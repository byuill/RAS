"""Serializable operating assumptions; historical defaults are not design ratings."""
from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
import math


def parameter(default, group, label, help, low=0., high=1e9):
    from dataclasses import field
    return field(default=default, metadata=dict(group=group, label=label, help=help, low=low, high=high))


@dataclass(frozen=True)
class Parameters:
    input_reference: str = parameter('union_point', 'Workflow', 'Discharge reference', 'Union Point is upstream of ORCC; Tarbert Landing is downstream.')
    orcc_mode: str = parameter('prescribed', 'Workflow', 'ORCC total', 'Prescribed uses ORCC/ORCC_sim from CSV; calculated uses the latitude-flow target.')
    split_semantics: str = parameter('fraction', 'Workflow', 'Monthly split values', 'WY V2 stores MMR/(MMR+Ohio) fractions; CY stores MMR/Ohio ratios.')
    split_sampling: str = parameter('monthly_mean', 'Workflow', 'Seasonal split sampling', 'Monthly mean or one sampled historical row per water/calendar year.')
    water_year: bool = parameter(True, 'Workflow', 'Use water years', 'October–September for seasonal sampling; dates are never shifted.')
    upstream_balance: str = parameter('preserve', 'Workflow', 'Regional budget closure', 'Preserve historical coefficients and report the gap, or adjust minor tributaries to match the prescribed gauge flow.')
    use_input_state: bool = parameter(False, 'Workflow', 'Use supplied hydrograph state', 'Requires state column: 0 normal, 1 rising, 1.5 crest, 2 falling, 3 low water.')
    eflows: bool = parameter(False, 'Workflow', 'Use Simmesport E-flow targets', 'Requires Eflows in CSV. Infeasible targets fall back to the prescribed/calculated ORCC target and are flagged.')
    seed: int = parameter(42, 'Workflow', 'Random seed', 'Repeatable seasonal sampling and perturbations.', 0, 2147483647)
    smooth_days: int = parameter(0, 'Workflow', 'Input smoothing window (days)', '0 disables smoothing. Odd window >=5 smooths gauge forcing before partitioning, not independent exported boundaries.', 0, 365)
    mmr_min: float = parameter(30000., 'Regional inflows', 'MMR and Ohio minimum (cfs)', 'Redistribute within the combined flow. Report infeasible minimums rather than adding water.')
    up_mmr: float = parameter(.352646, 'Regional inflows', 'Union Point → MMR coefficient', 'Together with Ohio defines combined headwater flow.', 0, 5)
    up_ohio: float = parameter(.432026, 'Regional inflows', 'Union Point → Ohio coefficient', 'Used for combined flow; monthly split sets the relative contributions.', 0, 5)
    up_tribs: float = parameter(.156022, 'Regional inflows', 'Union Point → minor tributaries', 'Historical regional estimate; coefficients do not sum to one.', 0, 5)
    tl_mmr: float = parameter(.457126, 'Regional inflows', 'Tarbert Landing → MMR', 'Historical combined-flow coefficient.', 0, 5)
    tl_ohio: float = parameter(.56002, 'Regional inflows', 'Tarbert Landing → Ohio', 'Historical combined-flow coefficient.', 0, 5)
    tl_tribs: float = parameter(.279125, 'Regional inflows', 'Tarbert Landing → minor tributaries', 'Historical regional estimate.', 0, 5)
    red_ratio: float = parameter(.132, 'Regional inflows', 'Tarbert Landing → Red River', 'Used only when Tarbert-reference input omits Red_River.', 0, 5)
    upper_share: float = parameter(.0625, 'Regional inflows', 'Upper minor-tributary weight', 'Legacy Hatchie boundary represents an aggregate tributary contribution.', 0, 1)
    middle_share: float = parameter(.505, 'Regional inflows', 'Arkansas/White weight', 'Weights are normalized to sum to one, with a recorded notice.', 0, 1)
    lower_share: float = parameter(.432, 'Regional inflows', 'Yazoo/lower tributary weight', 'Aggregate contribution, not a separately calibrated tributary hydrograph.', 0, 1)
    annual_flux: float = parameter(0., 'Regional inflows', 'Annual random-flux fraction', 'Exchange between MMR/Ohio and minor tributaries without changing the regional total.', 0, 1)
    bp_threshold: float = parameter(1810000., 'Floodway & spillways', 'Birds Point trigger (cfs)', 'Combined MMR+Ohio threshold; estimated flow trigger, not a stage-based operating plan.')
    bp_lag: int = parameter(2, 'Floodway & spillways', 'New Madrid base lag (days)', 'Convolve all diversions with eight-day return weights.', 0, 365)
    bp_efficiency: float = parameter(1., 'Floodway & spillways', 'Floodway return fraction', 'The non-returned fraction is a reported loss; delayed tail is retained in the ledger.', 0, 1)
    bp_return_weights: tuple = parameter((.5, .25, .1, .05, .05, .025, .015, .01), 'Floodway & spillways', 'Daily return weights (comma-separated)', 'After the base lag. Nonnegative weights must sum to one; efficiency controls the returned fraction.')
    spill_threshold: float = parameter(1250000., 'Floodway & spillways', 'Spillway mainstem threshold (cfs)', 'Applied at modeled Tarbert flow; travel time to Carrollton is not simulated.')
    spill_style: str = parameter('threshold', 'Floodway & spillways', 'Spillway allocation', 'Threshold fills Bonnet Carré first; ratio divides the excess.')
    bc_low_share: float = parameter(.75, 'Floodway & spillways', 'Bonnet Carré low-excess share', 'Ratio-style allocation only.', 0, 1)
    bc_high_share: float = parameter(.5, 'Floodway & spillways', 'Bonnet Carré high-excess share', 'Ratio-style allocation only.', 0, 1)
    bc_switch: float = parameter(250000., 'Floodway & spillways', 'Ratio switch excess (cfs)', 'Independent of the threshold-style Bonnet Carré ceiling.')
    bc_limit: float = parameter(250000., 'Floodway & spillways', 'Bonnet Carré allocation ceiling (cfs)', 'Legacy MorganzaQThres parameter; residual excess goes to Morganza.')
    orcc_override: bool = parameter(False, 'Floodway & spillways', 'Send excess to ORCC first', 'Subject to ORCC total, structure, and available-water limits.')
    orcc_ratio: float = parameter(.7, 'ORCC operations', 'Normal Mississippi latitude fraction', 'Fraction remaining in Mississippi: TL/(UP+Red River).', .01, 1)
    rising_ratio: float = parameter(.7, 'ORCC operations', 'Rising/crest Mississippi fraction', 'Calculated total mode only.', .01, 1)
    falling_ratio: float = parameter(.7, 'ORCC operations', 'Falling Mississippi fraction', 'Calculated total mode only.', .01, 1)
    low_ratio: float = parameter(.7, 'ORCC operations', 'Low-water Mississippi fraction', 'Calculated total mode only.', .01, 1)
    orcc_max: float = parameter(620000., 'ORCC operations', 'Total ORCC ceiling (cfs)', 'Historical scenario ceiling; prescribed values above it are flagged and constrained.')
    low_to_mod: float = parameter(300000., 'ORCC operations', 'Low → moderate mainstem flow (cfs)', 'Uses Tarbert flow after total diversion constraints.')
    mod_to_high: float = parameter(1000000., 'ORCC operations', 'Moderate → high mainstem flow (cfs)', 'Uses Tarbert flow after total diversion constraints.')
    hp_cap_a: float = parameter(150000., 'ORCC operations', 'Typical hydropower ceiling (cfs)', 'Hydropower allocation can never exceed the total diversion.')
    hp_cap_b: float = parameter(170000., 'ORCC operations', 'High-flow hydropower ceiling (cfs)', 'Historical high-flow scenario allocation.')
    hp_min: float = parameter(8000., 'ORCC operations', 'Hydropower minimum target (cfs)', 'Constrained by available water and capacity; unmet minimum is recorded.')
    ls_cap: float = parameter(130000., 'ORCC operations', 'Low Sill ceiling (cfs)', 'Enforced before allocation is exported.')
    overbank_cap: float = parameter(320000., 'ORCC operations', 'Overbank ceiling (cfs)', 'Enforced before allocation is exported.')
    aux_cap: float = parameter(620000., 'ORCC operations', 'Auxiliary scenario ceiling (cfs)', 'Legacy code has no independent auxiliary ceiling. Default equals total ORCC ceiling; supply a verified rating for your model.')
    dominant_share: float = parameter(.8, 'ORCC operations', 'Dominant structure fraction', 'Low Sill dominates rising flow, Auxiliary otherwise.', 0, 1)
    orcc_flux: float = parameter(0., 'ORCC operations', 'Daily allocation perturbation', 'Seeded conservative exchange between Low Sill and Auxiliary, bounded by their capacities.', 0, 1)
    consider_head: bool = parameter(False, 'Hydrograph state', 'Enable head-constraint proxy', 'Discharge-based scenario heuristic; it does not compute actual differential head.')
    head_ratio: float = parameter(.67, 'Hydrograph state', 'Head-proxy Mississippi fraction', 'Calculated ORCC total mode only.', .01, 1)
    rise_window: int = parameter(30, 'Hydrograph state', 'Trailing rise window (days)', 'Uses every preceding day, excluding the current day.', 7, 365)
    rise_threshold: float = parameter(100000., 'Hydrograph state', 'Rise above trailing mean (cfs)', 'Historical rise classifier threshold.')
    rise_min: float = parameter(1000000., 'Hydrograph state', 'Flood-rise minimum (cfs)', 'Based on the selected input reference.')
    fall_min: float = parameter(600000., 'Hydrograph state', 'Falling-limb recent mean (cfs)', 'Six-day trailing mean.')
    low_water: float = parameter(300000., 'Hydrograph state', 'Low-water recent mean (cfs)', 'Six-day trailing mean.')
    red_head: float = parameter(29000., 'Hydrograph state', 'Red River head-proxy threshold (cfs)', 'Requires a rise below flood-rise minimum.')
    crest_days: int = parameter(30, 'Hydrograph state', 'Maximum rising crest duration (days)', 'Subsequent crest uses state 1.5 and ordinary structure allocation.', 0, 365)
    eflow_min_orcc: float = parameter(100000., 'E-flow targets', 'Minimum feasible E-flow ORCC target (cfs)', 'The legacy environmental-flow floor, separate from the hydropower minimum.')
    eflow_min_mainstem: float = parameter(150000., 'E-flow targets', 'Minimum E-flow mainstem flow (cfs)', 'Reject Simmesport targets that leave too little flow in the Mississippi.')
    eflow_max_mainstem: float = parameter(1250000., 'E-flow targets', 'Maximum E-flow mainstem flow (cfs)', 'Reject targets outside the chosen environmental-flow mainstem envelope.')
    diversion_trigger: float = parameter(300000., 'Lower diversions', 'Diversion activation flow (cfs)', 'Legacy trigger uses the selected input gauge discharge.')
    davis: float = parameter(3055., 'Lower diversions', 'Davis Pond extraction (cfs)', 'Enter a positive magnitude; output lateral extraction is negative.')
    caernarvon: float = parameter(1742., 'Lower diversions', 'Caernarvon extraction (cfs)', 'Positive magnitude, bounded by remaining mainstem water.')
    siphons: float = parameter(2000., 'Lower diversions', 'LMR siphons extraction (cfs)', 'Positive magnitude, bounded by remaining mainstem water.')
    mg_a: float = parameter(24000., 'Pass rating curves', 'Mardi Gras log slope A', 'Qout=max(0, A ln(Qremaining) − B), capped at Qremaining.')
    mg_b: float = parameter(325029., 'Pass rating curves', 'Mardi Gras intercept B (cfs)', 'Natural logarithm; input and output discharge in cfs.')
    palh_a: float = parameter(52877., 'Pass rating curves', 'Point à la Hache log slope A', 'Evaluated after the constrained Mardi Gras extraction.')
    palh_b: float = parameter(715899., 'Pass rating curves', 'Point à la Hache intercept B (cfs)', 'Point à la Hache is distinct from Pass a Loutre.')
    ost_a: float = parameter(.1043, 'Pass rating curves', 'Ostrica/Neptune slope A', 'Linear Qout=max(0,A Qremaining−B), bounded by available water.', 0, 5)
    ost_b: float = parameter(8130., 'Pass rating curves', 'Ostrica/Neptune intercept B (cfs)', 'Empirical scenario relation.')
    fsp_a: float = parameter(.1412, 'Pass rating curves', 'Fort St. Philip slope A', 'Sequential linear extraction.', 0, 5)
    fsp_b: float = parameter(38667., 'Pass rating curves', 'Fort St. Philip intercept B (cfs)', 'Empirical scenario relation.')
    bap_a: float = parameter(.1124, 'Pass rating curves', 'Baptist Collette slope A', 'Sequential linear extraction.', 0, 5)
    bap_b: float = parameter(1365., 'Pass rating curves', 'Baptist Collette intercept B (cfs)', 'Empirical scenario relation.')
    gp_a: float = parameter(.0821, 'Pass rating curves', 'Grand Pass slope A', 'Sequential linear extraction.', 0, 5)
    gp_b: float = parameter(9377., 'Pass rating curves', 'Grand Pass intercept B (cfs)', 'Empirical scenario relation.')
    cg_a: float = parameter(.1683, 'Pass rating curves', 'Cubits Gap/West Bay slope A', 'Sequential linear extraction.', 0, 5)
    cg_b: float = parameter(9122., 'Pass rating curves', 'Cubits Gap/West Bay intercept B (cfs)', 'Empirical scenario relation.')
    swp_threshold: float = parameter(200000., 'Terminal passes', 'SW Pass curve switch (cfs)', 'Legacy piecewise SW Pass fraction has a small jump at this threshold.')
    swp_quad: float = parameter(7.5e-12, 'Terminal passes', 'SW Pass low-flow quadratic', 'Fraction = a Q² + b Q + c.', 0, 1)
    swp_low_slope: float = parameter(1.25e-6, 'Terminal passes', 'SW Pass low-flow slope', 'Legacy piecewise rating.', 0, 1)
    swp_low_offset: float = parameter(.1, 'Terminal passes', 'SW Pass low-flow offset', 'Fractions are bounded to [0,1].', 0, 1)
    swp_high_slope: float = parameter(6e-8, 'Terminal passes', 'SW Pass high-flow slope', 'Fraction = a Q + b.', 0, 1)
    swp_high_offset: float = parameter(.6375, 'Terminal passes', 'SW Pass high-flow offset', 'Remainder split equally between South Pass and Pass a Loutre.', 0, 1)

    def validate(self):
        options = dict(input_reference={'union_point', 'tarbert'}, orcc_mode={'prescribed', 'calculated'},
                       split_semantics={'fraction', 'ratio'}, split_sampling={'monthly_mean', 'sample_year'},
                       upstream_balance={'preserve', 'close_minor'}, spill_style={'threshold', 'ratio'})
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in options:
                if value not in options[f.name]:
                    raise ValueError(f'{f.name}: choose one of {sorted(options[f.name])}')
            elif f.name == 'bp_return_weights':
                if not isinstance(value, (tuple, list)) or not 1 <= len(value) <= 365:
                    raise ValueError('Floodway return weights require 1–365 numeric values')
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in value):
                    raise ValueError('Floodway return weights must be finite and nonnegative')
                if not math.isclose(sum(value), 1, abs_tol=1e-10):
                    raise ValueError('Floodway return weights must sum to one')
            elif isinstance(f.default, bool):
                if type(value) is not bool:
                    raise ValueError(f'{f.name} must be true or false')
            else:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError(f'{f.name} must be finite and numeric')
                if isinstance(f.default, int) and not isinstance(value, int):
                    raise ValueError(f'{f.name} must be an integer')
                if not f.metadata['low'] <= value <= f.metadata['high']:
                    raise ValueError(f"{f.name} must be between {f.metadata['low']} and {f.metadata['high']}")
        if self.low_to_mod >= self.mod_to_high:
            raise ValueError('ORCC low/moderate threshold must be less than moderate/high threshold')
        if self.eflow_min_mainstem >= self.eflow_max_mainstem:
            raise ValueError('E-flow minimum mainstem flow must be less than maximum')
        if self.hp_min > min(self.hp_cap_a, self.hp_cap_b, self.orcc_max):
            raise ValueError('Hydropower minimum must not exceed hydropower or ORCC ceilings')
        if self.hp_cap_b < self.hp_cap_a:
            raise ValueError('High-flow hydropower ceiling must be at least the typical ceiling')
        if self.upper_share + self.middle_share + self.lower_share <= 0:
            raise ValueError('At least one minor-tributary weight must be positive')
        if self.smooth_days and (self.smooth_days < 5 or self.smooth_days % 2 == 0):
            raise ValueError('Smoothing window must be zero or an odd integer >=5')
        return self

    def save(self, path):
        self.validate()
        Path(path).write_text(json.dumps(asdict(self), indent=2, allow_nan=False)+'\n', encoding='utf-8')

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Scenario must be a JSON object')
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown scenario parameters: {sorted(unknown)}')
        if isinstance(data.get('bp_return_weights'), list):
            data['bp_return_weights'] = tuple(data['bp_return_weights'])
        return cls(**data).validate()
