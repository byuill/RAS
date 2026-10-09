"""Shared GUI/headless figures, using physical chainage and supported segments."""
import numpy as np


def segment_lines(axis, table, columns):
    for column, label, style in columns:
        for i, (_, group) in enumerate(table.groupby('segment_id', sort=False)):
            axis.plot(group.chainage_m/1000, group[column], style, label=label if i == 0 else None)
    axis.set_xlabel('Downstream chainage (km)')


def draw_comparison(figure, result, provenance):
    figure.clear()
    upper, lower = figure.subplots(2, 1)
    columns = [('model_cumulative_m3', 'Model', '-'), ('observed_cumulative_m3', 'Observed', '--')]
    if 'native_cumulative_m3' in result.sections:
        columns.append(('native_cumulative_m3', 'Native RAS audit', ':'))
    segment_lines(upper, result.sections, columns)
    upper.set_ylabel('Cumulative bed change per segment (m³)')
    upper.set_title(f'{provenance["survey_before"]} → {provenance["survey_after"]}')
    segment_lines(lower, result.sections, [('model_mean_change_m', 'Model', '-'),
                                          ('observed_mean_change_m', 'Observed', '--')])
    lower.set_ylabel('Mean bed elevation change (m)')
    threshold = result.metrics['change_detection_threshold_m']
    lower.axhspan(-threshold, threshold, color='grey', alpha=.15, label='Detection threshold')
    for axis in (upper, lower):
        axis.axhline(0, color='grey', linewidth=.7)
        axis.legend()
        axis.grid(alpha=.2)


def draw_diagnostics(figure, result, quantity='change'):
    figure.clear()
    axes = figure.subplots(3, 2)
    table, metrics = result.sections, result.metrics
    segment_lines(axes[0, 0], table, [('model_mean_change_m', 'Model', '-'),
                                    ('observed_mean_change_m', 'Observed', '--')])
    axes[0, 0].set_ylabel('Bed change (m)')
    for label, color in [('erosion', 'royalblue'), ('deposition', 'sienna'), ('within_threshold', 'grey')]:
        group = table[table.observed_zone == label]
        axes[0, 0].scatter(group.chainage_m/1000, group.observed_mean_change_m, c=color, label=f'Observed {label}')
    axes[0, 1].scatter(table.observed_mean_change_m, table.model_mean_change_m,
                       c=np.where(table.zone_agrees, 'seagreen', 'firebrick'), s=25)
    limits = np.r_[table.observed_mean_change_m, table.model_mean_change_m]
    lo, hi = float(limits.min()), float(limits.max())
    padding = max((hi-lo)*.05, .05)
    axes[0, 1].plot([lo-padding, hi+padding], [lo-padding, hi+padding], ':', color='grey')
    axes[0, 1].set(xlabel='Observed change (m)', ylabel='Model change (m)',
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
    axes[1, 1].set_ylabel('Mean bed elevation (m, common datum)')
    for axis, derivative, units, label in [(axes[2, 0], 'slope', 'm_per_km', 'Slope (m/km)'),
                                           (axes[2, 1], 'concavity', 'm_per_km2', 'Concavity (m/km²)')]:
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
    upper.set(title=f'XS {xs_id}: matched lateral support', ylabel='Bed elevation (m)')
    lower.set(xlabel='Lateral station (m)', ylabel='Bed change (m)')
    lower.axhline(0, color='grey', linewidth=.7)
    for axis in (upper, lower):
        axis.legend(fontsize=8)
        axis.grid(alpha=.2)


def draw_time_series(figure, series):
    figure.clear()
    axes = figure.subplots(2, 1)
    xs = series.comparisons[0][0].sections.xs_id.tolist()
    values = [np.array([r.sections[f'{source}_mean_change_m_per_year'].to_numpy()
                        for r, _ in series.comparisons]) for source in ('model', 'observed')]
    limit = max(max(abs(v).max() for v in values), 1e-8)
    ticks = np.unique(np.linspace(0, len(xs)-1, min(12, len(xs))).astype(int))
    for axis, data, source in zip(axes, values, ('Model', 'Observed')):
        artist = axis.imshow(data, aspect='auto', cmap='RdBu_r', vmin=-limit, vmax=limit, interpolation='nearest')
        axis.set_xticks(ticks, [xs[i] for i in ticks])
        labels = [f'{p["survey_before"]} → {p["survey_after"]}' for _, p in series.comparisons]
        axis.set_yticks(np.arange(len(labels)), labels)
        axis.set(xlabel='Cross-section IDs in downstream order (discrete samples)', title=source)
        figure.colorbar(artist, ax=axis, label='Bed change rate (m/year); red deposition')
        boundaries = series.comparisons[0][0].sections.segment_id.diff().fillna(0).ne(0)
        for index in np.flatnonzero(boundaries):
            axis.axvline(index-.5, color='black', linewidth=2)
    figure.suptitle('Consecutive survey intervals on fixed support; rates use each source’s dates')
