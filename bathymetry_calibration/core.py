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
        raise CalibrationError('Duplicate lateral stations require an explicit QA/QC decision.')
    return out.sort_values(['xs_id', 'u_m']).reset_index(drop=True)


def interpolate_profile(frame, xs_id, target_u, max_gap_m):
    """Linear interpolation without extrapolation, gap filling, or crossing NaN knots."""
    group = frame[frame.xs_id == str(xs_id)].sort_values('u_m')
    if len(group) < 2:
        raise CalibrationError(f'{xs_id}: fewer than two source profile points.')
    x, z = group.u_m.to_numpy(), group.z_m.to_numpy()
    result = np.full(len(target_u), np.nan)
    for j, u in enumerate(target_u):
        i = int(np.searchsorted(x, u))
        if i < len(x) and np.isclose(x[i], u, rtol=0, atol=1e-8):
            result[j] = z[i]
        elif 0 < i < len(x) and x[i] - x[i-1] <= max_gap_m:
            if np.isfinite(z[i-1:i+1]).all():
                result[j] = np.interp(u, x[i-1:i+1], z[i-1:i+1])
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


def compare_profiles(transects, model_before, model_after, observed_before, observed_after,
                     *, max_gap_m=25.0, min_coverage=1.0, max_reach_length_m=10000.0):
    if not np.isfinite([max_gap_m, min_coverage, max_reach_length_m]).all():
        raise CalibrationError('Coverage and gap controls must be finite.')
    if max_gap_m <= 0 or not 0 < min_coverage <= 1 or max_reach_length_m <= 0:
        raise CalibrationError('Invalid coverage or gap controls.')
    transects, sections = validate_transects(transects)
    sources = [normalize_profile(p) for p in
               (model_before, model_after, observed_before, observed_after)]
    rows = []
    for row in sections.itertuples():
        grid = transects[transects.xs_id == row.xs_id].sort_values('u_m')
        u = grid.u_m.to_numpy()
        profiles = [interpolate_profile(p, row.xs_id, u, max_gap_m) for p in sources]
        valid = np.logical_and.reduce([np.isfinite(p) for p in profiles])
        widths = np.diff(u)
        accepted = valid[:-1] & valid[1:] & (widths <= max_gap_m)
        coverage = float(widths[accepted].sum() / widths.sum())
        if coverage < min_coverage - 1e-10:
            raise CalibrationError(f'{row.xs_id}: common lateral coverage {coverage:.1%} < '
                                   f'{min_coverage:.1%}. Never fill missing bathymetry with zero.')
        dm, do = profiles[1] - profiles[0], profiles[3] - profiles[2]
        def area(delta):
            return float(np.sum(0.5 * (delta[:-1][accepted] + delta[1:][accepted]) * widths[accepted]))
        rows.append({'xs_id': row.xs_id, 'model_column': int(row.model_column),
                     'chainage_m': row.chainage_m, 'coverage': coverage,
                     'effective_width_m': float(widths[accepted].sum()),
                     'model_area_change_m2': area(dm), 'observed_area_change_m2': area(do)})
    table = pd.DataFrame(rows)
    lengths = sections.length_to_next_m.to_numpy()[:-1]
    if (lengths > max_reach_length_m).any():
        raise CalibrationError('A reach gap exceeds the configured integration limit.')
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
               'minimum_common_coverage': float(table.coverage.min())}
    return Comparison(table, intervals, metrics)
