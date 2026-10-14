"""Explicit junction percentage denominators for the conceptual flow ledger."""
import numpy as np
import pandas as pd

from .engine import ORCC_COLUMNS


LOWER_JUNCTIONS = ['Morganza', 'BonnetCarre', 'Davis_Pond', 'Caernarvon', 'Siphons',
                  'MGP', 'PALH', 'OstNep', 'FSP', 'BapCol', 'GrandPass', 'CubitsGapWB']


def percent(flow, denominator):
    return 100*float(flow)/float(denominator) if denominator > 0 else np.nan


def percent_text(value):
    return f'{value:.1f}%' if np.isfinite(value) else '—'


def junction_budget(row):
    """One selected-day table; each row names the percentage's reference flow.

    Confluences use merged flow; withdrawals use arriving flow. Allocation rows
    use the parent total. No gauge-gap correction is silently treated as water.
    """
    entries = []

    def add(column, q, total, basis, kind, continuing=None):
        entries.append(dict(date=row.date, boundary=column, kind=kind, flow_cfs=float(q),
                            reference_flow_cfs=float(total), percent=percent(q, total), percent_basis=basis,
                            mainstem_after_cfs=float(continuing) if continuing is not None else np.nan))

    combined = row.Thebes+row.Ohio
    for name in ['Thebes', 'Ohio']:
        add(name, row[name], combined, 'MMR + Ohio at their confluence', 'source')
    running = combined
    for name in ['BirdsPoint', 'NewMadrid', 'Hatchie', 'Arkansas', 'Yazoo']:
        branch = abs(row[name])
        inflow = name != 'BirdsPoint'
        after = running+row[name]
        basis = 'Merged flow after '+name if inflow else 'MMR + Ohio before Birds Point'
        add(name, branch, after if inflow else running, basis, 'inflow' if inflow else 'withdrawal', after)
        running = after
    for name, q in [('ORCC_total', row.ORCC_total), ('TarbertLanding', row.TarbertLanding)]:
        add(name, q, row.UnionPoint, 'Union Point forcing before ORCC', 'allocation')
    for name in ORCC_COLUMNS:
        add(name, abs(row[name]), row.ORCC_total, 'Total ORCC diversion', 'structure')
    for name, q in [('ORCC_to_Simmesport', row.ORCC_total), ('Red_River', row.Red_River)]:
        add(name, q, row.Simmesport, 'Simmesport = ORCC + Red River (pre-Morganza)', 'source')
    running = row.TarbertLanding
    for name in LOWER_JUNCTIONS:
        after = running+row[name]
        add(name, abs(row[name]), running, 'Mainstem flow arriving at '+name, 'withdrawal', after)
        running = after
    for name in ['SWP_Flow', 'SouthPass', 'PassALoutre']:
        add(name, abs(row[name]), row.HeadOfPasses, 'Head of Passes before the three-way split', 'terminal')
    return pd.DataFrame(entries)
