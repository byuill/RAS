"""Trace signed-volume accounting and explore explicit, conditional assumptions.

All lateral moments integrate the piecewise-linear profile exactly, including
zero/threshold crossings. Interpolated knots are never independent observations.
Gross volumes describe sampled cross-section turnover between two dates, not
sediment transport, porosity-corrected solids, or activity between survey dates.
"""
from dataclasses import dataclass
import copy

import numpy as np
import pandas as pd

from .core import CalibrationError, compare_profiles


CALCULATION_GUIDE = """1. Convert verified source elevations/stations and reach lengths to metres.
2. At each XS, intersect all four profile extents with the manifest transect
   (or require the selected transect footprint). Keep every source knot, including
   NaN barriers. Interpolate linearly, with no extrapolation or gap bridging.
3. Accept a lateral interval only when every source has finite endpoints AND
   supported interior. Δz = target − baseline; deposition is positive.
   ΔA = Σ width × (Δz_left + Δz_right)/2 on accepted intervals [m²].
4. Default reach volume = L × (ΔA_upstream + ΔA_downstream)/2 [m³], using
   verified channel length L, not a substitute chainage or river-mile distance.
5. XS control length = half each neighboring accepted reach length. Local
   volume = ΔA × control length. The displayed node cumulative curve sums these
   local contributions; it starts with a half-reach contribution at the first XS.
   The boundary-prefix curve starts at zero and sums completed reach volumes at
   downstream XS. Their intermediate values differ; segment final totals agree.
   Upstream/downstream scenarios use the selected endpoint's full reach length
   instead of half-length weighting. Gross reach indicators are endpoint-section
   quadrature proxies, not a reconstruction of unsampled 2-D morphology.
6. Unsupported XS disconnect segments. Each cumulative curve resets per segment.
   Partial footprints remain partial; no missing bed is scaled up or filled.
7. Split linear changes at zero to integrate deposition and erosion magnitudes
   separately. Gross = deposition + erosion; net = deposition − erosion.
   Cancellation = 1 − |net|/gross (undefined when gross is zero). RMS and spatial
   standard deviation integrate Δz² exactly, weighted by lateral width × control
   length. Threshold fractions split intervals at ±threshold; thresholds classify
   change without deleting volume. Net zero can hide substantial opposing change.
8. Scenario changes are sensitivity experiments. They do not establish a better
   estimator or justify datum correction. Review support changes before comparing
   totals. A two-date turnover indicator cannot measure intervening dynamism.
"""


def linear_positive_area(a, b, width):
    """Integral of max(linear(a,b), 0), with exact sign-crossing triangles."""
    a, b, width = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float),
                                     np.asarray(width, float))
    out = np.array(width*(np.maximum(a, 0)+np.maximum(b, 0))/2, copy=True)
    cross = ((a < 0) & (b > 0)) | ((a > 0) & (b < 0))
    out[cross] = width[cross]*np.maximum(a[cross], b[cross])**2/(2*abs(b[cross]-a[cross]))
    return out


def linear_above_width(a, b, width, threshold):
    """Length on which linearly interpolated change strictly exceeds threshold."""
    a, b, width = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float),
                                     np.asarray(width, float))
    out = np.zeros(a.shape)
    out[(a > threshold) & (b > threshold)] = width[(a > threshold) & (b > threshold)]
    cross = (a > threshold) != (b > threshold)
    out[cross] = width[cross]*(np.maximum(a[cross], b[cross])-threshold)/abs(b[cross]-a[cross])
    return out


def add_calculation_audit(result):
    """Add an interval ledger and spatial variability without changing net volumes."""
    threshold = result.metrics['change_detection_threshold_m']
    parts = []
    section_statistics = []
    section_rows = result.sections.set_index('xs_id')
    for xs_id, group in result.profiles.groupby('xs_id', sort=False):
        group = group.sort_values('u_m')
        accepted = group.accepted_interval_to_next.to_numpy()[:-1]
        width = np.diff(group.u_m.to_numpy())
        row = section_rows.loc[xs_id]
        ledger = pd.DataFrame(dict(xs_id=xs_id, segment_id=int(row.segment_id),
            u_left_m=group.u_m.to_numpy()[:-1], u_right_m=group.u_m.to_numpy()[1:],
            width_m=width, accepted=accepted))
        ledger['reason'] = np.where(accepted, 'accepted', 'missing endpoint or unsupported interior (NaN/gap)')
        failures = [[] for _ in width]
        for name, column in [('model_before', 'model_before_z_m'), ('model_after', 'model_after_z_m'),
                             ('obs_before', 'observed_before_z_m'), ('obs_after', 'observed_after_z_m')]:
            endpoint_ok = np.isfinite(group[column].to_numpy()[:-1]) & np.isfinite(group[column].to_numpy()[1:])
            midpoint_ok = group[f'{name}_midpoint_supported_to_next'].to_numpy()[:-1]
            ledger[f'{name}_endpoint_supported'] = endpoint_ok
            ledger[f'{name}_interior_supported'] = midpoint_ok
            for i in np.flatnonzero(~endpoint_ok | ~midpoint_ok):
                failures[i].append(name)
        for i in np.flatnonzero(~accepted):
            ledger.loc[i, 'reason'] = 'unsupported: '+(', '.join(failures[i]) or 'additional time-series support epoch')
        for name in ('model_before_z_m', 'model_after_z_m', 'observed_before_z_m', 'observed_after_z_m'):
            ledger[name.replace('_m', '_left_m')] = group[name].to_numpy()[:-1]
            ledger[name.replace('_m', '_right_m')] = group[name].to_numpy()[1:]
        stats = {'xs_id': xs_id}
        for source in ('model', 'observed'):
            a, b = group[f'{source}_change_m'].to_numpy()[:-1], group[f'{source}_change_m'].to_numpy()[1:]
            ledger[f'{source}_change_left_m'], ledger[f'{source}_change_right_m'] = a, b
            # Unsupported intervals are visible with zero integrated contribution.
            a, b, w = a[accepted], b[accepted], width[accepted]
            values = {
                'signed_area_m2': w*(a+b)/2,
                'deposition_area_m2': linear_positive_area(a, b, w),
                'erosion_area_m2': linear_positive_area(-a, -b, w),
                'second_moment_m3': w*(a*a+a*b+b*b)/3,
                'deposition_width_m': linear_above_width(a, b, w, threshold),
                'erosion_width_m': linear_above_width(-a, -b, w, threshold),
            }
            for quantity, v in values.items():
                ledger[f'{source}_{quantity}'] = 0.
                ledger.loc[accepted, f'{source}_{quantity}'] = v
                stats[f'{source}_{quantity}'] = float(v.sum())
            mean = stats[f'{source}_signed_area_m2']/row.effective_width_m
            second = stats[f'{source}_second_moment_m3']/row.effective_width_m
            gross = stats[f'{source}_deposition_area_m2']+stats[f'{source}_erosion_area_m2']
            stats[f'{source}_lateral_std_m'] = float(np.sqrt(max(0, second-mean*mean)))
            stats[f'{source}_rms_change_m'] = float(np.sqrt(second))
            stats[f'{source}_cancellation_fraction'] = float(np.clip(1-abs(stats[f'{source}_signed_area_m2'])/gross, 0, 1)) if gross else np.nan
            for zone in ('deposition', 'erosion'):
                stats[f'{source}_{zone}_width_fraction'] = stats[f'{source}_{zone}_width_m']/row.effective_width_m
            stats[f'{source}_within_threshold_width_fraction'] = 1-stats[f'{source}_deposition_width_fraction']-stats[f'{source}_erosion_width_fraction']
        parts.append(ledger)
        section_statistics.append(stats)
    result.lateral_audit = pd.concat(parts, ignore_index=True)
    statistics = pd.DataFrame(section_statistics).set_index('xs_id')
    table = result.sections
    for column in statistics:
        table[column] = table.xs_id.map(statistics[column])
    lengths = table.control_length_m.to_numpy()
    footprint_area = float(np.dot(lengths, table.effective_width_m))
    result.metrics['sampled_bed_area_m2'] = footprint_area
    for source in ('model', 'observed'):
        for zone in ('deposition', 'erosion'):
            table[f'{source}_{zone}_control_volume_m3'] = table[f'{source}_{zone}_area_m2']*lengths
            table[f'{source}_{zone}_cumulative_m3'] = table.groupby('segment_id')[f'{source}_{zone}_control_volume_m3'].cumsum()
            result.metrics[f'{source}_gross_{zone}_m3'] = float(table[f'{source}_{zone}_control_volume_m3'].sum())
            result.metrics[f'{source}_{zone}_footprint_fraction'] = float(np.dot(lengths, table[f'{source}_{zone}_width_m'])/footprint_area)
        gross = result.metrics[f'{source}_gross_deposition_m3']+result.metrics[f'{source}_gross_erosion_m3']
        net = result.metrics[f'{source}_total_m3']
        mean = net/footprint_area
        second = float(np.dot(lengths, table[f'{source}_second_moment_m3'])/footprint_area)
        result.metrics.update({f'{source}_gross_turnover_m3': gross,
            f'{source}_cancellation_fraction': float(np.clip(1-abs(net)/gross, 0, 1)) if gross else None,
            f'{source}_spatial_std_change_m': float(np.sqrt(max(0, second-mean*mean))),
            f'{source}_rms_change_m': float(np.sqrt(second)),
            f'{source}_within_threshold_footprint_fraction': float(np.clip(1-result.metrics[f'{source}_deposition_footprint_fraction']-result.metrics[f'{source}_erosion_footprint_fraction'], 0, 1))})
        # Reach indicators retain both lateral and opposing upstream/downstream changes.
        intervals = result.intervals
        by_xs = table.set_index('xs_id')
        left, right = intervals.upstream_weight.to_numpy(), intervals.downstream_weight.to_numpy()
        length = intervals.length_m.to_numpy()
        def reach_integral(column):
            return length*(left*intervals.upstream_xs.map(by_xs[column]).to_numpy()+
                           right*intervals.downstream_xs.map(by_xs[column]).to_numpy())
        area = reach_integral('effective_width_m')
        for zone in ('deposition', 'erosion'):
            intervals[f'{source}_gross_{zone}_m3'] = reach_integral(f'{source}_{zone}_area_m2')
            intervals[f'{source}_{zone}_footprint_fraction'] = reach_integral(f'{source}_{zone}_width_m')/area
        gross_reach = intervals[f'{source}_gross_deposition_m3']+intervals[f'{source}_gross_erosion_m3']
        net_reach = intervals[f'{source}_volume_change_m3']
        intervals[f'{source}_gross_turnover_m3'] = gross_reach
        intervals[f'{source}_cancellation_fraction'] = np.clip(1-abs(net_reach)/gross_reach.replace(0, np.nan), 0, 1)
        mean_reach = net_reach/area
        intervals[f'{source}_spatial_std_change_m'] = np.sqrt(np.maximum(0,
            reach_integral(f'{source}_second_moment_m3')/area-mean_reach**2))
    if not np.isfinite(result.lateral_audit.filter(regex='signed_area|second_moment').to_numpy()).all():
        raise CalibrationError('Nonfinite integrated profile moments; check source scales and magnitudes.')
    return result


def change_error_sigma(before_sigma_m, after_sigma_m, temporal_correlation=0., spatial_correlation=1.):
    values = [before_sigma_m, after_sigma_m, temporal_correlation, spatial_correlation]
    if not np.isfinite(values).all() or min(values[:2]) < 0 or not -1 <= temporal_correlation <= 1 or not 0 <= spatial_correlation <= 1:
        raise CalibrationError('Uncertainty needs nonnegative finite sigmas, temporal correlation in [-1,1], and spatial correlation in [0,1].')
    return float(np.sqrt(max(0., before_sigma_m**2+after_sigma_m**2-2*temporal_correlation*before_sigma_m*after_sigma_m)))


def volume_uncertainty(result, *, before_sigma_m=0., after_sigma_m=0.,
                       temporal_correlation=0., spatial_correlation=1.):
    """Conditional Gaussian survey-volume error; model/reference treated as exact.

    Each survey error is coherent across a section's lateral footprint. Between
    sections, equicorrelation rho_s mixes independent XS and one coherent reach
    error. rho_t correlates before/after survey errors. This excludes unresolved
    morphology between XS, georegistration, model error, and systematic bias.
    """
    change_sigma = change_error_sigma(before_sigma_m, after_sigma_m, temporal_correlation, spatial_correlation)
    variance = change_sigma**2
    coefficients = (result.sections.effective_width_m*result.sections.control_length_m).to_numpy()
    sigma = float(np.sqrt(variance*((1-spatial_correlation)*np.dot(coefficients, coefficients)+spatial_correlation*coefficients.sum()**2)))
    margin = 1.96*sigma
    bias = result.metrics['total_bias_m3']
    declared = before_sigma_m > 0 or after_sigma_m > 0
    return dict(before_sigma_m=float(before_sigma_m), after_sigma_m=float(after_sigma_m),
        temporal_correlation=float(temporal_correlation), spatial_correlation=float(spatial_correlation),
        change_sigma_m=change_sigma, observed_volume_sigma_m3=sigma if declared else None,
        bias_lower_95_m3=float(bias-margin) if declared else None,
        bias_upper_95_m3=float(bias+margin) if declared else None,
        bias_exceeds_survey_error_95=bool(abs(bias) > margin) if declared and sigma > 0 else None,
        interpretation='Conditional Gaussian interval: section-coherent survey elevation error; '
        'model treated as exact. Includes specified temporal/spatial correlation; excludes model error, '
        'unresolved between-XS morphology, registration errors, and unknown systematic biases. '
        'Not a test of calibration validity. Zero/missing error does not establish significance.')


def support_signature(result):
    """Accepted lateral runs, independent of redundant integration-grid knots."""
    runs = []
    for xs, group in result.profiles.groupby('xs_id', sort=False):
        accepted = group.accepted_interval_to_next.to_numpy()[:-1]
        u = group.u_m.to_numpy()
        start = None
        for i, ok in enumerate(accepted):
            if ok and start is None:
                start = float(u[i])
            if start is not None and (not ok or i == len(accepted)-1):
                end = float(u[i+1] if ok else u[i])
                runs.append((xs, start, end))
                start = None
    return runs


@dataclass
class SensitivityComparison:
    reference: object
    scenarios: list
    summary: pd.DataFrame
    uncertainty: dict


def run_sensitivity(reference, scenarios, *, uncertainty=None, cancel=None):
    """Recompute reviewed original profiles; never overwrite a reference or source.

    A scenario is {name, overrides}; each override is a compare_profiles control,
    change_threshold_m, or observed_target_shift_m (hypothetical, not a datum fix).
    """
    if not reference.calculation_inputs:
        raise CalibrationError('Original reviewed profiles are required for sensitivity calculations.')
    if not isinstance(scenarios, list) or not scenarios or len(scenarios) > 100:
        raise CalibrationError('Provide between 1 and 100 sensitivity scenarios.')
    uncertainty = dict(uncertainty or {})
    output, rows, used_names = [], [], {'Reference'}
    baseline_uncertainty = volume_uncertainty(reference, **uncertainty)
    baseline = {**reference.metrics, **baseline_uncertainty}
    rows.append(dict(name='Reference', status='ok', support_changed=False,
                     model_delta_m3=0., observed_delta_m3=0., bias_delta_m3=0., **baseline))
    allowed = set(reference.calculation_options)-{'diagnostics', 'sample_spacing_m', 'longitudinal_limit_m'}
    allowed |= {'change_threshold_m', 'observed_target_shift_m'}
    for scenario in scenarios:
        if cancel is not None and cancel.is_set():
            raise CalibrationError('Sensitivity operation cancelled.')
        if not isinstance(scenario, dict) or set(scenario)-{'name', 'overrides'}:
            raise CalibrationError('Each scenario must contain a name and optional overrides object.')
        name, overrides = scenario.get('name'), scenario.get('overrides', {})
        if not isinstance(name, str) or not name.strip() or name in used_names:
            raise CalibrationError('Sensitivity scenarios require unique nonempty names (Reference is reserved).')
        used_names.add(name)
        if not isinstance(overrides, dict) or set(overrides)-allowed:
            raise CalibrationError(f'{name}: unknown or unsupported sensitivity controls.')
        controls = copy.deepcopy(reference.calculation_options)
        changes = dict(overrides)
        shift = changes.pop('observed_target_shift_m', 0.)
        if not isinstance(shift, (int, float)) or not np.isfinite(shift):
            raise CalibrationError('Hypothetical target-survey shift must be finite.')
        if 'change_threshold_m' in changes:
            controls['diagnostics']['change_threshold_m'] = changes.pop('change_threshold_m')
        controls.update(changes)
        inputs = dict(reference.calculation_inputs)
        inputs['observed_after'] = inputs['observed_after'].assign(z_m=inputs['observed_after'].z_m+shift)
        try:
            result = compare_profiles(**inputs, **controls)
        except CalibrationError as exc:
            rows.append(dict(name=name, status='unavailable', error=str(exc)))
            output.append((name, None, overrides))
            continue
        error = volume_uncertainty(result, **uncertainty)
        row = dict(name=name, status='ok', support_changed=support_signature(result) != support_signature(reference),
            model_delta_m3=result.metrics['model_total_m3']-reference.metrics['model_total_m3'],
            observed_delta_m3=result.metrics['observed_total_m3']-reference.metrics['observed_total_m3'],
            bias_delta_m3=result.metrics['total_bias_m3']-reference.metrics['total_bias_m3'],
            **result.metrics, **error)
        rows.append(row)
        output.append((name, result, dict(overrides)))
    return SensitivityComparison(reference, output, pd.DataFrame(rows), uncertainty)
