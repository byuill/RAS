"""Illustrate the engine's limb classifier on a fixed, synthetic annual flood pulse."""
import numpy as np
import pandas as pd
from matplotlib import dates as mdates
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
from scipy.interpolate import PchipInterpolator
from scipy.signal import savgol_filter

from .engine import classify_states


STATES = ((0., 'Normal', '#94a3b8'), (1., 'Rising', '#d97706'),
          (1.5, 'Crest', '#b43b52'), (2., 'Falling', '#16858a'),
          (3., 'Low water', '#7552ac'))


def synthetic_limb_delineation(p):
    """Return one illustrative year, with a preceding year for classifier history.

    The smooth, multi-pulse spring flood and autumn trough are conceptual flows,
    not a fit to observations. Threshold edits never rescale the example to force
    particular states to appear. One prior 365-day cycle covers the largest
    supported trailing window and lets flood memory pass through the fall reset.
    """
    p.validate()
    days = np.array([0, 20, 35, 50, 65, 80, 95, 110, 125, 140, 155, 170,
                     185, 205, 225, 245, 260, 275, 290, 305, 320, 335, 350, 365])
    flows = np.array([520, 570, 700, 640, 880, 1100, 1240, 1380, 1400, 1360,
                      1300, 1150, 940, 700, 540, 400, 310, 250, 205, 230,
                      265, 340, 460, 520]) * 1000.
    cycle = np.arange(730) % 365
    raw = PchipInterpolator(days, flows)(cycle)
    # Illustrative downstream gauge attenuation, not a routing calculation.
    if p.input_reference == 'tarbert':
        raw *= .85
    red = 20000. + 90000.*np.exp(-.5*((cycle-100)/35.)**2)
    q = raw.copy()
    if p.smooth_days:
        q = np.maximum(savgol_filter(q, p.smooth_days, 3), 0)
        red = np.maximum(savgol_filter(red, p.smooth_days, 3), 0)
    state, head = classify_states(q, red, p)
    series = pd.Series(q)
    return pd.DataFrame({
        'date': pd.date_range('2001-01-01', periods=365),
        'raw_discharge': raw[365:], 'discharge': q[365:],
        'red_river': red[365:], 'state': state[365:],
        'head_constraint': head[365:],
        'rise_trigger': (series.shift().rolling(p.rise_window).mean()
                         + p.rise_threshold).to_numpy()[365:],
        'recent_mean': series.shift().rolling(6).mean().to_numpy()[365:],
    })


def _state_runs(states):
    edges = np.r_[0, np.flatnonzero(np.diff(states)) + 1, len(states)]
    return zip(edges[:-1], edges[1:])


def draw_limb_delineation(figure, p, data=None):
    """Draw thresholds and engine states; keep rule annotations outside the data."""
    data = synthetic_limb_delineation(p) if data is None else data
    figure.clear()
    figure.set_facecolor('white')
    reference = 'Union Point' if p.input_reference == 'union_point' else 'Tarbert Landing'
    figure.suptitle('Limb delineation · illustrative Lower Mississippi year',
                    x=.10, y=.98, ha='left', fontsize=15, fontweight='bold', color='#173e58')
    figure.text(.10, .935, f'{reference} reference · daily discharge in cfs · fixed synthetic forcing, not observations',
                fontsize=10, color='#526575')
    grid = figure.add_gridspec(2, 2, width_ratios=[2.3, 1.25], height_ratios=[7, .65],
                              left=.10, right=.98, bottom=.23, top=.80, wspace=.22, hspace=.12)
    ax = figure.add_subplot(grid[0, 0])
    strip = figure.add_subplot(grid[1, 0], sharex=ax)
    rules = figure.add_subplot(grid[:, 1])
    rules.set_axis_off()
    dates = mdates.date2num(data.date)
    state = data.state.to_numpy()
    colors = {code: color for code, _, color in STATES}
    for start, end in _state_runs(state):
        left, right = dates[start]-.5, dates[end-1]+.5
        color = colors[state[start]]
        ax.axvspan(left, right, color=color, alpha=.13, lw=0)
        strip.axvspan(left, right, color=color, lw=0)
    ax.plot(data.date, data.discharge, color='#173e58', lw=2.2, label='Synthetic daily flow')
    ax.plot(data.date, data.rise_trigger, color='#af6800', lw=1.2, ls='--',
            label=f'Previous {p.rise_window}-day mean + rise threshold')
    ax.plot(data.date, data.recent_mean, color='#617785', lw=1.1, ls='--', label='Previous 6-day mean')
    for value, label, color in [(p.rise_min, 'Flood-rise minimum', colors[1]),
                                 (p.fall_min, 'Falling recent-mean minimum', colors[2]),
                                 (p.low_water, 'Low-water recent-mean threshold', colors[3])]:
        ax.axhline(value, color=color, lw=1.2, ls=':', label=f'{label}: {value:,.0f} cfs')
    if p.consider_head:
        mask = data.head_constraint
        ax.scatter(data.date[mask], data.discharge[mask], marker='^', color='#805222',
                   s=24, zorder=4, label='Head-proxy condition (separate flag)')
    ax.set_ylim(0, max(data.discharge.max()*1.18, 1))
    ax.set_xlim(dates[0]-.5, dates[-1]+.5)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{value:,.0f}'))
    ax.set_ylabel('Daily discharge (cfs)', fontsize=10)
    ax.tick_params(axis='both', labelsize=9)
    ax.tick_params(axis='x', labelbottom=False)
    ax.grid(axis='y', color='#cbd5df', alpha=.55)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)
    ax.legend(loc='lower left', bbox_to_anchor=(0, 1.015), borderaxespad=0,
              fontsize=8.5, frameon=False, ncol=2)
    strip.set_yticks([])
    strip.set_ylabel('State', fontsize=9, rotation=0, labelpad=22, va='center')
    strip.xaxis.set_major_locator(mdates.MonthLocator())
    strip.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
    strip.tick_params(axis='x', length=0, labelsize=9, pad=6)
    for spine in strip.spines.values():
        spine.set_visible(False)

    counts = {code: int((state == code).sum()) for code, _, _ in STATES}
    annotations = [
        (1., 'RISING', f'Q > {p.rise_min:,.0f} cfs AND\n'
         f'Q > previous {p.rise_window}-day mean\n'
         f'     + {p.rise_threshold:,.0f} cfs starts a flood.\n'
         f'First {p.crest_days} high-flow continuation days\n'
         'also stay rising; a fresh rise resets the count.'),
        (1.5, 'CREST', f'After {p.crest_days} high-flow continuation days,\n'
         f'Q still > {p.rise_min:,.0f} cfs in an active flood.\n'
         'A qualifying fresh rise takes priority.\n'
         'Crest state is not the exact hydrograph peak.'),
        (2., 'FALLING', 'Active flood AND Q < previous 6-day mean\n'
         f'AND that mean > {p.fall_min:,.0f} cfs.\n'
         'Rising / crest tests take priority.\n'
         'A declining flow alone need not be falling state.'),
        (3., 'LOW WATER', f'Previous 6-day mean < {p.low_water:,.0f} cfs,\n'
         'after higher-priority flood tests.\n'
         'Resets flood memory. The synthetic fall\n'
         'trough stays fixed when thresholds change.'),
    ]
    for y, (code, title, body) in zip([1.01, .75, .49, .23], annotations):
        text = rules.text(0, y, f'{title} · state {code:g} · {counts[code]} days\n{body}',
                          transform=rules.transAxes, ha='left', va='top', fontsize=9,
                          linespacing=1.45, color='#173e58',
                          bbox=dict(boxstyle='round,pad=.55', facecolor=colors[code]+'12',
                                    edgecolor=colors[code], linewidth=.8))
        text.set_gid('limb-rule')
    figure.legend(handles=[Patch(color=color, label=f'{name} ({counts[code]} d)')
                           for code, name, color in STATES],
                  loc='upper left', bbox_to_anchor=(.10, .18), ncol=5,
                  frameon=False, fontsize=9, borderaxespad=0)
    footer = ['States use one preceding synthetic year for history. Normal (0) applies when no other rule qualifies.',
              f'Input smoothing: {p.smooth_days} days (0 = off). Thresholds outside the plot range remain in effect; a state may have zero days.']
    if p.use_input_state:
        footer.append('Supplied-state mode is selected: this tab illustrates the automatic rules; actual runs use the CSV state column.')
    if p.consider_head:
        footer.append(f'Head proxy: qualifying rise below flood minimum and Red River < {p.red_head:,.0f} cfs; '
                      f'{int(data.head_constraint.sum())} days flagged. This flag does not change the limb state.')
    else:
        footer.append('Head-constraint proxy is disabled. The synthetic hydrograph is illustrative, not a forecast or operating plan.')
    figure.text(.10, .115, '\n'.join(footer), ha='left', va='top', fontsize=9,
                linespacing=1.7, color='#526575')
    return figure
