"""Shared GUI/headless figures, using physical chainage and supported segments."""
import copy
import numpy as np

from .display_units import (customary_column, longitudinal_x, longitudinal_axis,
                            uses_river_miles, FT_PER_M, M_PER_MILE)


def _plot_frame(frame):
    out = frame.copy()
    for column in out:
        # Keep canonical chainage for the explicit fallback distance axis.
        if not column.endswith('chainage_m'):
            _, scale = customary_column(column)
            if scale != 1:
                out[column] = out[column]*scale
    return out


def _plot_result(result):
    out = copy.copy(result)
    out.sections, out.profiles, out.intervals = (_plot_frame(getattr(result, name))
                                               for name in ('sections', 'profiles', 'intervals'))
    out.metrics = {key: value*customary_column(key)[1] if value is not None and isinstance(value, (int, float))
                   else value for key, value in result.metrics.items()}
    return out


def segment_lines(axis, table, columns):
    colors = ('#2166ac', '#b35806', '#555555', '#762a83')
    for color, (column, label, style) in zip(colors, columns):
        for i, (_, group) in enumerate(table.groupby('segment_id', sort=False)):
            axis.plot(longitudinal_x(group), group[column], style, color=color,
                      label=label if i == 0 else None)
    longitudinal_axis(axis, table)


def draw_comparison(figure, result, provenance):
    result = _plot_result(result)
    figure.clear()
    upper, lower = figure.subplots(2, 1)
    columns = [('model_cumulative_m3', 'Model', '-'), ('observed_cumulative_m3', 'Observed', '--')]
    if 'native_cumulative_m3' in result.sections:
        columns.append(('native_cumulative_m3', 'Native RAS audit', ':'))
    segment_lines(upper, result.sections, columns)
    upper.set_ylabel('Cumulative bed volume change (yd³)\nNode sum per supported segment')
    upper.set_title(f'{provenance["survey_before"]} → {provenance["survey_after"]}')
    upper.text(.01, .02, 'Node sum includes the first half-reach contribution; resets at gaps.',
               transform=upper.transAxes, fontsize=8, bbox=dict(facecolor='white', alpha=.8, edgecolor='none'))
    segment_lines(lower, result.sections, [('model_mean_change_m', 'Model', '-'),
                                          ('observed_mean_change_m', 'Observed', '--')])
    lower.set_ylabel('Mean bed elevation change (ft)')
    threshold = result.metrics['change_detection_threshold_m']
    lower.axhspan(-threshold, threshold, color='grey', alpha=.15, label='Detection threshold')
    for axis in (upper, lower):
        axis.axhline(0, color='grey', linewidth=.7)
        axis.legend()
        axis.grid(alpha=.2)


def draw_diagnostics(figure, result, quantity='change'):
    result = _plot_result(result)
    figure.clear()
    axes = figure.subplots(3, 2)
    table, metrics = result.sections, result.metrics
    segment_lines(axes[0, 0], table, [('model_mean_change_m', 'Model', '-'),
                                    ('observed_mean_change_m', 'Observed', '--')])
    axes[0, 0].set_ylabel('Bed change (ft)')
    for label, color in [('erosion', 'royalblue'), ('deposition', 'sienna'), ('within_threshold', 'grey')]:
        group = table[table.observed_zone == label]
        axes[0, 0].scatter(longitudinal_x(group), group.observed_mean_change_m, c=color, label=f'Observed {label}')
    axes[0, 1].scatter(table.observed_mean_change_m, table.model_mean_change_m,
                       c=np.where(table.zone_agrees, 'seagreen', 'firebrick'), s=25)
    limits = np.r_[table.observed_mean_change_m, table.model_mean_change_m]
    lo, hi = float(limits.min()), float(limits.max())
    padding = max((hi-lo)*.05, .05)
    axes[0, 1].plot([lo-padding, hi+padding], [lo-padding, hi+padding], ':', color='grey')
    axes[0, 1].set(xlabel='Observed change (ft)', ylabel='Model change (ft)',
                   title='Green: same zone; red: different zone')
    lengths = table.control_length_m.to_numpy()*table.effective_width_m.to_numpy()
    standardized = table.copy()
    for prefix in ('model', 'observed'):
        values = table[f'{prefix}_mean_change_m'].to_numpy()
        center = np.average(values, weights=lengths)
        spread = np.sqrt(np.average((values-center)**2, weights=lengths))
        standardized[f'{prefix}_standardized'] = (values-center)/spread if spread > 1e-12 else np.nan
    segment_lines(axes[1, 0], standardized, [('model_standardized', 'Model', '-'),
                                           ('observed_standardized', 'Observed', '--')])
    axes[1, 0].set_ylabel('Standardized change (dimensionless)')
    corr = metrics['change_shape_correlation']
    axes[1, 0].set_title('Spatial pattern: undefined for constant series' if corr is None else f'Spatial pattern correlation: {corr:.3f}')
    segment_lines(axes[1, 1], table, [('model_baseline_elev_m', 'Model baseline', ':'),
                                    ('model_target_elev_m', 'Model target', '-'),
                                    ('observed_baseline_elev_m', 'Observed baseline', '-.'),
                                    ('observed_target_elev_m', 'Observed target', '--')])
    axes[1, 1].set_ylabel('Mean bed elevation (ft, common datum)')
    for axis, derivative, units, label in [(axes[2, 0], 'slope', 'm_per_km', 'Slope (ft / downstream mi)'),
                                           (axes[2, 1], 'concavity', 'm_per_km2', 'Concavity (ft / downstream mi²)')]:
        segment_lines(axis, table, [(f'model_{quantity}_{derivative}_{units}', 'Model', '-'),
                                   (f'observed_{quantity}_{derivative}_{units}', 'Observed', '--')])
        axis.set_ylabel(label)
        axis.set_title(quantity.replace('_', ' ').capitalize()+'; unsmoothed')
    for axis in axes.flat:
        axis.grid(alpha=.2)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=7)
    figure.suptitle('Magnitude, erosion/deposition zones, and bed shape on matched support')


def draw_section(figure, result, xs_id):
    result = _plot_result(result)
    figure.clear()
    upper, lower = figure.subplots(2, 1, sharex=True)
    data = result.profiles[result.profiles.xs_id == xs_id].copy()
    # One artist per series, with NaN separators rather than thousands of lines.
    accepted = np.flatnonzero(data.accepted_interval_to_next.to_numpy())
    line_u = np.full(len(accepted)*3, np.nan)
    line_u[0::3], line_u[1::3] = data.u_m.to_numpy()[accepted], data.u_m.to_numpy()[accepted+1]
    def supported_line(axis, column, style):
        values = np.full(len(accepted)*3, np.nan)
        values[0::3], values[1::3] = data[column].to_numpy()[accepted], data[column].to_numpy()[accepted+1]
        axis.plot(line_u, values, style, linewidth=1)
    for column, label, style in [('model_before_z_m', 'Model baseline', ':'),
                                 ('model_after_z_m', 'Model target', '-'),
                                 ('observed_before_z_m', 'Survey baseline', '-.'),
                                 ('observed_after_z_m', 'Survey target', '--')]:
        upper.scatter(data.u_m, data[column], s=8, label=label)
        supported_line(upper, column, style)
    for column, label in [('model_change_m', 'Model'), ('observed_change_m', 'Observed')]:
        lower.scatter(data.u_m[data.accepted_point], data.loc[data.accepted_point, column], s=10, label=label)
        supported_line(lower, column, '-')
    upper.set(title=f'XS {xs_id}: matched lateral support', ylabel='Bed elevation (ft)')
    lower.set(xlabel='Lateral station (ft)', ylabel='Bed change (ft)')
    lower.axhline(0, color='grey', linewidth=.7)
    for axis in (upper, lower):
        axis.legend(fontsize=8)
        axis.grid(alpha=.2)


def draw_time_series(figure, series):
    figure.clear()
    axes = figure.subplots(2, 1)
    sections = series.comparisons[0][0].sections
    xs = sections.xs_id.tolist()
    locations = longitudinal_x(sections)
    values = [np.array([r.sections[f'{source}_mean_change_m_per_year'].to_numpy()
                        for r, _ in series.comparisons])*FT_PER_M for source in ('model', 'observed')]
    limit = max(max(abs(v).max() for v in values), 1e-8)
    ticks = np.unique(np.linspace(0, len(xs)-1, min(12, len(xs))).astype(int))
    for axis, data, source in zip(axes, values, ('Model', 'Observed')):
        artist = axis.imshow(data, aspect='auto', cmap='RdBu_r', vmin=-limit, vmax=limit, interpolation='nearest')
        axis.set_xticks(ticks, [f'{locations[i]:g}' for i in ticks])
        labels = [f'{p["survey_before"]} → {p["survey_after"]}' for _, p in series.comparisons]
        axis.set_yticks(np.arange(len(labels)), labels)
        axis.set(xlabel='River mile (discrete model XS samples; downstream →)' if uses_river_miles(sections) else 'Downstream distance (mi; discrete XS samples)', title=source)
        figure.colorbar(artist, ax=axis, label='Bed change rate (ft/year); red deposition')
        boundaries = series.comparisons[0][0].sections.segment_id.diff().fillna(0).ne(0)
        for index in np.flatnonzero(boundaries):
            axis.axvline(index-.5, color='black', linewidth=2)
    figure.suptitle('Consecutive survey intervals on fixed support; rates use each source’s dates')


def draw_calculation_audit(figure, result, xs_id, reference=None, cumulative='node'):
    """Calculation stages, with consistent source colors and explicit prefix semantics."""
    result = _plot_result(result)
    figure.clear()
    axes = figure.subplots(2, 2)
    table = result.sections
    suffix = 'cumulative_m3' if cumulative == 'node' else 'interval_prefix_m3'
    columns = [(f'model_{suffix}', 'Model', '-'), (f'observed_{suffix}', 'Observed', '--')]
    segment_lines(axes[0, 0], table, columns)
    if reference is not None:
        reference = _plot_result(reference)
        for source, color in [('model', '#2166ac'), ('observed', '#b35806')]:
            for i, (_, group) in enumerate(reference.sections.groupby('segment_id', sort=False)):
                axes[0, 0].plot(longitudinal_x(group), group[f'{source}_{suffix}'], ':',
                    color=color, alpha=.45, label=f'{source.capitalize()} reference' if i == 0 else None)
        longitudinal_axis(axes[0, 0], reference.sections)
    axes[0, 0].set(ylabel='Signed cumulative change (yd³)',
        title='Node control-volume sum' if cumulative == 'node' else 'Completed-reach prefix (starts at zero)')
    interval = result.intervals
    x = interval.mid_river_mile.to_numpy() if uses_river_miles(table) else interval.mid_chainage_m.to_numpy()/M_PER_MILE
    longitudinal_axis(axes[0, 1], table, midpoint=True)
    # Thin paired markers retain readability when reach lengths are very unequal.
    for source, marker, color in [('model', 'o', '#2166ac'), ('observed', 's', '#b35806')]:
        axes[0, 1].vlines(x, 0, interval[f'{source}_volume_change_m3'], color=color, alpha=.35)
        axes[0, 1].scatter(x, interval[f'{source}_volume_change_m3'], marker=marker, color=color, s=20, label=source.capitalize())
    axes[0, 1].set(ylabel='Reach volume change (yd³)',
                   title='Endpoint areas × verified reach length')
    data = result.profiles[result.profiles.xs_id == xs_id]
    accepted = np.flatnonzero(data.accepted_interval_to_next.to_numpy())
    u = np.full(len(accepted)*3, np.nan)
    u[::3], u[1::3] = data.u_m.to_numpy()[accepted], data.u_m.to_numpy()[accepted+1]
    for source, color, style in [('model', '#2166ac', '-'), ('observed', '#b35806', '--')]:
        z = np.full(len(u), np.nan)
        z[::3], z[1::3] = data[f'{source}_change_m'].to_numpy()[accepted], data[f'{source}_change_m'].to_numpy()[accepted+1]
        axes[1, 0].plot(u, z, style, color=color, label=source.capitalize())
        axes[1, 0].fill_between(u, 0, z, color=color, alpha=.16)
    threshold = result.metrics['change_detection_threshold_m']
    axes[1, 0].axhspan(-threshold, threshold, color='grey', alpha=.12, label='Classification threshold')
    axes[1, 0].set(xlabel='Lateral station (ft)', ylabel='Target − baseline (ft)',
                   title=f'XS {xs_id}: shaded integral gives ΔA (ft²)')
    for source, color in [('model', '#2166ac'), ('observed', '#b35806')]:
        for i, (_, group) in enumerate(table.groupby('segment_id', sort=False)):
            axes[1, 1].plot(longitudinal_x(group), group[f'{source}_deposition_cumulative_m3'], '-', color=color,
                            label=f'{source.capitalize()} deposition' if i == 0 else None)
            axes[1, 1].plot(longitudinal_x(group), -group[f'{source}_erosion_cumulative_m3'], '--', color=color,
                            label=f'{source.capitalize()} erosion (negative)' if i == 0 else None)
    longitudinal_axis(axes[1, 1], table)
    axes[1, 1].set(ylabel='Node cumulative components (yd³)',
                   title='Opposing changes hidden by net averages')
    for axis in axes.flat:
        axis.axhline(0, color='grey', linewidth=.7)
        axis.grid(alpha=.2)
        axis.legend(fontsize=7)
    figure.suptitle('Calculation audit • ' + result.calculation_options['longitudinal_method'].replace('_', ' '))


def draw_variability(figure, result):
    result = _plot_result(result)
    figure.clear()
    axes = figure.subplots(3, 1, sharex=True)
    for source, color in [('model', '#2166ac'), ('observed', '#b35806')]:
        for i, (_, group) in enumerate(result.sections.groupby('segment_id', sort=False)):
            label = source.capitalize() if i == 0 else None
            axes[0].plot(longitudinal_x(group), group[f'{source}_lateral_std_m'], color=color, label=label)
            axes[1].plot(longitudinal_x(group), group[f'{source}_cancellation_fraction'], color=color, label=label)
            axes[2].plot(longitudinal_x(group), group[f'{source}_deposition_width_fraction'], '-', color=color,
                         label=f'{source.capitalize()} deposition' if i == 0 else None)
            axes[2].plot(longitudinal_x(group), group[f'{source}_erosion_width_fraction'], '--', color=color,
                         label=f'{source.capitalize()} erosion' if i == 0 else None)
    axes[0].set(ylabel='Lateral change std (ft)', title='Within-section heterogeneity on accepted support')
    axes[1].set(ylabel='Cancellation fraction', ylim=(-.03, 1.03), title='1 = opposing changes cancel; undefined if no change')
    longitudinal_axis(axes[2], result.sections)
    axes[2].set(ylabel='Accepted width fraction', ylim=(-.03, 1.03),
                title='Erosion/deposition above threshold; remainder within threshold')
    for axis in axes:
        axis.legend(fontsize=8)
        axis.grid(alpha=.2)
    figure.suptitle('Two-date change variability; sampled transects, not continuous 2-D bed or transport')


def draw_sensitivity(figure, exploration):
    figure.clear()
    axes = figure.subplots(2, 1, sharex=True)
    table = _plot_frame(exploration.summary[exploration.summary.status == 'ok'])
    x = np.arange(len(table))
    axes[0].plot(x, table.model_total_m3, 'o-', color='#2166ac', label='Model net')
    axes[0].plot(x, table.observed_total_m3, 's--', color='#b35806', label='Observed net')
    axes[0].plot(x, table.observed_gross_turnover_m3, '^:', color='#762a83', label='Observed gross turnover')
    axes[0].set(ylabel='Bed change (yd³)', title='Net totals can hide gross erosion and deposition')
    changed = table.support_changed.fillna(False).to_numpy(bool)
    axes[1].scatter(x, table.total_bias_m3, c=np.where(changed, '#d95f02', '#333333'), s=30)
    has_error = table.observed_volume_sigma_m3.notna().to_numpy()
    if has_error.any():
        axes[1].errorbar(x[has_error], table.total_bias_m3.to_numpy()[has_error],
            yerr=1.96*table.observed_volume_sigma_m3.to_numpy()[has_error], fmt='none', capsize=4,
            color='#555555', label='Conditional 95% survey error; model exact')
    axes[1].scatter([], [], color='#d95f02', label='Orange: different footprint')
    axes[1].set(ylabel='Model − observed bias (yd³)', xlabel='Retained calculation assumptions',
                title='Error bars exclude model / unresolved morphology / registration error')
    axes[1].set_xticks(x, table.name, rotation=20, ha='right')
    for axis in axes:
        axis.axhline(0, color='grey', linewidth=.7)
        axis.legend(fontsize=8)
        axis.grid(alpha=.2)
    unavailable = int((exploration.summary.status != 'ok').sum())
    figure.suptitle('Assumption sensitivity' + (f' • {unavailable} unavailable scenarios in ledger' if unavailable else ''))
