"""Conceptual river network and hydrographs using the same audited flow ledger."""
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
    'UnionPoint': 'Union Point', 'Simmesport': 'Simmesport (pre-Morganza)', 'Red_River': 'Red River',
    'ORCC_total': 'Total ORCC diversion', 'ORCC_to_Simmesport': 'ORCC contribution to Simmesport'}


def draw_network(figure, result, index=0, view='all'):
    from .network import draw_network as render
    return render(figure, result, index, LABELS, view)


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
