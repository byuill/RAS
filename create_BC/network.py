"""River diagram with dedicated label columns and connector lanes.

The GUI gives this figure a minimum readable size inside a scroll area; text is
never shrunk to fit an arbitrarily small desktop viewport.
"""
import numpy as np
from textwrap import fill
from matplotlib.patches import FancyBboxPatch

from .budget_view import LOWER_JUNCTIONS, junction_budget, percent, percent_text
from .engine import ORCC_COLUMNS


BLUE, GREEN, ORANGE = '#246b9c', '#008779', '#b76327'


def draw_network(figure, result, index, labels, view='all'):
    if view not in {'all', 'regional', 'lower'}:
        raise ValueError('Network view must be all, regional, or lower')
    figure.clear()
    row = result.flows.iloc[index]
    shares = junction_budget(row).set_index('boundary')
    axes = np.atleast_1d(figure.subplots(1, 2 if view == 'all' else 1))
    figure.subplots_adjust(left=.025, right=.975, bottom=.095 if view == 'all' else .11, top=.92, wspace=.07)
    figure.suptitle(f'Lower Mississippi flow budget  ·  {row.date:%d %b %Y}', fontsize=14, fontweight='bold', y=.985)
    for ax in axes:
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')

    def value(q):
        return f'{abs(q):,.0f} cfs'

    def card(ax, x, y, width, height, text, color=BLUE, fontsize=9):
        box = FancyBboxPatch((x, y-height/2), width, height, boxstyle='round,pad=0.006',
                             facecolor='#f8fbfc', edgecolor=color, linewidth=.7, zorder=3)
        ax.add_patch(box)
        artist = ax.text(x+.012, y, text, va='center', ha='left', fontsize=fontsize,
                         color='#233a49', linespacing=1.5, zorder=4)
        artist.set_gid('budget-label')
        return artist

    def arrow(ax, start, end, q, color=BLUE, dashed=False):
        width = .6+3*np.sqrt(min(abs(q)/max(row.UnionPoint, 1), 2))
        artist = ax.annotate('', end, start, arrowprops=dict(arrowstyle='->', lw=width, color=color,
            linestyle='--' if dashed else '-', shrinkA=3, shrinkB=3), zorder=1)
        artist.arrow_patch.set_gid('budget-connector')

    def branch(ax, name, y, side):
        item = shares.loc[name]
        inflow = item.kind == 'inflow'
        endpoint = (.396 if side < 0 else .604, y)
        arrow(ax, endpoint if inflow else (.5, y), (.5, y) if inflow else endpoint,
              item.flow_cfs, GREEN if inflow else ORANGE)
        x = .012 if side < 0 else .612
        share = percent_text(item.percent)
        if np.isfinite(item.percent):
            detail = f'{share} in · {100-item.percent:.1f}% main' if inflow else f'{share} out · {100-item.percent:.1f}% stays'
        else:
            detail = 'Share — (zero reference flow)'
        card(ax, x, y, .376, .057, f'{labels[name]}\n{value(item.flow_cfs)}\n{detail}', GREEN if inflow else ORANGE)
        ax.plot(.5, y, 'o', ms=4, color=BLUE, zorder=2)

    if view in {'all', 'regional'}:
        ax = axes[0]
        ax.set_title('Regional inflows and Old River', fontsize=11, pad=12)
        for x, name in [(.02, 'Thebes'), (.61, 'Ohio')]:
            card(ax, x, .938, .37, .057, f'{labels[name]}\n{value(row[name])}\n{percent_text(shares.loc[name, "percent"])} of MMR + Ohio', GREEN)
        arrow(ax, (.205, .905), (.5, .871), row.Thebes, GREEN)
        arrow(ax, (.795, .905), (.5, .871), row.Ohio, GREEN)
        running, previous_y = row.Thebes+row.Ohio, .871
        for i, name in enumerate(['BirdsPoint', 'NewMadrid', 'Hatchie', 'Arkansas', 'Yazoo']):
            y = .82-i*.078
            arrow(ax, (.5, previous_y), (.5, y), running)
            branch(ax, name, y, -1 if i % 2 == 0 else 1)
            running += row[name]
            previous_y = y
        gap = row.upstream_residual_cfs
        gauge_share = percent_text(percent(running, row.UnionPoint))
        gap_share = percent_text(percent(gap, row.UnionPoint))
        arrow(ax, (.5, previous_y), (.5, .449), running, dashed=abs(gap) > 1)
        card(ax, .06, .395, .88, .087,
             f'Union Point forcing: {value(row.UnionPoint)}\n'
             f'Estimated upstream boundaries: {value(running)} ({gauge_share} of gauge)\n'
             f'Gauge − estimate: {gap:+,.0f} cfs ({gap_share} of gauge)',
             ORANGE if abs(gap) > 1 else BLUE)
        arrow(ax, (.5, .345), (.5, .322), row.UnionPoint)
        for x, name, title in [(.012, 'ORCC_total', 'Old River diversion'), (.612, 'TarbertLanding', 'Tarbert Landing')]:
            endpoint = (.396 if x < .5 else .604, .29)
            arrow(ax, (.5, .322), endpoint, row[name], ORANGE if name == 'ORCC_total' else BLUE)
            card(ax, x, .29, .376, .057,
                 f'{title}\n{value(row[name])}\n{percent_text(shares.loc[name, "percent"])} of Union Point',
                 ORANGE if name == 'ORCC_total' else BLUE)
        actual_latitude = percent_text(percent(row.TarbertLanding, row.Lat_Flow))
        ax.text(.99, .244, f'Actual Mississippi share of latitude flow: {actual_latitude}',
                ha='right', va='center', fontsize=8, color=BLUE).set_gid('budget-label')
        structure_text = 'ORCC structure allocation  ·  % of total diversion\n' + '\n'.join(
            f'{labels[name].replace("ORCC ", "")}: {value(row[name])}  ·  '
            f'{percent_text(shares.loc[name, "percent"])}' for name in ORCC_COLUMNS)
        card(ax, .06, .164, .88, .124, structure_text, ORANGE)
        arrow(ax, (.205, .251), (.205, .234), row.ORCC_total, ORANGE)
        # Sources to the receiving-channel total are given their own distinct lane.
        arrow(ax, (.65, .096), (.65, .081), row.ORCC_total, ORANGE)
        card(ax, .012, .045, .318, .064,
             f'Red River\n{value(row.Red_River)}\n{percent_text(percent(row.Red_River, row.Simmesport))} of Simmesport', GREEN, 8.5)
        arrow(ax, (.34, .045), (.405, .045), row.Red_River, GREEN)
        card(ax, .414, .045, .574, .064,
             f'Simmesport (pre-Morganza): {value(row.Simmesport)}\n'
             f'ORCC {percent_text(percent(row.ORCC_total, row.Simmesport))} + '
             f'Red River {percent_text(percent(row.Red_River, row.Simmesport))}', BLUE, 8.5)

    if view in {'all', 'lower'}:
        ax = axes[-1]
        ax.set_title('Lower river withdrawals and terminal passes', fontsize=11, pad=12)
        card(ax, .2, .938, .6, .057, f'Tarbert Landing\n{value(row.TarbertLanding)}', BLUE)
        remaining, previous_y = row.TarbertLanding, .905
        for i, name in enumerate(LOWER_JUNCTIONS):
            y = .849-i*.059
            arrow(ax, (.5, previous_y), (.5, y), remaining)
            branch(ax, name, y, -1 if i % 2 == 0 else 1)
            remaining += row[name]
            previous_y = y
        arrow(ax, (.5, previous_y), (.5, .164), remaining)
        card(ax, .19, .139, .62, .034, f'Head of Passes: {value(row.HeadOfPasses)}', BLUE)
        for x, name in [(.014, 'SWP_Flow'), (.35, 'SouthPass'), (.686, 'PassALoutre')]:
            arrow(ax, (.5, .114), (x+.15, .081), row[name], ORANGE)
            card(ax, x, .045, .30, .064,
                 f'{labels[name]}\n{value(row[name])}\n{percent_text(shares.loc[name, "percent"])} of Head of Passes', ORANGE, 8.5)
    wrap_width = 150 if view == 'all' else 80
    figure.text(.025, .064, fill('Percent bases: out / stays = arriving flow; in / main = merged flow; '
                'allocation bases are named on the cards. — = no reference flow.', wrap_width), fontsize=8, color='#394f5d')
    figure.text(.025, .025, fill('Green: inflow. Orange: withdrawal. Blue: mainstem. Arrow thickness is a visual flow cue. '
                'Daily empirical ledger; conceptual order, not mapped distances or travel-time routing.', wrap_width), fontsize=8, color='#394f5d')
    return figure
