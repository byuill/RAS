"""Signed bulk-bed geometry change; all lengths and elevations are in metres."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class CalibrationError(ValueError):
    pass


def normalize_profile(frame):
    required = {'xs_id', 'u_m', 'z_m'}
    if not required <= set(frame):
        raise CalibrationError(f'Profiles require columns {sorted(required)}.')
    out = frame[list(sorted(required))].copy()
    if out.xs_id.isna().any() or out.xs_id.astype(str).str.strip().eq('').any():
        raise CalibrationError('Profile cross-section IDs must be present.')
    out['xs_id'] = out.xs_id.astype(str)
    for column in ('u_m', 'z_m'):
        out[column] = pd.to_numeric(out[column], errors='raise')
    if not np.isfinite(out.u_m).all() or np.isinf(out.z_m).any():
        raise CalibrationError('Stations must be finite; elevations may contain NaN, never infinity.')
    if out.duplicated(['xs_id', 'u_m']).any():
        raise CalibrationError('Duplicate lateral stations require an explicit QA/QC decision.')
    return out.sort_values(['xs_id', 'u_m']).reset_index(drop=True)


def profile_extent(frame, xs_id):
    """(min_u, max_u) of finite-elevation stations for one section, or None."""
    group = frame[(frame.xs_id == str(xs_id)) & np.isfinite(frame.z_m)]
    if len(group) < 2:
        return None
    return float(group.u_m.min()), float(group.u_m.max())


def interpolate_profile(frame, xs_id, target_u, max_gap_m):
    """Linear interpolation without extrapolation or crossing NaN/gap barriers."""
    target_u = np.asarray(target_u, dtype=float)
    group = frame[frame.xs_id == str(xs_id)].sort_values('u_m')
    result = np.full(len(target_u), np.nan)
    if len(group) < 2:
        return result
    x, z = group.u_m.to_numpy(), group.z_m.to_numpy()
    hi = np.clip(np.searchsorted(x, target_u, side='left'), 1, len(x) - 1)
    lo = hi - 1
    eps = 1e-8
    ok = ((target_u >= x[0]) & (target_u <= x[-1]) &
          (x[hi] - x[lo] <= max_gap_m) & np.isfinite(z[lo]) & np.isfinite(z[hi]))
    result[ok] = np.interp(target_u[ok], x, z)
    # Exact finite knots survive even next to a missing point or large gap.
    for candidates in (lo, hi):
        exact = np.isclose(x[candidates], target_u, rtol=0, atol=eps)
        result[exact] = z[candidates[exact]]
    return result


def validate_transects(frame):
    required = {'xs_id', 'model_column', 'chainage_m', 'length_to_next_m', 'u_m', 'x_m', 'y_m'}
    if not required <= set(frame):
        raise CalibrationError(f'Transects require columns {sorted(required)}.')
    frame = frame.copy()
    if frame.xs_id.isna().any() or frame.xs_id.astype(str).str.strip().eq('').any():
        raise CalibrationError('Transect cross-section IDs must be present.')
    frame['xs_id'] = frame.xs_id.astype(str)
    for column in required - {'xs_id'}:
        frame[column] = pd.to_numeric(frame[column], errors='raise')
    if not np.isfinite(frame[list(required - {'xs_id', 'length_to_next_m'})]).all().all():
        raise CalibrationError('Transect coordinates and identifiers must be finite.')
    if frame.duplicated(['xs_id', 'u_m']).any():
        raise CalibrationError('Duplicate transect stations.')
    metadata = []
    for xs_id, group in frame.groupby('xs_id', sort=False):
        for column in ('model_column', 'chainage_m', 'length_to_next_m'):
            if group[column].nunique(dropna=False) != 1:
                raise CalibrationError(f'{xs_id}: inconsistent {column}.')
        if len(group) < 2:
            raise CalibrationError(f'{xs_id}: a transect requires at least two knots.')
        metadata.append(group.iloc[0])
    sections = pd.DataFrame(metadata).sort_values('chainage_m').reset_index(drop=True)
    if len(sections) < 2 or (np.diff(sections.chainage_m) <= 0).any():
        raise CalibrationError('Select one reach with unique downstream-increasing chainage and at least two XS.')
    columns = sections.model_column.to_numpy()
    if (columns < 0).any() or (columns != np.floor(columns)).any() or len(set(columns)) != len(columns):
        raise CalibrationError('Model columns must be distinct nonnegative integer HDF column indices.')
    lengths = sections.length_to_next_m.to_numpy()[:-1]
    if not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise CalibrationError('Every upstream section requires a verified positive downstream reach length.')
    return frame, sections


@dataclass
class Comparison:
    sections: pd.DataFrame
    intervals: pd.DataFrame
    metrics: dict
    excluded: pd.DataFrame = None
    profiles: pd.DataFrame = field(default_factory=pd.DataFrame)
    zones: pd.DataFrame = field(default_factory=pd.DataFrame)
    confusion: pd.DataFrame = field(default_factory=pd.DataFrame)
    qaqc: pd.DataFrame = field(default_factory=pd.DataFrame)


def common_domain_grid(extents, spacing_m, min_width_m):
    """Uniform grid over the intersection of all source extents (None if empty/too narrow)."""
    if any(e is None for e in extents):
        return None
    lo, hi = max(e[0] for e in extents), min(e[1] for e in extents)
    if hi - lo < max(min_width_m, spacing_m * 1e-6) or hi <= lo:
        return None
    n = max(int(np.ceil((hi - lo) / spacing_m)), 1)
    return np.linspace(lo, hi, n + 1)


def compare_profiles(transects, model_before, model_after, observed_before, observed_after,
                     *, max_gap_m=25.0, min_coverage=1.0, max_reach_length_m=10000.0,
                     grid_spacing_m=10.0, min_common_width_m=0.0, domain_mode='intersection',
                     support_profiles=None, diagnostics=None, sample_spacing_m=10.0,
                     longitudinal_limit_m=50.0):
    """Integrate matched profiles without bridging unsupported XS or lateral holes.

    Intersection mode compares the overlap of all profiles within each manifest
    transect. Transect mode requires coverage of the entire specified footprint.
    Extra support_profiles can hold all epochs for a time series, fixing support
    across its intervals. Original verified channel lengths remain authoritative.
    """
    controls = [max_gap_m, min_coverage, max_reach_length_m, grid_spacing_m, min_common_width_m]
    if not np.isfinite(controls).all() or (min(controls[:4]) <= 0 or min_common_width_m < 0 or min_coverage > 1):
        raise CalibrationError('Coverage and gap controls must be finite and valid.')
    if domain_mode not in ('intersection', 'transect'):
        raise CalibrationError('domain_mode must be intersection or transect.')
    transects, metadata = validate_transects(transects)
    sources = [normalize_profile(p) for p in (model_before, model_after, observed_before, observed_after)]
    support = sources + [normalize_profile(p) for p in (support_profiles or [])]
    grouped = [{xs: group for xs, group in source.groupby('xs_id', sort=False)} for source in support]
    geometry_groups = {xs: group for xs, group in transects.groupby('xs_id', sort=False)}
    empty = pd.DataFrame(columns=['xs_id', 'u_m', 'z_m'])
    rows, skipped, sampled = [], [], []
    names = ('model_before', 'model_after', 'obs_before', 'obs_after')
    for position, row in enumerate(metadata.itertuples()):
        geometry = geometry_groups[row.xs_id]
        footprint = (float(geometry.u_m.min()), float(geometry.u_m.max()))
        profiles_at_xs = [groups.get(row.xs_id, empty) for groups in grouped]
        extents = [profile_extent(p, row.xs_id) for p in profiles_at_xs]
        diag = {'xs_id': row.xs_id, 'chainage_m': row.chainage_m}
        for name, extent in zip(names, extents):
            diag[f'{name}_u_min'], diag[f'{name}_u_max'] = extent or (np.nan, np.nan)
        domain = extents + [footprint] if domain_mode == 'intersection' else [footprint]
        u = common_domain_grid(domain, min(grid_spacing_m, max_gap_m/2), min_common_width_m)
        if u is None:
            skipped.append({**diag, 'reason': 'no/insufficient common lateral extent', 'coverage': 0.0})
            continue
        # Include source knots, including NaN knots. This preserves holes and
        # piecewise-linear breakpoints that a coarse uniform grid could miss.
        knots = np.concatenate([p.u_m.to_numpy() for p in profiles_at_xs] + [geometry.u_m.to_numpy()])
        u = np.unique(np.r_[u, knots[(knots >= u[0]) & (knots <= u[-1])]])
        values = [interpolate_profile(p, row.xs_id, u, max_gap_m) for p in profiles_at_xs]
        valid = np.logical_and.reduce([np.isfinite(v) for v in values])
        midpoints = (u[:-1]+u[1:])/2
        midpoint_valid = np.logical_and.reduce([
            np.isfinite(interpolate_profile(p, row.xs_id, midpoints, max_gap_m)) for p in profiles_at_xs])
        widths = np.diff(u)
        accepted = valid[:-1] & valid[1:] & midpoint_valid
        effective = float(widths[accepted].sum())
        coverage = effective/float(widths.sum())
        if effective <= 0 or coverage < min_coverage-1e-10:
            skipped.append({**diag, 'reason': 'common-domain data coverage below minimum', 'coverage': coverage})
            continue
        dm, do = values[1]-values[0], values[3]-values[2]
        def area(v):
            return float(np.sum(0.5*(v[:-1][accepted]+v[1:][accepted])*widths[accepted]))
        accepted_points = np.r_[accepted, False] | np.r_[False, accepted]
        sampled.append(pd.DataFrame({'xs_id': row.xs_id, 'u_m': u, 'chainage_m': row.chainage_m,
                                     'model_before_z_m': values[0], 'model_after_z_m': values[1],
                                     'observed_before_z_m': values[2], 'observed_after_z_m': values[3],
                                     'model_change_m': dm, 'observed_change_m': do,
                                     'accepted_point': accepted_points,
                                     'accepted_interval_to_next': np.r_[accepted, False]}))
        rows.append({'xs_id': row.xs_id, 'model_column': int(row.model_column), 'source_position': position,
                     'chainage_m': row.chainage_m, 'length_to_next_m': row.length_to_next_m,
                     'coverage': coverage, 'footprint_coverage': effective/(footprint[1]-footprint[0]),
                     'common_u_min_m': float(u[0]), 'common_u_max_m': float(u[-1]),
                     'common_width_m': float(u[-1]-u[0]), 'effective_width_m': effective,
                     'model_area_change_m2': area(dm), 'observed_area_change_m2': area(do),
                     'model_baseline_elev_m': area(values[0])/effective,
                     'model_target_elev_m': area(values[1])/effective,
                     'observed_baseline_elev_m': area(values[2])/effective,
                     'observed_target_elev_m': area(values[3])/effective})
    if rows:
        table = pd.DataFrame(rows)
        positions = table.source_position.to_numpy()
        adjacent = np.diff(positions) == 1
        connected = np.r_[adjacent, False] | np.r_[False, adjacent]
        for row in table[~connected].itertuples():
            skipped.append({'xs_id': row.xs_id, 'chainage_m': row.chainage_m,
                            'reason': 'isolated section; unsupported coverage is not bridged', 'coverage': row.coverage})
        table = table[connected].reset_index(drop=True)
    else:
        table = pd.DataFrame()
    excluded = pd.DataFrame(skipped)
    if len(table) < 2:
        details = '; '.join(f'{k}={v}' for k, v in excluded.reason.value_counts().items()) if len(excluded) else ''
        raise CalibrationError(f'Fewer than two adjacent XS have usable common coverage. {details}')
    adjacent = np.diff(table.source_position.to_numpy()) == 1
    upstream = np.flatnonzero(adjacent)
    lengths = table.length_to_next_m.to_numpy()[upstream]
    if (lengths > max_reach_length_m).any():
        raise CalibrationError('A reach gap exceeds the configured integration limit.')
    table['segment_id'] = np.r_[0, np.cumsum(~adjacent)]
    m, o = table.model_area_change_m2.to_numpy(), table.observed_area_change_m2.to_numpy()
    model = 0.5*(m[upstream]+m[upstream+1])*lengths
    observed = 0.5*(o[upstream]+o[upstream+1])*lengths
    weights = np.zeros(len(table))
    weights[upstream] += lengths/2
    weights[upstream+1] += lengths/2
    table['control_length_m'] = weights
    table['model_local_control_volume_m3'] = m*weights
    table['observed_local_control_volume_m3'] = o*weights
    for source, volumes in [('model', model), ('observed', observed)]:
        table[f'{source}_cumulative_m3'] = table.groupby('segment_id')[f'{source}_local_control_volume_m3'].cumsum()
        interval_at_node = np.zeros(len(table))
        interval_at_node[upstream+1] = volumes
        table[f'{source}_interval_prefix_m3'] = pd.Series(interval_at_node).groupby(table.segment_id).cumsum()
    table['cumulative_residual_m3'] = table.model_cumulative_m3-table.observed_cumulative_m3
    intervals = pd.DataFrame({'upstream_xs': table.xs_id.to_numpy()[upstream],
                              'downstream_xs': table.xs_id.to_numpy()[upstream+1],
                              'segment_id': table.segment_id.to_numpy()[upstream], 'length_m': lengths,
                              'mid_chainage_m': (table.chainage_m.to_numpy()[upstream]+table.chainage_m.to_numpy()[upstream+1])/2,
                              'model_volume_change_m3': model, 'observed_volume_change_m3': observed,
                              'residual_m3': model-observed})
    residual = model-observed
    metrics = {'model_total_m3': float(model.sum()), 'observed_total_m3': float(observed.sum()),
               'total_bias_m3': float(residual.sum()), 'interval_rmse_m3': float(np.sqrt(np.mean(residual**2))),
               'interval_mae_m3': float(np.mean(abs(residual))),
               'cumulative_rmse_m3': float(np.sqrt(np.mean(table.cumulative_residual_m3.to_numpy()**2))),
               'volume_per_length_rmse_m2': float(np.sqrt(np.average((residual/lengths)**2, weights=lengths))),
               'minimum_common_coverage': float(table.coverage.min()),
               'minimum_footprint_coverage': float(table.footprint_coverage.min()),
               'integrated_reach_length_m': float(lengths.sum()), 'supported_segments': int(table.segment_id.nunique()),
               'sections_used': len(table), 'sections_excluded': len(excluded)}
    samples = pd.concat(sampled, ignore_index=True)
    samples = samples[samples.xs_id.isin(table.xs_id)].reset_index(drop=True)
    result = Comparison(table.drop(columns='source_position'), intervals, metrics, excluded, samples)
    from .diagnostics import add_diagnostics
    return add_diagnostics(result, **(diagnostics or {}))
