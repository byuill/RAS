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


def read_survey(source, transects, settings):
    if source['kind'] == 'csv':
        # This format is already metres and common-datum bed elevations, not depths.
        return normalize_profile(pd.read_csv(source['path'], dtype={'xs_id': str}))
    knots = transects[['xs_id', 'u_m', 'x_m', 'y_m']].to_dict('records')
    if source['kind'] == 'gdb_raster':
        spacing = float(settings.get('integration', {}).get('sample_spacing_m', 10.0))
        knots = densify_transects(transects, spacing)
    records = arcpy_request({'operation': 'profiles', 'source': source, 'knots': knots,
                             'analysis_crs': settings['analysis_crs']}, settings.get('arcpy_python'))
                             
    if source['kind'] == 'gdb_points_raw':
        # records has x_m, y_m, z_m
        import scipy.spatial
        mapped_records = []
        limits = settings.get('integration', {})
        transverse_limit = limits.get('transverse_limit_m', 50.0)
        longitudinal_limit = limits.get('longitudinal_limit_m', 50.0)
        
        pts = np.array([[r['x_m'], r['y_m']] for r in records])
        tree = scipy.spatial.KDTree(pts)
        
        for xs_id, group in transects.groupby('xs_id', sort=False):
            x = group.x_m.values
            y = group.y_m.values
            u = group.u_m.values
            
            # For each segment of the cross section
            for i in range(len(x) - 1):
                p1 = np.array([x[i], y[i]])
                p2 = np.array([x[i+1], y[i+1]])
                seg_vec = p2 - p1
                seg_len = np.linalg.norm(seg_vec)
                if seg_len < 1e-6: continue
                seg_dir = seg_vec / seg_len
                
                # Bounding box of segment expanded by limits
                min_x, max_x = min(x[i], x[i+1]) - longitudinal_limit, max(x[i], x[i+1]) + longitudinal_limit
                min_y, max_y = min(y[i], y[i+1]) - longitudinal_limit, max(y[i], y[i+1]) + longitudinal_limit
                
                # Query rough candidates
                candidates = tree.query_ball_point((p1 + p2)/2, seg_len/2 + longitudinal_limit + transverse_limit)
                
                for idx in candidates:
                    pt = pts[idx]
                    vec = pt - p1
                    proj = np.dot(vec, seg_dir)
                    # transverse check (along XS)
                    if -transverse_limit <= proj <= seg_len + transverse_limit:
                        # longitudinal check (perpendicular distance to XS)
                        perp_dist = np.abs(np.cross(seg_dir, vec))
                        if perp_dist <= longitudinal_limit:
                            mapped_records.append({
                                'xs_id': xs_id,
                                'u_m': u[i] + proj,
                                'z_m': records[idx]['z_m']
                            })
        records = mapped_records
        
    return normalize_profile(pd.DataFrame(records))


def read_model_profiles(hdf_path, mapping, transects, before_index, after_index):
    if mapping.get('profile_mapping_verified') is not True:
        raise CalibrationError('Verify evolving model profile datasets, XS column IDs, and station orientation locally first.')
    if before_index < 0 or after_index <= before_index:
        raise CalibrationError('Model output indices must be nonnegative and ordered baseline < target.')
    frames = [[], []]
    with h5py.File(hdf_path, 'r') as h5:
        if mapping.get('layout') == 'ragged_se':
            # Handle ragged HEC-RAS 1D Station Elevation layout
            time_ds = h5[mapping['time_dataset']]
            times = [s.decode().strip() if isinstance(s, bytes) else str(s).strip() for s in time_ds[:]]
            base_group = mapping['se_group']
            for output, index in zip(frames, (before_index, after_index)):
                time_str = times[index]
                info = h5[f'{base_group}/Station Elevation ({time_str}) info'][:]
                values = h5[f'{base_group}/Station Elevation ({time_str}) values'][:]
                
                for xs_id, group in transects.groupby('xs_id', sort=False):
                    column = int(group.model_column.iloc[0])
                    if not 0 <= column < len(info):
                        raise CalibrationError(f'{xs_id}: HDF column outside profile data.')
                    start, count = info[column]
                    xs_data = values[start:start+count]
                    
                    stations = np.asarray(xs_data[:, 0], dtype=float) * mapping['u_scale_to_m']
                    stations += mapping.get('u_offset_m', 0.0)
                    elevation = np.asarray(xs_data[:, 1], dtype=float) * mapping['z_scale_to_m']
                    elevation += mapping.get('z_offset_m', 0.0)
                    
                    output.extend({'xs_id': xs_id, 'u_m': float(s), 'z_m': float(v)} for s, v in zip(stations, elevation))
        else:
            z = h5[mapping['elevation_dataset']]
            u = h5[mapping['station_dataset']]
            if z.ndim != 3 or z.dtype.kind not in 'fiu':
                raise CalibrationError('Starter HDF profile adapter expects numeric [time, XS, knot] elevations. Other layouts need a local adapter.')
            if u.shape not in ((z.shape[2],), (z.shape[1], z.shape[2])) or u.dtype.kind not in 'fiu':
                raise CalibrationError('Lateral stations must be [knot] or [XS, knot]. Ragged/time-varying profiles require a local adapter.')
            if after_index >= z.shape[0]:
                raise CalibrationError('Selected output index lies outside the model profiles.')
            for xs_id, group in transects.groupby('xs_id', sort=False):
                column = int(group.model_column.iloc[0])
                if not 0 <= column < z.shape[1]:
                    raise CalibrationError(f'{xs_id}: HDF column outside profile data.')
                stations = np.asarray(u[:] if u.ndim == 1 else u[column, :], dtype=float) * mapping['u_scale_to_m']
                stations += mapping.get('u_offset_m', 0.0)
                for output, index in zip(frames, (before_index, after_index)):
                    elevation = np.asarray(z[index, column, :], dtype=float) * mapping['z_scale_to_m'] + mapping.get('z_offset_m', 0.0)
                    output.extend({'xs_id': xs_id, 'u_m': float(s), 'z_m': float(v)} for s, v in zip(stations, elevation))
    return [normalize_profile(pd.DataFrame(frame)) for frame in frames]


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
        order = mapping.get('spatial_order_columns')
        if semantics == 'spatial_temporally_cumulative':
            if order is None or sorted(order) != list(range(dataset.shape[1])):
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
    if mapping.get('time_format') == 'hec':
        from ras.hdf_reader import parse_time_stamps
        times = parse_time_stamps(np.asarray(text))
    else:
        times = pd.DatetimeIndex(pd.to_datetime(text, errors='raise'))
    if times.tz is not None or times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise CalibrationError('Model times must be unique, increasing, and on an explicitly aligned naive local clock.')
    return times