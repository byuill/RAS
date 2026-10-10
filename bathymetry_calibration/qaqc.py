"""Review survey elevations before interpolation; retain an audit of every input row."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .core import CalibrationError, normalize_profile


def survey_frame(frame):
    required = {'xs_id', 'u_m', 'z_m'}
    if not required <= set(frame):
        raise CalibrationError(f'Survey profiles require columns {sorted(required)}.')
    out = frame.copy().reset_index(drop=True)
    if out.xs_id.isna().any() or out.xs_id.astype(str).str.strip().eq('').any():
        raise CalibrationError('Survey cross-section IDs must be present.')
    out['xs_id'] = out.xs_id.astype(str)
    for column in ('u_m', 'z_m'):
        try:
            out[column] = pd.to_numeric(out[column], errors='raise').astype(float)
        except (ValueError, TypeError) as exc:
            raise CalibrationError(f'Survey {column} must be numeric; check units and NoData encoding.') from exc
    if not np.isfinite(out.u_m).all():
        raise CalibrationError('Survey lateral stations must be finite.')
    out['source_nonfinite'] = out.get('source_nonfinite', False) | ~np.isfinite(out.z_m)
    out.loc[~np.isfinite(out.z_m), 'z_m'] = np.nan
    return out


@dataclass
class SurveyReview:
    profile: pd.DataFrame
    audit: pd.DataFrame
    sections: pd.DataFrame
    summary: dict


def review_survey(frame, options=None, *, max_gap_m=25.0, allow_unresolved_duplicates=False):
    """Flag without removal by default. Explicit exclusion leaves NaN barrier knots.

    Optional limits are in metres, slope in m/m. A spike is deviation from linear
    interpolation of immediate neighbours, exceeding both a robust MAD cutoff
    and a minimum physical threshold. Natural banks can trigger flags: review
    them before choosing exclude_flagged. Duplicate aggregation is opt-in.
    """
    options = options or {}
    known = {'elevation_min_m', 'elevation_max_m', 'max_slope_m_per_m', 'spike_min_m',
             'robust_z_limit', 'exclude_flagged', 'excluded_points', 'duplicate_policy',
             'datum_correction_m', 'datum_correction_evidence'}
    if set(options)-known:
        raise CalibrationError(f'Unknown survey QA/QC options: {sorted(set(options)-known)}.')
    controls = {'spike_min_m': 1.0, 'robust_z_limit': 6.0, 'datum_correction_m': 0.0}
    controls.update({k: options[k] for k in known & set(options) if k not in
                     {'exclude_flagged', 'excluded_points', 'duplicate_policy', 'datum_correction_evidence'}})
    for key, value in controls.items():
        if not isinstance(value, (int, float)) or not np.isfinite(value):
            raise CalibrationError(f'QA/QC {key} must be finite and numeric.')
    if controls['spike_min_m'] < 0 or controls['robust_z_limit'] <= 0 or controls.get('max_slope_m_per_m', 1) <= 0:
        raise CalibrationError('QA/QC spike limits must be nonnegative and slope/robust limits positive.')
    if controls.get('elevation_min_m', -np.inf) >= controls.get('elevation_max_m', np.inf):
        raise CalibrationError('QA/QC elevation minimum must be below maximum.')
    if controls['datum_correction_m'] and not str(options.get('datum_correction_evidence', '')).strip():
        raise CalibrationError('Datum corrections require documented evidence; a uniform shift alone is insufficient.')
    if not isinstance(options.get('exclude_flagged', False), bool):
        raise CalibrationError('exclude_flagged must be true or false.')
    frame = survey_frame(frame)
    audit = frame.rename(columns={'z_m': 'original_z_m'}).copy()
    audit['used_z_m'] = audit.original_z_m + controls['datum_correction_m']
    audit['missing_or_nonfinite'] = audit.source_nonfinite
    audit['duplicate_station'] = audit.duplicated(['xs_id', 'u_m'], keep=False)
    audit['outside_elevation_limits'] = ((audit.used_z_m < controls.get('elevation_min_m', -np.inf)) |
                                        (audit.used_z_m > controls.get('elevation_max_m', np.inf)))
    audit['steep_slope'] = False
    audit['spike'] = False
    audit['gap_after_m'] = np.nan
    audit['spike_residual_m'] = np.nan
    summaries = []
    for xs_id, group in audit.groupby('xs_id', sort=False):
        group = group.sort_values('u_m')
        x, z = group.u_m.to_numpy(), group.used_z_m.to_numpy()
        gaps = np.diff(x)
        audit.loc[group.index[:-1], 'gap_after_m'] = gaps
        positive = gaps > 0
        if 'max_slope_m_per_m' in controls:
            steep = np.zeros(len(gaps), dtype=bool)
            steep[positive] = abs(np.diff(z)[positive]/gaps[positive]) > controls['max_slope_m_per_m']
            audit.loc[group.index[np.r_[steep, False] | np.r_[False, steep]], 'steep_slope'] = True
        residual = np.full(len(x), np.nan)
        if len(x) >= 3:
            valid = (np.diff(x[:-1]) > 0) & (np.diff(x[1:]) > 0) & ((x[2:]-x[:-2]) <= 2*max_gap_m)
            expected = np.full(len(x)-2, np.nan)
            expected[valid] = z[:-2][valid] + ((x[1:-1][valid]-x[:-2][valid])/
                                              (x[2:][valid]-x[:-2][valid]))*(z[2:][valid]-z[:-2][valid])
            residual[1:-1] = z[1:-1]-expected
        audit.loc[group.index, 'spike_residual_m'] = residual
        finite = residual[np.isfinite(residual)]
        if len(finite) >= 5:
            center = float(np.median(finite))
            scale = float(1.4826*np.median(abs(finite-center)))
            spike = abs(residual-center) > max(controls['spike_min_m'], controls['robust_z_limit']*scale)
            audit.loc[group.index, 'spike'] = spike
        summaries.append({'xs_id': xs_id, 'points': len(group), 'finite_points': int(np.isfinite(z).sum()),
                          'gap_count': int((gaps > max_gap_m).sum()),
                          'max_gap_m': float(gaps.max()) if len(gaps) else None})
    flags = ['missing_or_nonfinite', 'duplicate_station', 'outside_elevation_limits', 'steep_slope', 'spike']
    audit['flagged'] = audit[flags].any(axis=1)
    audit['flag_reasons'] = ''
    for flag in flags:
        audit.loc[audit[flag], 'flag_reasons'] += flag+';'
    audit['flag_reasons'] = audit.flag_reasons.str.rstrip(';')
    audit['manual_exclusion_reason'] = ''
    for point in options.get('excluded_points', []):
        if not str(point.get('reason', '')).strip():
            raise CalibrationError('Manual survey exclusions require a reason.')
        selected = (audit.xs_id == str(point['xs_id'])) & np.isclose(audit.u_m, float(point['u_m']), rtol=0, atol=1e-8)
        if not selected.any():
            raise CalibrationError(f'Manual exclusion does not match a survey point: {point["xs_id"]}, {point["u_m"]}.')
        audit.loc[selected, 'manual_exclusion_reason'] = point['reason']
    # Duplicate flags need an aggregation decision, not automatic removal of both rows.
    auto_flags = audit[['outside_elevation_limits', 'steep_slope', 'spike']].any(axis=1)
    audit['excluded'] = audit.manual_exclusion_reason.ne('') | (auto_flags & options.get('exclude_flagged', False))
    audit.loc[audit.excluded, 'used_z_m'] = np.nan
    profile = audit[['xs_id', 'u_m', 'used_z_m']].rename(columns={'used_z_m': 'z_m'})
    policy = options.get('duplicate_policy', 'error')
    if policy not in ('error', 'mean', 'median'):
        raise CalibrationError('duplicate_policy must be error, mean, or median.')
    if audit.duplicate_station.any():
        if policy == 'error':
            if not allow_unresolved_duplicates:
                raise CalibrationError('Duplicate lateral stations: review QA/QC and set an explicit mean/median duplicate policy.')
        else:
            # Missing/excluded duplicates keep the shared station masked, never resurrect it.
            profile = profile.groupby(['xs_id', 'u_m'], as_index=False).agg(
                z_m=('z_m', lambda values: getattr(values, policy)() if values.notna().all() else np.nan))
    if not allow_unresolved_duplicates or policy != 'error':
        profile = normalize_profile(profile)
    summary = {'input_points': len(audit), 'flagged_points': int(audit.flagged.sum()),
               'excluded_points': int(audit.excluded.sum()), 'duplicate_policy': policy,
               'retained_flagged_points': int((audit.flagged & ~audit.excluded & audit.used_z_m.notna()).sum()),
               'datum_correction_m': controls['datum_correction_m'],
               'datum_correction_evidence': options.get('datum_correction_evidence'),
               'flag_counts': {k: int(audit[k].sum()) for k in flags},
               'warning': 'Flags are review candidates. Coherent real bed change can resemble a datum shift.'}
    summary['mapping'] = frame.attrs.get('mapping')
    return SurveyReview(profile, audit, pd.DataFrame(summaries), summary)


def datum_shift_review(profiles, *, threshold_m=0.5, stable_controls=None):
    """Screen matched before/after survey differences; do not infer a correction.

    Without independent stable controls a coherent shift is equally consistent
    with real deposition/erosion. Report that ambiguity explicitly.
    """
    if not np.isfinite(threshold_m) or threshold_m <= 0:
        raise CalibrationError('Datum screening threshold must be positive and finite.')
    if stable_controls:
        values = []
        seen = set()
        for point in stable_controls:
            identity = str(point['xs_id']), float(point['u_m'])
            if identity in seen:
                continue
            seen.add(identity)
            group = profiles[profiles.xs_id == identity[0]].sort_values('u_m')
            u, change = group.u_m.to_numpy(), group.observed_change_m.to_numpy()
            index = int(np.searchsorted(u, identity[1]))
            value = np.nan
            if index < len(u) and np.isclose(u[index], identity[1], rtol=0, atol=1e-8):
                if group.accepted_point.iloc[index]:
                    value = change[index]
            elif 0 < index < len(u) and group.accepted_interval_to_next.iloc[index-1]:
                value = np.interp(identity[1], u[index-1:index+1], change[index-1:index+1])
            if np.isfinite(value):
                values.append(value)
        values = np.asarray(values)
        basis = 'user-designated stable control points'
    else:
        # One median per XS prevents densely sampled sections dominating the screen.
        values = profiles[profiles.accepted_point].groupby('xs_id').observed_change_m.median().to_numpy()
        basis = 'section medians; real spatially coherent bed change is an alternative explanation'
    center = float(np.median(values)) if len(values) else None
    scatter = float(1.4826*np.median(abs(values-center))) if len(values) else None
    return {'basis': basis, 'samples': len(values), 'median_shift_m': center, 'robust_scatter_m': scatter,
            'uniform_shift_candidate': bool(len(values) >= 3 and abs(center) >= threshold_m and
                                             scatter <= max(0.05, abs(center)*0.15)),
            'action': 'Check independent benchmarks, vertical units/datum, acquisition dates, and real channel change. No correction is applied.'}
