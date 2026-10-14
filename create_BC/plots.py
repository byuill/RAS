"""Conceptual river network and hydrographs using the same audited flow ledger."""
import numpy as np

from .engine import ORCC_COLUMNS


LABELS = {'Thebes': 'MMR / Thebes', 'Ohio': 'Ohio / Olmsted', 'BirdsPoint': 'Birds Point diversion',
    'NewMadrid': 'New Madrid return', 'Hatchie': 'Upper minor tributaries', 'Arkansas': 'Arkansas / White',
    'Yazoo': 'Yazoo / lower tributaries', 'ORCC_HydroP': 'ORCC Hydropower', 'ORCC_LowSill': 'ORCC Low Sill',
    'ORCC_Auxil': 'ORCC Auxiliary', 'overBank': 'ORCC Overbank', 'Morganza': 'Morganza',
    'BonnetCarre': 'Bonnet Carré', 'Davis_Pond': 'Davis Pond', 'Caernarvon': 'Caernarvon',
    'Siphons': 'LMR siphons', 'MGP': 'Mardi Gras Pass', 'PALH': 'Point à la Hache',
    'OstNep': 'Ostrica / Neptune', 'FSP': 'Fort St. Philip', 'BapCol': 'Baptist Collette',
    'GrandPass': 'Grand Pass', 'CubitsGapWB': 'Cubits Gap / West Bay', 'SWP_Flow': 'Southwest Pass',
    'SouthPass': 'South Pass', 'PassALoutre': 'Pass a Loutre', 'TarbertLanding': 'Tarbert Landing',
    'UnionPoint': 'Union Point', 'Simmesport': 'Simmesport (pre-Morganza)', 'Red_River': 'Red River'}


def draw_network(figure, result, index=0):
    figure.clear()
    row = result.flows.iloc[index]
    left, right = figure.subplots(1, 2)
    figure.subplots_adjust(left=.025, right=.975, bottom=.07, top=.90, wspace=.10)
    figure.suptitle(f"Lower Mississippi flow budget  ·  {row.date:%d %b %Y}  ·  cfs", fontsize=14, fontweight='bold')
    blue, teal, orange = '#246b9c', '#008779', '#b76327'

    def flow(q):
        return f'{abs(q):,.0f} cfs'

    def arrow(ax, start, end, q, color=blue, dashed=False):
        width = .6+3.4*np.sqrt(abs(q)/max(row.UnionPoint, 1))
        ax.annotate('', end, start, arrowprops=dict(arrowstyle='->', lw=width, color=color,
                                                  linestyle='--' if dashed else '-'))

    def branch(ax, name, y, side, inward=False):
        q = row[name]
        tip = (side*3.7, y)
        arrow(ax, tip if inward else (0, y), (0, y) if inward else tip, q,
              teal if inward else orange)
        ax.text(side*3.85, y, f'{LABELS[name]}\n{flow(q)}', ha='left' if side > 0 else 'right',
                va='center', fontsize=8)

    for ax in [left, right]:
        ax.set_xlim(-8.2, 8.2)
        ax.set_ylim(-2, 24)
        ax.axis('off')
    left.set_title('Regional inflows and Old River', fontsize=11)
    arrow(left, (-3, 22), (0, 21), row.Thebes, teal)
    arrow(left, (3, 22), (0, 21), row.Ohio, teal)
    left.text(-3, 23.3, f'MMR / Thebes\n{flow(row.Thebes)}', ha='center', va='top', fontsize=9)
    left.text(3, 23.3, f'Ohio / Olmsted\n{flow(row.Ohio)}', ha='center', va='top', fontsize=9)
    ys = [21, 19, 17, 15, 13, 11, 9]
    names = ['BirdsPoint', 'NewMadrid', 'Hatchie', 'Arkansas', 'Yazoo']
    running = row.Thebes+row.Ohio
    for i, name in enumerate(names):
        arrow(left, (0, ys[i]), (0, ys[i+1]), running)
        branch(left, name, ys[i+1], -1 if i % 2 == 0 else 1, inward=name != 'BirdsPoint')
        running += row[name]
    arrow(left, (0, 11), (0, 8.4), running)
    gap = row.upstream_residual_cfs
    left.text(0, 8.3, f'Union Point forcing\n{flow(row.UnionPoint)}', ha='center', va='top', fontsize=9,
              bbox=dict(boxstyle='round,pad=.35', fc='#edf4f8', ec=blue))
    left.text(-7.8, 6.6, f'Upstream gap: {gap:+,.0f} cfs\nGauge − estimated boundaries',
              fontsize=8, color='#a24921' if abs(gap) > 1 else teal)
    arrow(left, (0, 6.5), (0, 3.2), row.UnionPoint, dashed=abs(gap) > 1)
    arrow(left, (0, 4), (-3.3, 4), row.ORCC_total, orange)
    left.text(-3.5, 4.8, 'Old River diversion\n'+flow(row.ORCC_total), fontsize=9, ha='right')
    left.text(-7.8, 3.4, '\n'.join(f'{LABELS[c].replace("ORCC ", "")}: {flow(row[c])}'
                                   for c in ORCC_COLUMNS), fontsize=8, va='top')
    arrow(left, (-3.3, 4), (-3.3, .4), row.ORCC_total, orange)
    arrow(left, (-7, .6), (-3.3, .6), row.Red_River, teal)
    left.text(-7.8, -.7, 'Red River\n'+flow(row.Red_River), fontsize=8)
    left.text(-3.3, -1.5, 'Atchafalaya / Simmesport\n'+flow(row.Simmesport), fontsize=9, ha='center')
    left.text(0, 2.7, 'Tarbert Landing\n'+flow(row.TarbertLanding), fontsize=9, ha='center', va='top')

    right.set_title('Lower river diversions and distributaries', fontsize=11)
    right.text(0, 23.3, 'Tarbert Landing\n'+flow(row.TarbertLanding), ha='center', va='top', fontsize=9)
    remaining = row.TarbertLanding
    names = ['Morganza', 'BonnetCarre', 'Davis_Pond', 'Caernarvon', 'Siphons', 'MGP',
             'PALH', 'OstNep', 'FSP', 'BapCol', 'GrandPass', 'CubitsGapWB']
    y = 22.
    for i, name in enumerate(names):
        ny = y-1.5
        arrow(right, (0, y), (0, ny), remaining)
        branch(right, name, ny, -1 if i % 2 == 0 else 1)
        remaining += row[name]
        y = ny
    right.text(0, 3.4, 'Head of Passes\n'+flow(row.HeadOfPasses), ha='center', va='top', fontsize=9)
    for x, name in [(-5, 'SWP_Flow'), (0, 'SouthPass'), (5, 'PassALoutre')]:
        arrow(right, (0, 1.9), (x, -.6), row[name], orange)
        right.text(x, -1, LABELS[name]+'\n'+flow(row[name]), ha='center', va='top', fontsize=8)
    figure.text(.5, .013, 'Conceptual network; not to scale. Width ∝ √flow. Green: inflow. Orange: extraction. '
                'Terminal arrows show positive outflow magnitudes. No hydraulic travel time.', ha='center', fontsize=8)
    return figure


def draw_hydrographs(figure, result):
    figure.clear()
    f = result.flows
    axes = figure.subplots(3, 1, sharex=True)
    for col in ['UnionPoint', 'TarbertLanding', 'Red_River', 'Simmesport']:
        axes[0].plot(f.date, f[col], label=LABELS[col], lw=1)
    for col in ORCC_COLUMNS:
        axes[1].plot(f.date, -f[col], label=LABELS[col], lw=1)
    for col in ['upstream_residual_cfs', 'lower_residual_cfs', 'orcc_residual_cfs']:
        axes[2].plot(f.date, f[col], label=col.replace('_residual_cfs', '').capitalize(), lw=1)
    for ax, title in zip(axes, ['Gauge and receiving-channel flows', 'ORCC structure allocation',
                               'Budget residuals (forcing − partitioned flow)']):
        ax.set_title(title, loc='left', fontsize=10)
        ax.set_ylabel('cfs')
        ax.grid(alpha=.2)
        ax.legend(loc='upper right', fontsize=8, ncol=2)
    axes[2].axhline(0, color='black', lw=.5)
    figure.tight_layout()
    return figure
