"""Empirical outflow formulas shared by calculations and explanatory plots.

These encode the supplied parameterization; they do not establish its calibration
range, measurement provenance, or applicability to a different hydraulic model.
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PassRating:
    column: str
    label: str
    a_parameter: str
    b_parameter: str
    logarithmic: bool = False


PASS_RATINGS = (
    PassRating('MGP', 'Mardi Gras Pass', 'mg_a', 'mg_b', True),
    PassRating('PALH', 'Point à la Hache', 'palh_a', 'palh_b', True),
    PassRating('OstNep', 'Ostrica / Neptune', 'ost_a', 'ost_b'),
    PassRating('FSP', 'Fort St. Philip', 'fsp_a', 'fsp_b'),
    PassRating('BapCol', 'Baptist Collette', 'bap_a', 'bap_b'),
    PassRating('GrandPass', 'Grand Pass', 'gp_a', 'gp_b'),
    PassRating('CubitsGapWB', 'Cubits Gap / West Bay', 'cg_a', 'cg_b'),
)
RATING_CHOICES = [('all_passes', 'Overview · seven pass outflow ratings')] + [
    (r.column, r.label) for r in PASS_RATINGS] + [
    ('terminal', 'Terminal passes · flow fractions'),
    ('controlled', 'Davis Pond, Caernarvon & siphons · activation'),
    ('spillways', 'Morganza & Bonnet Carré · excess allocation'),
    ('birds', 'Birds Point & New Madrid · diversion and return'),
    ('orcc', 'ORCC total · latitude-flow target'),
]


def pass_outflow(q, rating, p):
    q = np.asarray(q, dtype=float)
    a, b = getattr(p, rating.a_parameter), getattr(p, rating.b_parameter)
    raw = a*(np.log(np.maximum(q, 1)) if rating.logarithmic else q)-b
    return raw, np.clip(raw, 0, q)


def terminal_fraction(q, p):
    q = np.asarray(q, dtype=float)
    raw = np.where(q < p.swp_threshold,
        p.swp_quad*q**2+p.swp_low_slope*q+p.swp_low_offset,
        p.swp_high_slope*q+p.swp_high_offset)
    return raw, np.clip(raw, 0, 1)


def spillway_outflows(q, p):
    excess = np.maximum(np.asarray(q, dtype=float)-p.spill_threshold, 0)
    bc = (np.minimum(excess, p.bc_limit) if p.spill_style == 'threshold' else
          excess*np.where(excess < p.bc_switch, p.bc_low_share, p.bc_high_share))
    return excess-bc, bc


def pass_input_flows(flows):
    """Recover the exact local rating inputs from the signed output ledger."""
    remaining = flows.TarbertLanding+flows[['Morganza', 'BonnetCarre', 'Davis_Pond', 'Caernarvon', 'Siphons']].sum(axis=1)
    inputs = {}
    for rating in PASS_RATINGS:
        inputs[rating.column] = remaining.copy()
        remaining = remaining+flows[rating.column]
    return inputs
