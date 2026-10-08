"""Time-series overlay, residuals, and observed transport-function preview."""
from __future__ import annotations

import matplotlib.dates as mdates
import numpy as np
from matplotlib.ticker import EngFormatter, MaxNLocator

from plotting.styles import OBS_COLOR


def draw_time_series_calibration(fig, result, quantity, label, du, display, log, title,
                                 extrapolate=False, smear=False, manual_points=()):
    fig.clear()
    grid = fig.add_gridspec(2, 2, width_ratios=[2.5, 1], height_ratios=[2.3, 1])
    ax = fig.add_subplot(grid[0, 0])
    residual = fig.add_subplot(grid[1, 0], sharex=ax)
    rating = fig.add_subplot(grid[:, 1])
    unit = du.label(quantity)
    axis_label = label.removeprefix('Sediment ').capitalize()
    def values(data):
        y = np.asarray(du.convert(np.asarray(data, float), quantity), float)
        return np.where(y > 0, y, np.nan) if log else y
    series, samples = result.series, result.samples
    ax.plot(series.index, values(series['mod']), color='black', lw=1.2, label='HEC-RAS')
    if display in ('points', 'both'):
        ax.scatter(samples.index, values(samples.obs), color=OBS_COLOR, s=22, zorder=3, label='Measured sediment')
        residual.scatter(samples.index, du.convert(samples.residual.to_numpy(), quantity), color=OBS_COLOR,
                         s=15, label='Model − measured')
    if display in ('rating', 'both'):
        ax.plot(series.index, values(series.reference), color='#0072b2', lw=1.3, label='Rating-derived reference')
        residual.plot(series.index, du.convert(series.residual.to_numpy(), quantity), color='#0072b2', lw=1,
                      label='Model − rating reference')
    if log:
        ax.set_yscale('log')
    ax.set_ylabel(f'{axis_label} ({unit})')
    ax.legend(fontsize=8); ax.grid(True, which='both', alpha=.25)
    residual.axhline(0, color='#777777', lw=.8)
    residual.set_ylabel(f'Residual\n({unit})'); residual.grid(True, alpha=.25)
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6, interval_multiples=False)
    residual.xaxis.set_major_locator(locator)
    residual.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    residual.set_xlabel('Model date / time')
    ax.tick_params(axis='x', labelbottom=False)
    q = samples.Q.to_numpy(float)
    y = samples.obs.to_numpy(float)
    valid = np.isfinite(q) & (q > 0) & np.isfinite(y) & (y >= 0)
    rating.scatter(du.convert(q[valid], 'discharge'), values(y[valid]), color=OBS_COLOR, s=18)
    if not valid.any() and not len(manual_points):
        mq = series.Q.to_numpy(float)
        my = series['mod'].to_numpy(float)
        usable = np.isfinite(mq) & (mq > 0) & np.isfinite(my) & (my >= 0)
        if usable.any():
            xx = np.asarray(du.convert(mq[usable], 'discharge'))
            yy = np.asarray(du.convert(my[usable], quantity))
            rating.set_xlim(max(float(xx.min())*.5, .001), float(xx.max())*1.5)
            rating.set_ylim(max(float(yy.min())*.5, .001) if log else 0, max(float(yy.max())*1.5, 1))
    if len(manual_points):
        points = np.asarray(manual_points, float)
        rating.scatter(du.convert(points[:, 0], 'discharge'), values(points[:, 1]), color='#009e73', marker='*',
                       s=65, zorder=4, label='Drawn controls')
        rating.legend(fontsize=7)
    if result.fit is not None:
        fit = result.fit
        q_grid = np.geomspace(fit.q_min, fit.q_max, 250)
        rating.plot(du.convert(q_grid, 'discharge'), values(fit.predict(q_grid, extrapolate, smear)),
                    color='#0072b2', lw=1.3)
    else:
        rating.text(.5, .95, 'No rating fit' if display != 'points' else 'Same-record measurements',
                    ha='center', va='top', transform=rating.transAxes, fontsize=8)
    if log:
        rating.set_yscale('log')
    rating.set_title('Observed rating curve', fontsize=9)
    rating.set_xlabel(f'Observed discharge ({du.label("discharge")})')
    rating.xaxis.set_major_locator(MaxNLocator(nbins=3, min_n_ticks=2))
    rating.xaxis.set_major_formatter(EngFormatter(places=0, sep=''))
    rating.set_ylabel(f'{axis_label} ({unit})')
    rating.grid(True, which='both', alpha=.25)
    fig.suptitle(title, fontsize=11, x=.01, ha='left')
    fig.subplots_adjust(left=.09, right=.97, top=.89, bottom=.13, wspace=.4, hspace=.12)
