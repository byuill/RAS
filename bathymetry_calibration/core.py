"""Signed bulk-bed geometry change; all lengths and elevations are in metres."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


class CalibrationError(ValueError):
    pass


def normalize_profile(frame):
    required = {'xs_id', 'u_m', 'z_m'}
    if not required <= set(frame):
        raise CalibrationError(f'Profiles require columns {sorted(required)}.')
    out = frame[list(sorted(required))].copy()
    out['xs_id'] = out.xs_id.astype(str)
    for column in ('u_m', 'z_m'):
        out[column] = pd.to_numeric(out[column], errors='raise')
    if not np.isfinite(out.u_m).all() or np.isinf(out.z_m).any():
        raise CalibrationError('Stations must be finite; elevations may contain NaN, never infinity.')
    if out.duplicated(['xs_id', 'u_m']).any():
        out = out.groupby(['xs_id', 'u_m'], as_index=False).mean()
    return out.sort_values(['xs_id', 'u_m']).reset_index(drop=True)


def profile_extent(frame, xs_id):
    """(min_u, max_u) of finite-elevation stations for one section, or None."""
    group = frame[(frame.xs_id == str(xs_id)) & np.isfinite(frame.z_m)]
    if len(group) < 2:
        return None
    return float(group.u_m.min()), float(group.u_m.max())


def interpolate_profile(frame, xs_id, target_u, max_gap_m):
    """Linear interpolation between finite neighbours; never extrapolates.

    Targets outside the profile's finite extent, or inside a data gap wider than
    ``max_gap_m``, are NaN. NaN knots are skipped (bridged only if the resulting
    gap is within ``max_gap_m``).
    """
    target_u = np.asarray(target_u, dtype=float)
    group = frame[(frame.xs_id == str(xs_id)) & np.isfinite(frame.z_m)].sort_values('u_m')
    result = np.full(len(target_u), np.nan)
    if len(group) < 2:
        return result
    x, z = group.u_m.to_numpy(), group.z_m.to_numpy()
    hi = np.clip(np.searchsorted(x, target_u, side='right'), 1, len(x) - 1)
    lo = hi - 1
    eps = 1e-8
    ok = (target_u >= x[0] - eps) & (target_u <= x[-1] + eps) & (x[hi] - x[lo] <= max_gap_m)
    result[ok] = np.interp(target_u[ok], x, z)
    return result


def validate_transects(frame):
    required = {'xs_id', 'model_column', 'chainage_m', 'length_to_next_m', 'u_m', 'x_m', 'y_m'}
    if not required <= set(frame):
        raise CalibrationError(f'Transects require columns {sorted(required)}.')
    frame = frame.copy()
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
                     grid_spacing_m=10.0, min_common_width_m=50.0, **sampling_options):
    """Compare model vs observed bed change on a per-section common lateral domain.

    The four profiles (model before/after, survey before/after) need not share
    stations or extents. For each section the common domain is the intersection
    of their finite lateral extents; all are linearly interpolated (no
    extrapolation) onto one uniform grid, so model and observed area changes are
    integrated over exactly the same lateral support. Sections without enough
    common support are excluded and volumes are integrated between the retained
    sections using their actual chainage separation.
    """
    if not np.isfinite([max_gap_m, min_coverage, max_reach_length_m, grid_spacing_m, min_common_width_m]).all():
        raise CalibrationError('Coverage and gap controls must be finite.')
    if (max_gap_m <= 0 or not 0 < min_coverage <= 1 or max_reach_length_m <= 0
            or grid_spacing_m <= 0 or min_common_width_m < 0):
        raise CalibrationError('Invalid coverage or gap controls.')
    transects, sections = validate_transects(transects)
    sources = [normalize_profile(p) for p in
               (model_before, model_after, observed_before, observed_after)]
    rows, skipped = [], []
    names = ('model_before', 'model_after', 'obs_before', 'obs_after')
    for row in sections.itertuples():
        extents = [profile_extent(p, row.xs_id) for p in sources]
        diag = {'xs_id': row.xs_id, 'chainage_m': row.chainage_m}
        for name, e in zip(names, extents):
            diag[f'{name}_u_min'], diag[f'{name}_u_max'] = (e if e else (np.nan, np.nan))
        u = common_domain_grid(extents, grid_spacing_m, min_common_width_m)
        if u is None:
            skipped.append({**diag, 'reason': 'no/insufficient common lateral extent', 'coverage': 0.0})
            continue
        profiles = [interpolate_profile(p, row.xs_id, u, max_gap_m) for p in sources]
        valid = np.logical_and.reduce([np.isfinite(p) for p in profiles])
        widths = np.diff(u)
        accepted = valid[:-1] & valid[1:]
        coverage = float(widths[accepted].sum() / widths.sum())
        if coverage < min_coverage - 1e-10:
            skipped.append({**diag, 'reason': 'common-domain data coverage below minimum', 'coverage': coverage})
            continue
        dm, do = profiles[1] - profiles[0], profiles[3] - profiles[2]
        def area(delta):
            return float(np.sum(0.5 * (delta[:-1][accepted] + delta[1:][accepted]) * widths[accepted]))
        rows.append({'xs_id': row.xs_id, 'model_column': int(row.model_column),
                     'chainage_m': row.chainage_m, 'coverage': coverage,
                     'common_u_min_m': float(u[0]), 'common_u_max_m': float(u[-1]),
                     'common_width_m': float(u[-1] - u[0]),
                     'effective_width_m': float(widths[accepted].sum()),
                     'model_area_change_m2': area(dm), 'observed_area_change_m2': area(do),
                     'model_baseline_elev_m': area(profiles[0]) / float(widths[accepted].sum()),
                     'model_target_elev_m': area(profiles[1]) / float(widths[accepted].sum()),
                     'observed_baseline_elev_m': area(profiles[2]) / float(widths[accepted].sum()),
                     'observed_target_elev_m': area(profiles[3]) / float(widths[accepted].sum())})
    excluded = pd.DataFrame(skipped)
    if len(rows) < 2:
        detail = ''
        if len(excluded):
            detail = ' Reasons: ' + '; '.join(f'{k}={v}' for k, v in excluded.reason.value_counts().items()) + '.'
            first = excluded.iloc[0]
            detail += (f' Example {first.xs_id}: ' + ', '.join(
                f'{n} u=[{first[f"{n}_u_min"]:.1f}, {first[f"{n}_u_max"]:.1f}]' for n in names))
        raise CalibrationError(f'Fewer than two cross sections have a usable common domain '
                               f'(min coverage {min_coverage:.1%}, min width {min_common_width_m} m).{detail}')
    table = pd.DataFrame(rows)
    sections = sections.set_index('xs_id').loc[table.xs_id].reset_index()
    lengths = np.diff(sections.chainage_m.to_numpy())
    if (lengths > max_reach_length_m).any():
        raise CalibrationError('A reach gap between retained sections exceeds the configured integration limit.')
    sections['length_to_next_m'] = np.r_[lengths, np.nan]
    model = 0.5 * (table.model_area_change_m2.to_numpy()[:-1] + table.model_area_change_m2.to_numpy()[1:]) * lengths
    observed = 0.5 * (table.observed_area_change_m2.to_numpy()[:-1] + table.observed_area_change_m2.to_numpy()[1:]) * lengths
    table['model_interval_prefix_m3'] = np.r_[0.0, np.cumsum(model)]
    table['observed_interval_prefix_m3'] = np.r_[0.0, np.cumsum(observed)]
    weights = np.r_[lengths[0]/2, (lengths[:-1]+lengths[1:])/2, lengths[-1]/2]
    table['control_length_m'] = weights
    table['model_local_control_volume_m3'] = table.model_area_change_m2 * weights
    table['observed_local_control_volume_m3'] = table.observed_area_change_m2 * weights
    table['model_cumulative_m3'] = table.model_local_control_volume_m3.cumsum()
    table['observed_cumulative_m3'] = table.observed_local_control_volume_m3.cumsum()
    table['cumulative_residual_m3'] = table.model_cumulative_m3 - table.observed_cumulative_m3
    intervals = pd.DataFrame({'upstream_xs': table.xs_id[:-1].to_numpy(),
                              'downstream_xs': table.xs_id[1:].to_numpy(), 'length_m': lengths,
                              'model_volume_change_m3': model, 'observed_volume_change_m3': observed,
                              'residual_m3': model-observed})
    residual = model-observed
    metrics = {'model_total_m3': float(model.sum()), 'observed_total_m3': float(observed.sum()),
               'total_bias_m3': float(residual.sum()), 'interval_rmse_m3': float(np.sqrt(np.mean(residual**2))),
               'interval_mae_m3': float(np.mean(np.abs(residual))),
               'cumulative_rmse_m3': float(np.sqrt(np.mean(table.cumulative_residual_m3.to_numpy()**2))),
               'volume_per_length_rmse_m2': float(np.sqrt(np.average((residual/lengths)**2, weights=lengths))),
               'minimum_common_coverage': float(table.coverage.min()),
               'sections_used': int(len(table)), 'sections_excluded': int(len(excluded))}
    return Comparison(table, intervals, metrics, excluded)