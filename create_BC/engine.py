"""Daily empirical flow partitioning with explicit gauge and storage ledgers.

All flows are cfs. Boundary inflows are positive and lateral extractions negative.
Gauge estimates and terminal outflows are diagnostics, not additional lateral BCs.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from .parameters import Parameters
from .schemes import PASS_RATINGS, pass_outflow, spillway_outflows, terminal_fraction


ORCC_COLUMNS = ['ORCC_HydroP', 'ORCC_LowSill', 'ORCC_Auxil', 'overBank']
LOWER_COLUMNS = ['Morganza', 'BonnetCarre', 'Davis_Pond', 'Caernarvon', 'Siphons',
                 'MGP', 'PALH', 'OstNep', 'FSP', 'BapCol', 'GrandPass', 'CubitsGapWB',
                 'SWP_Flow', 'SouthPass', 'PassALoutre']
INFLOW_COLUMNS = ['Thebes', 'Ohio', 'NewMadrid', 'Hatchie', 'Arkansas', 'Yazoo']
EXTRACTION_COLUMNS = ['BirdsPoint'] + ORCC_COLUMNS + LOWER_COLUMNS


@dataclass
class BudgetResult:
    flows: pd.DataFrame
    issues: pd.DataFrame
    summary: dict
    parameters: Parameters
    input_data: pd.DataFrame
    split_data: pd.DataFrame


def read_daily(data):
    df = data.copy(deep=True) if isinstance(data, pd.DataFrame) else pd.read_csv(data)
    if 'date' not in df or 'discharge' not in df or df.empty:
        raise ValueError('Input must contain nonempty date and discharge columns')
    try:
        dates = pd.to_datetime(df['date'], errors='raise', format='mixed')
        if dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
            raise ValueError('Dates must be timezone-free daily dates at midnight')
    except (ValueError, AttributeError) as exc:
        raise ValueError(f'Invalid daily dates: {exc}') from exc
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('Dates must be valid, unique, and strictly increasing')
    if len(dates) > 1 and not dates.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError('Input must be continuous daily data; fill/review gaps explicitly')
    df = df.reset_index(drop=True)
    df['date'] = dates.to_numpy()
    for col in ['discharge', 'Red_River', 'ORCC', 'ORCC_sim', 'Eflows', 'state']:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors='raise')
            if not np.isfinite(df[col].to_numpy(dtype=float)).all() or (df[col] < 0).any():
                raise ValueError(f'{col} must contain finite, nonnegative values on every day')
    return df


def monthly_splits(table, dates, p, rng):
    table = table.copy() if isinstance(table, pd.DataFrame) else pd.read_csv(table)
    table.columns = table.columns.astype(str)
    if table.empty or not set(map(str, range(1, 13))) <= set(table.columns):
        raise ValueError('Split table must contain nonempty month columns 1 through 12')
    values = table[list(map(str, range(1, 13)))].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('Monthly splits must be finite and nonnegative')
    if p.split_semantics == 'fraction' and (values > 1).any():
        raise ValueError('MMR fractions must be in [0,1]; choose ratio for the calendar-year file')
    month = dates.dt.month.to_numpy() - 1
    if p.split_sampling == 'sample_year':
        years = dates.dt.year.to_numpy() + ((dates.dt.month.to_numpy() >= 10) if p.water_year else 0)
        selected = {y: int(rng.integers(len(values))) for y in np.unique(years)}
        raw = np.array([values[selected[y], m] for y, m in zip(years, month)])
    else:
        raw = values.mean(axis=0)[month]
    return raw / (1+raw) if p.split_semantics == 'ratio' else raw


def classify_states(q, red, p):
    n = len(q)
    state, head = np.zeros(n), np.zeros(n, dtype=bool)
    flood, crest = False, 0
    for i in range(n):
        recent = q[max(0, i-6):i]
        if len(recent) and recent.mean() < p.low_water:
            state[i] = 3
        if i < p.rise_window:
            continue
        preceding = q[i-p.rise_window:i].mean()
        if q[i] > preceding+p.rise_threshold and q[i] > p.rise_min:
            state[i], flood, crest = 1, True, 0
        elif q[i] > p.rise_min and flood:
            state[i] = 1 if crest < p.crest_days else 1.5
            crest += 1
        elif recent.mean() > q[i] and recent.mean() > p.fall_min and flood:
            state[i], crest = 2, 0
        elif recent.mean() < p.low_water:
            state[i], flood, crest = 3, False, 0
        else:
            state[i], flood, crest = 0, False, 0
        head[i] = (p.consider_head and q[i] > preceding+p.rise_threshold and
                   q[i] < p.rise_min and red[i] < p.red_head)
    return state, head


def calculate_budget(data, split_table=None, parameters=None):
    p = (parameters or Parameters()).validate()
    df = read_daily(data)
    if split_table is None:
        split_table = Path(__file__).parent / ('ohio_split_wyV2.csv' if p.water_year else 'ohio_split_cy.csv')
    split_table = split_table.copy(deep=True) if isinstance(split_table, pd.DataFrame) else pd.read_csv(split_table)
    rng = np.random.default_rng(p.seed)
    n, dates = len(df), df['date']
    q = df['discharge'].to_numpy(dtype=float).copy()
    red = df['Red_River'].to_numpy(dtype=float).copy() if 'Red_River' in df else None
    if red is None:
        if p.input_reference == 'union_point':
            raise ValueError('Union Point input requires Red_River')
        red = q*p.red_ratio
    issues = []

    def flag(mask, code, message, severity='warning'):
        mask = np.broadcast_to(np.asarray(mask, dtype=bool), (n,))
        for i in np.flatnonzero(mask):
            issues.append(dict(date=dates.iloc[i], code=code, severity=severity, message=message))

    if p.smooth_days:
        if p.smooth_days > n:
            raise ValueError('Smoothing window exceeds the number of input days')
        q = np.maximum(savgol_filter(q, p.smooth_days, 3), 0)
        red = np.maximum(savgol_filter(red, p.smooth_days, 3), 0)
        flag(True, 'smoothed_forcing', 'Gauge forcing was smoothed before partitioning; original data retained.', 'info')
    state, head = classify_states(q, red, p)
    if p.use_input_state:
        if 'state' not in df or not df.state.isin([0, 1, 1.5, 2, 3]).all():
            raise ValueError('Supplied state must contain only 0, 1, 1.5, 2, 3')
        state = df.state.to_numpy(dtype=float)
    ratio = np.select([state == 1, state == 1.5, state == 2, state == 3],
                      [p.rising_ratio, p.rising_ratio, p.falling_ratio, p.low_ratio], p.orcc_ratio)
    ratio = np.where(head, p.head_ratio, ratio)
    calculated = ((q+red)*(1-ratio)-red if p.input_reference == 'union_point'
                  else q*(1/ratio-1)-red)
    if p.orcc_mode == 'prescribed':
        col = 'ORCC_sim' if 'ORCC_sim' in df else 'ORCC'
        if col not in df:
            raise ValueError('Prescribed ORCC mode requires ORCC or ORCC_sim')
        requested = df[col].to_numpy(dtype=float).copy()
    else:
        requested = calculated.copy()
    # Tarbert-reference upstream flow is inferred BEFORE imposing operating constraints.
    # A negative calculated diversion requests reverse flow, which this scenario
    # model does not support. Infer upstream water using zero diversion, then
    # report the constrained request rather than constructing a negative source.
    up = q.copy() if p.input_reference == 'union_point' else q+np.maximum(requested, 0)
    if p.eflows:
        if 'Eflows' not in df:
            raise ValueError('E-flow analysis requires Simmesport targets in Eflows')
        target = df.Eflows.to_numpy(dtype=float)-red
        possible = ((target >= max(p.hp_min, p.eflow_min_orcc)) & (target <= p.orcc_max) & (target <= up)
                    & (up-target >= p.eflow_min_mainstem) & (up-target <= p.eflow_max_mainstem))
        requested = np.where(possible, target, requested)
        flag(~possible, 'eflow_fallback', 'Simmesport target is infeasible; baseline ORCC request retained.')
    original_target = requested.copy()
    if p.orcc_override:
        requested += np.maximum(up-requested-p.spill_threshold, 0)
    total = np.clip(requested, min(p.hp_min, p.orcc_max), p.orcc_max)
    total = np.minimum(total, up)
    # Available structure capacity depends on final mainstem flow. Recheck monotonically.
    for _ in range(3):
        tl = up-total
        hp_cap = np.where(tl >= p.mod_to_high, p.hp_cap_b, p.hp_cap_a)
        capacity = hp_cap+p.aux_cap+np.where(tl < p.low_to_mod, 0, p.ls_cap+p.overbank_cap)
        total = np.minimum(total, capacity)
    tl = up-total
    flag(np.abs(total-original_target) > 1e-6, 'orcc_adjusted', 'ORCC request altered by override, available water, or operating ceilings/minimum.')
    flag(total < p.hp_min-1e-6, 'hp_min_unmet', 'Insufficient water/capacity for hydropower minimum.')
    hp = np.minimum(total, np.where(tl >= p.mod_to_high, p.hp_cap_b, p.hp_cap_a))
    excess = total-hp
    overbank = np.where(tl < p.low_to_mod, 0, np.clip(excess-p.ls_cap, 0, p.overbank_cap))
    rest = excess-overbank
    ls = np.where(tl < p.low_to_mod, 0, rest*np.where(state == 1, p.dominant_share, 1-p.dominant_share))
    flux = rng.uniform(-p.orcc_flux, p.orcc_flux, n)*total
    ls = np.where(head, rest, ls+flux)
    # Bounded conservative allocation. Spill excess to overbank if Aux/Low Sill cannot carry it.
    overflow = np.maximum(rest-p.ls_cap-p.aux_cap, 0)
    overbank += overflow
    rest -= overflow
    ls = np.clip(ls, np.maximum(rest-p.aux_cap, 0), np.minimum(rest, p.ls_cap))
    aux = rest-ls
    flag(head & (aux > 1e-6), 'head_proxy_limited', 'Head proxy cannot put all non-hydropower flow through Low Sill within its ceiling.')

    fraction = monthly_splits(split_table, dates, p, rng)
    c_mmr, c_ohio, c_tribs = ((p.up_mmr, p.up_ohio, p.up_tribs) if p.input_reference == 'union_point'
                             else (p.tl_mmr, p.tl_ohio, p.tl_tribs))
    combined = q*(c_mmr+c_ohio)
    a, b = np.zeros(n), np.zeros(n)
    for year in dates.dt.year.unique():
        select = dates.dt.year.eq(year).to_numpy()
        mean = q[select].mean()
        a[select] = mean*rng.uniform(-p.annual_flux, p.annual_flux)
        b[select] = mean*rng.uniform(-p.annual_flux*.5, p.annual_flux*.5)
    combined += b
    if (combined < 0).any():
        raise ValueError('Annual perturbation makes combined headwater flow negative; reduce annual random flux')
    thebes = combined*fraction+a
    feasible_min = combined >= 2*p.mmr_min
    thebes = np.clip(thebes, np.where(feasible_min, p.mmr_min, 0),
                     np.where(feasible_min, combined-p.mmr_min, combined))
    ohio = combined-thebes
    flag(~feasible_min, 'headwater_min_unmet', 'Combined MMR/Ohio flow cannot support both requested minimums.')
    birds = np.maximum(combined-p.bp_threshold, 0)
    returns = np.convolve(birds, np.r_[np.zeros(p.bp_lag), p.bp_return_weights])*p.bp_efficiency
    nm = returns[:n]
    loss = birds*(1-p.bp_efficiency)
    # cfs-day stock converts to ft³ by multiplying by 86400, not by trapezoidal interpolation.
    storage = np.cumsum(birds-nm-loss)
    tribs = q*c_tribs-b
    if p.upstream_balance == 'close_minor':
        tribs = up-combined+birds-nm
        flag(True, 'minor_closure', 'Minor tributaries adjusted to close the prescribed Union Point budget.', 'info')
    if (tribs < -1e-7).any():
        raise ValueError('Scenario produces negative minor-tributary inflows; revise regional coefficients/perturbations')
    tribs = np.maximum(tribs, 0)
    shares = np.array([p.upper_share, p.middle_share, p.lower_share])
    if not np.isclose(shares.sum(), 1, atol=1e-10):
        flag(True, 'tributary_weights_normalized', 'Historical tributary weights normalized to sum to one.', 'info')
    shares /= shares.sum()
    f = pd.DataFrame(dict(date=dates, discharge=df.discharge, forcing_flow=q, Red_River=red,
                          Thebes=thebes, Ohio=ohio, LMR_Tribs=tribs, Hatchie=tribs*shares[0],
                          Arkansas=tribs*shares[1], Yazoo=tribs*shares[2], BirdsPoint=-birds, NewMadrid=nm,
                          ORCC_HydroP=-hp, ORCC_LowSill=-ls, ORCC_Auxil=-aux, overBank=-overbank,
                          ORCC_requested=original_target, ORCC_total=total, ORCC_adjustment=total-original_target,
                          UnionPoint=up, TarbertLanding=tl, Lat_Flow=up+red, Simmesport=total+red,
                          Rising_ID=state, head_constraint=head, MMR_fraction=fraction,
                          RandomFlux_A=a, RandomFlux_B=b, floodway_loss=loss,
                          floodway_storage_ft3=storage*86400))
    morg, bc = spillway_outflows(tl, p)
    spill = np.maximum(tl-p.spill_threshold, 0)
    f['Morganza'], f['BonnetCarre'] = -morg, -bc
    remaining = tl-spill
    for name, demand in [('Davis_Pond', p.davis), ('Caernarvon', p.caernarvon), ('Siphons', p.siphons)]:
        target = np.where(q >= p.diversion_trigger, demand, 0)
        amount = np.minimum(target, remaining)
        flag(amount < target-1e-6, 'diversion_limited', f'{name} limited by available mainstem water.')
        f[name] = -amount
        remaining -= amount
    for rating in PASS_RATINGS:
        raw, amount = pass_outflow(remaining, rating, p)
        flag(raw > remaining+1e-6, 'rating_limited', f'{rating.column} rating exceeds available water; extraction capped.')
        f[rating.column] = -amount
        remaining -= amount
    f['HeadOfPasses'] = remaining
    raw_fraction, swp_fraction = terminal_fraction(remaining, p)
    flag((raw_fraction < 0) | (raw_fraction > 1), 'swp_fraction_limited', 'Southwest Pass fraction constrained to [0,1].')
    f['SWP_Flow'] = -remaining*swp_fraction
    f['SouthPass'] = f['PassALoutre'] = -remaining*(1-swp_fraction)/2
    f['Terminal_Passes'] = f.SouthPass  # Legacy alias: EACH terminal pass, not their sum.
    f['upstream_residual_cfs'] = up-(combined+tribs-birds+nm)
    f['orcc_residual_cfs'] = total+f[ORCC_COLUMNS].sum(axis=1)
    f['latitude_residual_cfs'] = up+red-tl-f.Simmesport
    f['lower_residual_cfs'] = tl+f[LOWER_COLUMNS].sum(axis=1)
    f['whole_system_residual_cfs'] = (f[INFLOW_COLUMNS].sum(axis=1)+red+f.BirdsPoint+
                                    f[LOWER_COLUMNS].sum(axis=1)-f.Simmesport)
    flag(f.upstream_residual_cfs.abs() > 1, 'regional_gap', 'Estimated upstream boundaries differ from prescribed Union Point; inspect the regional residual.')
    if not np.isfinite(f.select_dtypes(include=[np.number]).to_numpy()).all():
        raise ValueError('Nonfinite computed discharge; check scenario coefficients')
    if (f[INFLOW_COLUMNS] < -1e-6).any().any() or (f[EXTRACTION_COLUMNS] > 1e-6).any().any():
        raise RuntimeError('Internal boundary sign check failed')
    if (overbank > p.overbank_cap+1e-6).any() or (ls > p.ls_cap+1e-6).any() or (aux > p.aux_cap+1e-6).any():
        raise RuntimeError('Internal ORCC capacity check failed')
    for col in ['orcc_residual_cfs', 'latitude_residual_cfs', 'lower_residual_cfs']:
        if f[col].abs().max() > 1e-6:
            raise RuntimeError(f'Internal budget check failed: {col}')
    issue_frame = pd.DataFrame(issues, columns=['date', 'code', 'severity', 'message'])
    summary = dict(days=n, start=str(dates.iloc[0].date()), end=str(dates.iloc[-1].date()),
        units='cfs', issue_counts=issue_frame.code.value_counts().to_dict(),
        input_sha256=sha256(df.to_csv(index=False).encode()).hexdigest(),
        splits_sha256=sha256(split_table.to_csv(index=False).encode()).hexdigest(),
        max_abs_residual_cfs={c: float(f[c].abs().max()) for c in f if c.endswith('_residual_cfs')},
        floodway_diverted_ft3=float(birds.sum()*86400), floodway_returned_ft3=float(nm.sum()*86400),
        floodway_loss_ft3=float(loss.sum()*86400), floodway_tail_ft3=float(returns[n:].sum()*86400),
        floodway_final_storage_ft3=float(storage[-1]*86400),
        eflow_unmet_days=int(np.sum(np.abs(f.Simmesport-df.Eflows) > 1)) if p.eflows else 0,
        regional_coefficients_preserved=p.upstream_balance == 'preserve',
        assumptions=['Daily empirical partitioning, not hydraulic routing or a stage-based operating rule.',
                     'Prescribed Union Point/Tarbert gauge forcing controls the downstream budget.',
                     'Red River is outside the Mississippi model; Simmesport is ORCC + Red River before Morganza.',
                     'Terminal pass magnitudes are diagnostics unless separately mapped to RAS boundaries.'])
    return BudgetResult(f, issue_frame, summary, p, df, split_table)
