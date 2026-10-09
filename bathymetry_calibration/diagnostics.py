"""Magnitude and spatial-pattern skill on matched, explicitly segmented support."""
import numpy as np
import pandas as pd


def weighted_correlation(model, observed, weights):
    model, observed, weights = map(np.asarray, (model, observed, weights))
    ok = np.isfinite(model) & np.isfinite(observed) & (weights > 0)
    if ok.sum() < 2:
        return None
    m, o, w = model[ok], observed[ok], weights[ok]
    m = m - np.average(m, weights=w)
    o = o - np.average(o, weights=w)
    denominator = np.sqrt(np.sum(w*m*m) * np.sum(w*o*o))
    if denominator <= np.finfo(float).eps * w.sum():
        return None
    return float(np.clip(np.sum(w*m*o)/denominator, -1, 1))


def classify(values, threshold):
    values = np.asarray(values)
    return np.where(values > threshold, 'deposition',
                    np.where(values < -threshold, 'erosion', 'within_threshold'))


def _rmse(model, observed, weights):
    ok = np.isfinite(model) & np.isfinite(observed) & (weights > 0)
    return float(np.sqrt(np.average((model[ok]-observed[ok])**2, weights=weights[ok]))) if ok.any() else None


def _derivatives(x, y):
    if len(x) < 2:
        return np.full(len(x), np.nan), np.full(len(x), np.nan)
    slope = np.gradient(y, x, edge_order=2 if len(x) >= 3 else 1)
    curvature = np.gradient(slope, x, edge_order=2) if len(x) >= 3 else np.full(len(x), np.nan)
    return slope, curvature


def add_diagnostics(comparison, *, change_threshold_m=0.05, slope_threshold_m_per_km=0.01,
                    concavity_threshold_m_per_km2=0.01):
    """Thresholds classify patterns only; they never alter signed volume accounting.

    Change/shape statistics use matched sampled footprint (width * control length).
    Zone statistics use control lengths so wide sections do not dominate location
    agreement. Derivatives use downstream physical chainage in km within each
    supported segment, without smoothing or connecting excluded sections.
    """
    from .core import CalibrationError
    thresholds = [change_threshold_m, slope_threshold_m_per_km, concavity_threshold_m_per_km2]
    if not np.isfinite(thresholds).all() or min(thresholds) < 0:
        raise CalibrationError('Pattern detection thresholds must be finite and nonnegative.')
    table, metrics = comparison.sections, comparison.metrics
    model = table.model_area_change_m2.to_numpy()/table.effective_width_m.to_numpy()
    observed = table.observed_area_change_m2.to_numpy()/table.effective_width_m.to_numpy()
    lengths = table.control_length_m.to_numpy()
    weights = lengths * table.effective_width_m.to_numpy()
    table['model_mean_change_m'], table['observed_mean_change_m'] = model, observed
    table['mean_change_residual_m'] = model-observed
    table['model_zone'], table['observed_zone'] = classify(model, change_threshold_m), classify(observed, change_threshold_m)
    table['zone_agrees'] = table.model_zone == table.observed_zone
    m0, o0 = model-np.average(model, weights=weights), observed-np.average(observed, weights=weights)
    vm, vo = np.average(m0*m0, weights=weights), np.average(o0*o0, weights=weights)
    metrics.update({
        'mean_change_rmse_m': _rmse(model, observed, weights),
        'mean_change_bias_m': float(np.average(model-observed, weights=weights)),
        'demeaned_change_rmse_m': _rmse(m0, o0, weights),
        'change_shape_correlation': weighted_correlation(model, observed, weights),
        'change_rank_correlation': weighted_correlation(pd.Series(model).rank().to_numpy(),
                                                       pd.Series(observed).rank().to_numpy(), weights),
        'change_amplitude_ratio': float(np.sqrt(vm/vo)) if vo > 1e-15 else None,
        'change_regression_gain': float(np.average(m0*o0, weights=weights)/vo) if vo > 1e-15 else None,
        'zone_agreement_fraction': float(np.average(table.zone_agrees, weights=lengths)),
        'change_detection_threshold_m': float(change_threshold_m),
    })
    labels = ('erosion', 'within_threshold', 'deposition')
    comparison.confusion = pd.DataFrame([
        {'observed_zone': o, 'model_zone': m,
         'matched_length_m': float(lengths[(table.observed_zone == o) & (table.model_zone == m)].sum())}
        for o in labels for m in labels])
    for label in ('erosion', 'deposition'):
        m, o = (table.model_zone == label).to_numpy(), (table.observed_zone == label).to_numpy()
        union = lengths[m | o].sum()
        metrics[f'{label}_intersection_over_union'] = float(lengths[m & o].sum()/union) if union else None

    # Absolute bed shape and the spatial shape of bed change are separate diagnostics.
    for prefix in ('model', 'observed'):
        for quantity, column in [('change', f'{prefix}_mean_change_m'),
                                 ('baseline_bed', f'{prefix}_baseline_elev_m'),
                                 ('target_bed', f'{prefix}_target_elev_m')]:
            table[f'{prefix}_{quantity}_slope_m_per_km'] = np.nan
            table[f'{prefix}_{quantity}_concavity_m_per_km2'] = np.nan
            for _, group in table.groupby('segment_id', sort=False):
                slope, curve = _derivatives(group.chainage_m.to_numpy()/1000, group[column].to_numpy())
                table.loc[group.index, f'{prefix}_{quantity}_slope_m_per_km'] = slope
                table.loc[group.index, f'{prefix}_{quantity}_concavity_m_per_km2'] = curve
    for quantity in ('change', 'baseline_bed', 'target_bed'):
        for derivative, units, deadband in [('slope', 'm_per_km', slope_threshold_m_per_km),
                                           ('concavity', 'm_per_km2', concavity_threshold_m_per_km2)]:
            m = table[f'model_{quantity}_{derivative}_{units}'].to_numpy()
            o = table[f'observed_{quantity}_{derivative}_{units}'].to_numpy()
            ok = np.isfinite(m) & np.isfinite(o)
            metrics[f'{quantity}_{derivative}_rmse_{units}'] = _rmse(m, o, lengths)
            metrics[f'{quantity}_{derivative}_sign_agreement_fraction'] = (
                float(np.average(classify(m[ok], deadband) == classify(o[ok], deadband), weights=lengths[ok]))
                if ok.any() else None)
    zones = []
    for source in ('model', 'observed'):
        for segment, group in table.groupby('segment_id', sort=False):
            labels_in_group = group[f'{source}_zone']
            runs = (labels_in_group != labels_in_group.shift()).cumsum()
            for _, run in group.groupby(runs, sort=False):
                zones.append({'source': source, 'segment_id': int(segment),
                              'zone': run[f'{source}_zone'].iloc[0],
                              'upstream_xs': run.xs_id.iloc[0], 'downstream_xs': run.xs_id.iloc[-1],
                              'start_chainage_m': float(run.chainage_m.iloc[0]),
                              'end_chainage_m': float(run.chainage_m.iloc[-1]),
                              'control_length_m': float(run.control_length_m.sum()),
                              'volume_change_m3': float(run[f'{source}_local_control_volume_m3'].sum())})
    comparison.zones = pd.DataFrame(zones)
    return comparison
