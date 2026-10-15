"""Explanations limited to relationships visible in the supplied implementation."""

GROUP_GUIDES = {
    'Workflow': ('<b>Choose what the input represents before changing operating rules.</b> '
        'Union Point is the pre-ORCC forcing; Tarbert-reference input is post-diversion. '
        'Prescribed mode uses the CSV ORCC total; calculated mode selects a latitude-flow ratio by hydrograph state. '
        'Both then apply operating limits. Water-year selection changes the split table/sampling year, not observed dates. '
        'Greyed controls are inactive under the selected workflow; their saved values are retained.'),
    'Regional inflows': ('<b>The two large rivers share a combined estimate.</b> '
        'Combined MMR + Ohio = input flow × (MMR coefficient + Ohio coefficient), before the annual perturbation. '
        'The monthly table divides that combined estimate; the individual coefficients do not independently prescribe each river. '
        'Minor tributaries use their own coefficient, or the explicit gauge-closure option. '
        'The three tributary weights distribute that aggregate after normalization. This is an empirical regional budget, not reach routing.'),
    'Floodway & spillways': ('<b>These are two different operating schemes.</b> '
        'Birds Point removes only combined MMR/Ohio flow above its threshold. New Madrid returns it through a lagged kernel, '
        'adding overlapping returns and tracking losses/tail volume. '
        'Morganza/Bonnet Carré instead allocate excess modeled Tarbert flow. Threshold mode fills Bonnet Carré first; '
        'ratio mode changes its share at an excess-flow threshold. These discharge proxies do not calculate operating stages.'),
    'ORCC operations': ('<b>Set the total diversion, then distribute it among structures.</b> '
        'The latitude fraction means Tarbert / (Union Point + Red River). At r=0.7, it targets a 70/30 split of '
        'combined latitude flow, not a 30% diversion of Union Point alone. '
        'Low mainstem flow favors hydropower then Auxiliary; moderate/high regimes use Low Sill, Auxiliary and Overbank '
        'under their ceilings. Only state 1 gets the rising-limb dominant Low Sill share; state 1.5 uses ordinary allocation. '
        'Prescribed-total mode still applies structure allocation and capacity limits.'),
    'Hydrograph state': ('<b>State is a trailing-flow classifier, not a stage observation.</b> '
        'The full preceding rise-window mean excludes today. A qualifying rise starts flood state 1; continued high flow stays '
        'rising up to the crest-day limit, then becomes state 1.5. Falling and low-water tests use a preceding six-day mean. '
        'Before a full rise window exists, only the available low-water check is used. '
        'The optional head proxy flags a qualifying sub-flood rise with low Red River flow. '
        'Its effect in this code is to favor Low Sill and, in calculated mode, change the total ratio; actual differential head is not computed.'),
    'E-flow targets': ('<b>Eflows is a receiving-channel target at Simmesport.</b> '
        'Required ORCC = target Simmesport − Red River. A target is accepted only if it leaves mainstem flow inside the '
        'configured envelope and meets the ORCC target/available-water checks. Infeasible targets revert to the baseline request. '
        'Subsequent structure limits can still prevent the accepted request from being met; unmet days are reported.'),
    'Lower diversions': ('<b>Fixed requests triggered by the input gauge.</b> '
        'Below the trigger, Davis Pond, Caernarvon and siphon demands are zero. At/above it, their configured magnitudes are '
        'requested and removed in that order after spillways. Each is bounded by the water remaining. '
        'The activation gauge is the selected input reference, not local pass flow or a structure stage.'),
    'Pass rating curves': ('<b>Each pass sees a different local input.</b> '
        'Mardi Gras starts with flow after spillways and controlled diversions; each subsequent rating receives the remainder '
        'after the previous pass. Raw logarithmic/linear extractions are bounded to [0, local flow] before moving downstream. '
        'The Ratings tab shows formulas, local input spans, and the selected-day operating point. '
        'Coefficient source studies and calibrated flow ranges are not supplied in this folder.'),
    'Terminal passes': ('<b>This scheme fits a fraction rather than an extracted discharge.</b> '
        'A piecewise quadratic/linear relation gives the Southwest Pass fraction of Head of Passes flow. '
        'The fraction is bounded to [0,1], then multiplied by Head of Passes flow. '
        'South Pass and Pass a Loutre each get half the remainder. Their equality is a model assumption. '
        'The two Southwest branches need not be continuous at the switch; the Ratings tab reports that jump.'),
}

PARAMETER_NOTES = {
    'up_mmr': 'Only the sum of this coefficient and the Ohio coefficient sets the combined headwater estimate. The monthly split sets MMR versus Ohio.',
    'up_ohio': 'Only the sum with the MMR coefficient sets the combined headwater estimate. Changing their relative values while holding the sum fixed has no effect.',
    'tl_mmr': 'Tarbert-reference counterpart of the combined headwater estimate; monthly splits determine the individual river shares.',
    'tl_ohio': 'Added to the Tarbert MMR coefficient before multiplying the input flow; not a separately imposed Ohio discharge.',
    'annual_flux': 'A moves flow between MMR and Ohio. B increases their combined total and decreases the minor-tributary aggregate. Both are held constant within each calendar year and use the saved seed.',
    'dominant_share': 'For state 1, the preferred Low Sill share is this value; otherwise it is 1 minus this value. State 1.5 retains the rising total ratio but uses ordinary structure allocation. Capacity bounds may change the final share.',
    'bp_lag': 'Days before the first return weight is applied. Return-kernel length is set by the weight list; overlapping diversions add together.',
    'bc_limit': 'Threshold mode only: Bonnet Carré takes min(excess, this ceiling), and Morganza receives the remainder. This was named MorganzaQThres in the original script.',
    'bc_switch': 'Ratio mode only. This threshold is compared with excess above the mainstem spillway trigger, not with the full Tarbert discharge.',
    'orcc_ratio': 'Calculated mode only: r = Tarbert / (Union Point + Red River). Requested diversion = (1−r)(Union Point+Red River)−Red River. Operating bounds can move the final ratio.',
    'orcc_flux': 'Daily seeded exchange between preferred Low Sill and Auxiliary allocations, scaled by total diversion. It does not change the total ORCC diversion; structure bounds can limit the exchange.',
    'red_ratio': 'Used only for Tarbert-reference inputs that omit Red_River. When that column is present it takes precedence.',
}
