"""Explicit source mapping: no guessed HDF names, survey units, or datum transforms."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import h5py
import numpy as np
import pandas as pd

from .core import CalibrationError, normalize_profile
from .qaqc import survey_frame


def arcpy_request(request, python_executable=None):
    bridge = Path(__file__).with_name('arcpy_bridge.py')
    with tempfile.TemporaryDirectory(prefix='bathy-arcpy-') as directory:
        incoming, outgoing = Path(directory)/'request.json', Path(directory)/'response.json'
        incoming.write_text(json.dumps(request, allow_nan=False), encoding='utf-8')
        result = subprocess.run([python_executable or sys.executable, str(bridge), str(incoming), str(outgoing)],
                                capture_output=True, text=True, timeout=3600, check=False)
        if not outgoing.exists():
            raise CalibrationError(f'ArcPy bridge failed (exit {result.returncode}): {result.stderr[-2000:]}')
        response = json.loads(outgoing.read_text(encoding='utf-8'))
        if result.returncode or 'error' in response:
            raise CalibrationError(response.get('error', result.stderr[-2000:]))
        return response['result']


def densify_transects(transects, spacing_m):
    """Regular (u, x, y) samples along each transect polyline, always including every knot."""
    if not np.isfinite(spacing_m) or spacing_m <= 0:
        raise CalibrationError('sample_spacing_m must be positive and finite.')
    out = []
    for xs_id, group in transects.groupby('xs_id', sort=False):
        group = group.sort_values('u_m')
        u, x, y = group.u_m.to_numpy(), group.x_m.to_numpy(), group.y_m.to_numpy()
        stations = np.unique(np.r_[np.arange(u[0], u[-1], spacing_m), u])
        xs, ys = np.interp(stations, u, x), np.interp(stations, u, y)
        out.extend({'xs_id': xs_id, 'u_m': float(s), 'x_m': float(a), 'y_m': float(b)}
                   for s, a, b in zip(stations, xs, ys))
    return out


def map_xyz_points(records, transects, *, longitudinal_limit_m=50.0, ambiguity_tolerance_m=0.01):
    """Assign each XYZ point once to its nearest polyline, with no endpoint extension.

    Points equidistant from different XS are left unmatched. Lateral stations
    interpolate the manifest's u values, respecting curved polylines and units.
    """
    from scipy.spatial import cKDTree
    if not np.isfinite([longitudinal_limit_m, ambiguity_tolerance_m]).all() or longitudinal_limit_m <= 0 or ambiguity_tolerance_m < 0:
        raise CalibrationError('XYZ mapping distance limits must be finite and valid.')
    points = pd.DataFrame(records)
    if not {'x_m', 'y_m', 'z_m'} <= set(points):
        raise CalibrationError('XYZ sources require x_m, y_m, z_m.')
    xy = points[['x_m', 'y_m']].to_numpy(dtype=float)
    valid_xy = np.isfinite(xy).all(axis=1)
    selected = np.flatnonzero(valid_xy)
    if not len(selected):
        raise CalibrationError('No finite XYZ survey coordinates.')
    tree = cKDTree(xy[selected])
    best, second = np.full(len(points), np.inf), np.full(len(points), np.inf)
    identities = np.full(len(points), '', dtype=object)
    stations = np.full(len(points), np.nan)
    for xs_id, group in transects.groupby('xs_id', sort=False):
        group = group.sort_values('u_m')
        line = group[['x_m', 'y_m']].to_numpy()
        u = group.u_m.to_numpy()
        # First find the closest segment within each XS, then compare XS.
        distance, station = {}, {}
        for i, (start, end) in enumerate(zip(line[:-1], line[1:])):
            vector = end-start
            length = np.linalg.norm(vector)
            if length <= 1e-9:
                continue
            candidates = selected[tree.query_ball_point((start+end)/2, length/2+longitudinal_limit_m)]
            if not len(candidates):
                continue
            relative = xy[candidates]-start
            fraction = np.clip(relative @ vector/(length*length), 0, 1)
            distances = np.linalg.norm(xy[candidates]-(start+fraction[:, None]*vector), axis=1)
            for idx, fraction_i, dist in zip(candidates, fraction, distances):
                if dist <= longitudinal_limit_m and dist < distance.get(idx, np.inf):
                    distance[idx] = dist
                    station[idx] = u[i]+fraction_i*(u[i+1]-u[i])
        for idx, dist in distance.items():
            if dist < best[idx]:
                second[idx], best[idx] = best[idx], dist
                identities[idx], stations[idx] = xs_id, station[idx]
            elif dist < second[idx]:
                second[idx] = dist
    matched = np.isfinite(best)
    ambiguous = np.zeros(len(points), dtype=bool)
    ambiguous[matched] = second[matched]-best[matched] <= ambiguity_tolerance_m
    rows = []
    for idx in np.flatnonzero(matched & ~ambiguous):
        rows.append({'xs_id': identities[idx], 'u_m': stations[idx], 'z_m': points.z_m.iloc[idx],
                     'source_point_id': int(idx), 'x_m': xy[idx, 0], 'y_m': xy[idx, 1],
                     'mapping_distance_m': best[idx]})
    if not rows:
        raise CalibrationError('No XYZ points unambiguously match the selected transects; inspect CRS and mapping distances.')
    frame = survey_frame(pd.DataFrame(rows))
    frame.attrs['mapping'] = {'input_points': len(points), 'mapped_points': len(rows),
                              'ambiguous_points': int(ambiguous.sum()),
                              'invalid_coordinates': int((~valid_xy).sum()),
                              'outside_mapping_limit': int((valid_xy & ~matched).sum())}
    return frame


def read_survey(source, transects, settings):
    kind = source['kind']
    if kind == 'csv':
        return survey_frame(pd.read_csv(source['path'], dtype={'xs_id': str}))
    if kind == 'xyz_csv':
        if source.get('horizontal_mapping_verified') is not True:
            raise CalibrationError('XYZ CSV coordinates require verified projected-metre analysis CRS alignment.')
        fields = source.get('fields', {'x': 'x_m', 'y': 'y_m', 'z': 'z_m'})
        frame = pd.read_csv(source['path'])
        try:
            frame = frame[[fields['x'], fields['y'], fields['z']]].copy()
            frame.columns = ['x_m', 'y_m', 'z_m']
            frame = frame.apply(pd.to_numeric, errors='raise')
        except (KeyError, ValueError) as exc:
            raise CalibrationError('XYZ CSV fields must exist and contain numeric coordinates/elevations.') from exc
        scale, offset = float(source.get('z_scale_to_m', 1)), float(source.get('z_offset_m', 0))
        if not np.isfinite([scale, offset]).all() or scale <= 0:
            raise CalibrationError('XYZ vertical scale must be positive and finite; offset finite.')
        frame['z_m'] = frame.z_m*scale+offset
        records = frame.to_dict('records')
    elif kind == 'raster':
        from .raster import read_raster
        return read_raster(source, transects, settings)
    elif kind in ('gdb_raster', 'gdb_points', 'gdb_points_raw'):
        knots = transects[['xs_id', 'u_m', 'x_m', 'y_m']].to_dict('records')
        if kind == 'gdb_raster':
            knots = densify_transects(transects, float(settings.get('integration', {}).get('sample_spacing_m', 10)))
        records = arcpy_request({'operation': 'profiles', 'source': source, 'knots': knots,
                                 'analysis_crs': settings['analysis_crs']}, settings.get('arcpy_python'))
    else:
        raise CalibrationError(f'Unsupported survey source kind: {kind}.')
    if kind in ('xyz_csv', 'gdb_points_raw'):
        return map_xyz_points(records, transects,
                              longitudinal_limit_m=float(settings.get('integration', {}).get('longitudinal_limit_m', 50)),
                              ambiguity_tolerance_m=float(source.get('ambiguity_tolerance_m', 0.01)))
    return survey_frame(pd.DataFrame(records))


def read_model_snapshots(hdf_path, mapping, transects, indices):
    """Read only requested XS and outputs, including selected ragged SE slices."""
    if mapping.get('profile_mapping_verified') is not True:
        raise CalibrationError('Verify evolving model profiles, XS column IDs, and station orientation locally first.')
    if any(not isinstance(index, (int, np.integer)) or index < 0 for index in indices):
        raise CalibrationError('Model output indices must be nonnegative integers.')
    frames = {int(index): [] for index in indices}
    factors = [float(mapping.get(key, 1)) for key in ('u_scale_to_m', 'z_scale_to_m')]
    offsets = [float(mapping.get(key, 0)) for key in ('u_offset_m', 'z_offset_m')]
    if not np.isfinite(factors+offsets).all() or min(factors) <= 0:
        raise CalibrationError('Model station/elevation scales must be finite and positive; offsets finite.')
    with h5py.File(hdf_path, 'r') as h5:
        time_ds = h5[mapping['time_dataset']]
        if any(index >= len(time_ds) for index in indices):
            raise CalibrationError('Selected model output index lies outside the date dataset.')
        if mapping.get('layout') == 'ragged_se':
            for index, output in frames.items():
                stamp = time_ds[index]
                stamp = stamp.decode().strip() if isinstance(stamp, bytes) else str(stamp).strip()
                base = f'{mapping["se_group"]}/Station Elevation ({stamp})'
                info, values = h5[base+' info'], h5[base+' values']
                if info.ndim != 2 or info.shape[1] != 2 or info.dtype.kind not in 'iu' or values.ndim != 2 or values.shape[1] != 2 or values.dtype.kind not in 'fiu':
                    raise CalibrationError('Ragged SE requires integer [XS, start/count] info and numeric [knot, station/elevation] values.')
                for xs_id, group in transects.groupby('xs_id', sort=False):
                    column = int(group.model_column.iloc[0])
                    if not 0 <= column < len(info):
                        raise CalibrationError(f'{xs_id}: HDF column outside profile data.')
                    start, count = map(int, info[column, :])
                    if start < 0 or count < 2 or start+count > len(values):
                        raise CalibrationError(f'{xs_id}: invalid ragged profile start/count.')
                    data = np.asarray(values[start:start+count, :], dtype=float)
                    output.extend({'xs_id': xs_id, 'u_m': float(u*factors[0]+offsets[0]),
                                   'z_m': float(z*factors[1]+offsets[1])} for u, z in data)
        else:
            z, u = h5[mapping['elevation_dataset']], h5[mapping['station_dataset']]
            if z.ndim != 3 or z.dtype.kind not in 'fiu' or z.shape[0] != len(time_ds):
                raise CalibrationError('HDF profile elevations must be numeric [time, XS, knot] and match the date count.')
            if u.shape not in ((z.shape[2],), (z.shape[1], z.shape[2])) or u.dtype.kind not in 'fiu':
                raise CalibrationError('Lateral stations must be numeric [knot] or [XS, knot].')
            for xs_id, group in transects.groupby('xs_id', sort=False):
                column = int(group.model_column.iloc[0])
                if not 0 <= column < z.shape[1]:
                    raise CalibrationError(f'{xs_id}: HDF column outside profile data.')
                stations = np.asarray(u[:] if u.ndim == 1 else u[column, :], dtype=float)*factors[0]+offsets[0]
                for index, output in frames.items():
                    elevations = np.asarray(z[index, column, :], dtype=float)*factors[1]+offsets[1]
                    output.extend({'xs_id': xs_id, 'u_m': float(s), 'z_m': float(v)} for s, v in zip(stations, elevations))
    return {index: normalize_profile(pd.DataFrame(frame)) for index, frame in frames.items()}


def read_model_profiles(hdf_path, mapping, transects, before_index, after_index):
    if after_index <= before_index:
        raise CalibrationError('Select ordered model baseline and target outputs.')
    snapshots = read_model_snapshots(hdf_path, mapping, transects, [before_index, after_index])
    return [snapshots[before_index], snapshots[after_index]]


def native_volume_audit(hdf_path, mapping, sections, before_index, after_index):
    """Recover local interval volumes from explicitly verified native cumulative variables."""
    if mapping.get('verified') is not True or not mapping.get('evidence', '').strip():
        raise CalibrationError('Native volume use requires recorded HEC documentation and a numerical local verification.')
    semantics = mapping.get('semantics')
    if semantics not in ('local_temporally_cumulative', 'spatial_temporally_cumulative') or mapping.get('basis') != 'bulk_geometric':
        raise CalibrationError('Incremental-time, sediment-solid, or unknown variables are not accepted by this adapter.')
    factor, sign = float(mapping['scale_to_m3']), float(mapping['deposition_sign'])
    if not np.isfinite([factor, sign]).all() or factor <= 0 or sign not in (-1, 1):
        raise CalibrationError('Native units and sign must be explicitly verified.')
    local = []
    with h5py.File(hdf_path, 'r') as h5:
        dataset = h5[mapping['dataset']]
        if dataset.ndim != 2 or dataset.dtype.kind not in 'fiu':
            raise CalibrationError('Native adapter expects numeric [time, XS] data.')
        if not 0 <= before_index < after_index < dataset.shape[0] or any(
                not 0 <= int(column) < dataset.shape[1] for column in sections.model_column):
            raise CalibrationError('Native volume output indices/XS columns lie outside the selected dataset.')
        order = mapping.get('spatial_order_columns')
        if semantics == 'spatial_temporally_cumulative':
            if (not order or any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c < dataset.shape[1] for c in order)
                    or len(set(order)) != len(order) or not set(sections.model_column) <= set(order)):
                raise CalibrationError('A spatially cumulative native variable requires the verified full upstream-to-downstream HDF column order for one reach.')
            positions = [order.index(int(c)) for c in sections.model_column]
            if (np.diff(positions) != 1).any():
                raise CalibrationError('Selected sections must be consecutive in the native spatial accumulation order.')
        for column in sections.model_column:
            value = float(dataset[after_index, int(column)]) - float(dataset[before_index, int(column)])
            if semantics == 'spatial_temporally_cumulative':
                position = order.index(int(column))
                if position:
                    previous = order[position-1]
                    value -= float(dataset[after_index, previous]) - float(dataset[before_index, previous])
            local.append(value * factor * sign)
    if not np.isfinite(local).all():
        raise CalibrationError('Native volume contains missing/nonfinite values.')
    return np.asarray(local)


def model_times(hdf_path, mapping):
    with h5py.File(hdf_path, 'r') as h5:
        dataset = h5[mapping['time_dataset']]
        if dataset.ndim != 1 or dataset.dtype.kind not in 'SO':
            raise CalibrationError('Starter requires a 1-D date-stamp dataset. Numeric-time layouts need explicit local conversion.')
        text = [s.decode().strip() if isinstance(s, bytes) else str(s).strip() for s in dataset[:]]
    import re
    hec_stamps = bool(text) and all(re.fullmatch(r'\d{2}[A-Za-z]{3}\d{4} \d{2}:\d{2}:\d{2}', stamp) for stamp in text)
    if mapping.get('time_format') == 'hec' or hec_stamps:
        from ras.hdf_reader import parse_time_stamps
        times = parse_time_stamps(np.asarray(text))
    else:
        times = pd.DatetimeIndex(pd.to_datetime(text, errors='raise'))
    if len(times) < 2 or times.tz is not None or times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise CalibrationError('Model times must be unique, increasing, and on an explicitly aligned naive local clock.')
    return times
