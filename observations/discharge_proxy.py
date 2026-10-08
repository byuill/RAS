"""Auditable discharge estimates: local observations first, then explicit river budgets.

No branch is treated as zero when its data are missing. No measured Q is replaced.
Positive lag means an upstream observation reaches the target later; negative lag
routes a downstream record backward. Daily means are estimates of sample-time Q.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analysis.calibration_metrics import interpolate_model_to_times
from observations.processing import ObservationSet
from sediment.units import flux_from_concentration

RULES_FILE = Path(__file__).resolve().parents[1] / 'config' / 'discharge_proxies.yaml'


def load_rules(path=RULES_FILE):
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    return data.get('stations', {})


def flow_series(obs, parameter_kind=None):
    """One finite measured Q per timestamp, preferring USGS daily over CWMS.

    Daily values are placed at local noon for bounded interpolation. Estimates
    are never recycled as measurements to build another proxy.
    """
    d = obs.df.copy()
    if parameter_kind:
        d = d[d['kind'].isin(parameter_kind)]
    q = pd.to_numeric(d['discharge_m3s'], errors='coerce')
    valid = np.isfinite(q) & (q >= 0)
    if 'q_is_proxy' in d:
        valid &= ~d.q_is_proxy.fillna(False).astype(bool)
    d = d[valid].copy()
    if d.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    times = pd.DatetimeIndex(d.index)
    daily = d['kind'].eq('daily').to_numpy()
    d.index = pd.DatetimeIndex(np.where(daily, (times.normalize()+pd.Timedelta(hours=12)).values, times.values))
    d['_priority'] = d['kind'].map({'instantaneous': 0, 'daily': 1, 'cwms': 2, 'sample': 3}).fillna(4)
    d = d.sort_values('_priority', kind='stable')
    return d[~d.index.duplicated(keep='first')].discharge_m3s.astype(float).sort_index()


def routed_values(series, times, lag_hours=0, max_gap_hours=36):
    shifted = series.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=float(lag_hours))
    return interpolate_model_to_times(shifted, pd.DatetimeIndex(times), 'interpolate', max_gap_hours).to_numpy()


def _budget(recipe, flows, times, primary_lag=None):
    result = np.zeros(len(times))
    for i, term in enumerate(recipe['terms']):
        coefficient = float(term.get('coefficient', 1))
        lag = primary_lag if i == 0 and primary_lag is not None else float(term.get('lag_hours', 0))
        if not np.isfinite(coefficient) or not np.isfinite(lag):
            raise ValueError('Proxy coefficients and lags must be finite.')
        result += coefficient*routed_values(flows.get(term['station'], pd.Series(dtype=float,
            index=pd.DatetimeIndex([]))), times, lag, float(recipe.get('max_gap_hours', 36)))
    return np.where(np.isfinite(result) & (result >= 0), result, np.nan)


def _allowed(recipe, times):
    allowed = ~pd.DatetimeIndex(times).year.isin(recipe.get('blocked_years', []))
    if recipe.get('valid_through'):
        allowed &= times < pd.Timestamp(recipe['valid_through']) + pd.Timedelta(days=1)
    for start, end in recipe.get('blocked_periods', []):
        allowed &= ~((times >= pd.Timestamp(start)) & (times < pd.Timestamp(end)+pd.Timedelta(days=1)))
    return allowed


def select_lag(recipe, flows, measured):
    """Select a primary routing lag using chronological holdout validation.

    Require 20 distinct measured dates and improvement on withheld observations.
    This calibrates timing only, without fitting an arbitrary discharge multiplier.
    """
    default = float(recipe['terms'][0].get('lag_hours', 0))
    q = measured.discharge_m3s.astype(float)
    valid = np.isfinite(q) & (q > 0) & _allowed(recipe, measured.index)
    if 'q_is_proxy' in measured:
        valid &= ~measured.q_is_proxy.fillna(False).astype(bool)
    q = q[valid].groupby(level=0).mean().sort_index()
    if len(q.index.normalize().unique()) < 20:
        return default, 'configured lag; too few measured dates to validate routing', None
    candidates = sorted(set([default] + [float(x) for x in recipe.get('primary_lag_candidates_hours', [])]))
    predictions = np.column_stack([_budget(recipe, flows, q.index, lag) for lag in candidates])
    common = np.isfinite(predictions).all(axis=1)
    if common.sum() < 20:
        return default, 'configured lag; insufficient common flow coverage for validation', None
    actual, predictions = q.to_numpy()[common], predictions[common]
    split = int(len(actual)*.7)
    if split < 14 or len(actual)-split < 6:
        return default, 'configured lag; insufficient validation pairs', None
    errors = np.sqrt(np.mean((predictions[:split] - actual[:split, None])**2, axis=0))
    best = int(np.argmin(errors)); base = candidates.index(default)
    validation = np.sqrt(np.mean((predictions[split:] - actual[split:, None])**2, axis=0))
    detail = {'n_train': split, 'n_holdout': len(actual)-split,
              'default_holdout_rmse_m3s': float(validation[base]), 'selected_holdout_rmse_m3s': float(validation[best])}
    if best != base and validation[best] < .9*validation[base]:
        return candidates[best], 'lag selected on training data and improved holdout RMSE by at least 10%', detail
    return default, 'configured lag retained; alternative did not improve holdout RMSE by 10%', detail


def fill_discharge(obs, local_flow=None, recipes=(), flows=None, local_station_id=None):
    """Return an observation copy with missing sediment-record Q filled and labeled."""
    d = obs.df.copy(deep=True)
    from observations.qaqc import excluded_mask
    out = replace(obs, df=d, sources=list(obs.sources), derivations=list(obs.derivations), notes=list(obs.notes),
                  cache_status=list(obs.cache_status))
    for name, default in [('q_is_proxy', False), ('q_method', 'reported'), ('q_sources', ''),
                          ('q_proxy_recipe', ''), ('q_lag_hours', np.nan), ('q_proxy_low_m3s', np.nan),
                          ('q_proxy_high_m3s', np.nan)]:
        if name not in d: d[name] = default
    if 'q_original_m3s' not in d: d['q_original_m3s'] = d.discharge_m3s.copy()
    d.loc[~np.isfinite(d.discharge_m3s), 'q_method'] = 'missing'
    sediment = d[[c for c in ('ssc_mg_l', 'ssl_kg_s', 'sand_mg_l', 'fines_mg_l') if c in d]].notna().any(axis=1) & ~excluded_mask(d, 'discharge_m3s')
    if local_flow is not None:
        # Subdaily readings precede daily-mean estimates.
        for kinds, method, gap in [(['instantaneous'], 'same-station subdaily interpolation', 3),
                                  (['daily', 'cwms'], 'same-station flow interpolation (daily/USACE)', 36)]:
            values = routed_values(flow_series(local_flow, kinds), d.index, max_gap_hours=gap)
            use = sediment & ~np.isfinite(d.discharge_m3s) & np.isfinite(values)
            d.loc[use, 'discharge_m3s'] = values[use]
            d.loc[use, 'q_is_proxy'] = True
            d.loc[use, 'q_method'] = method
            d.loc[use, 'q_sources'] = local_station_id or obs.station_id
            if use.any(): out.derivations.append(f'{use.sum()} missing Q values filled from {method}; no reported sample Q replaced.')
    flows = flows or {}
    for recipe in recipes:
        if not recipe.get('terms'): raise ValueError('A discharge proxy needs at least one mandatory term.')
        lag, lag_note, validation = select_lag(recipe, flows, obs.df)
        values = _budget(recipe, flows, d.index, lag)
        use = sediment & ~np.isfinite(d.discharge_m3s) & np.isfinite(values) & _allowed(recipe, d.index)
        if not use.any(): continue
        d.loc[use, 'discharge_m3s'] = values[use]
        d.loc[use, 'q_is_proxy'] = True
        d.loc[use, 'q_method'] = f'river mass-balance estimate; {lag_note}'
        d.loc[use, 'q_sources'] = ';'.join(term['station'] for term in recipe['terms'])
        d.loc[use, 'q_proxy_recipe'] = recipe['name']
        d.loc[use, 'q_lag_hours'] = lag
        candidates = recipe.get('primary_lag_candidates_hours') or [lag]
        scenarios = np.column_stack([_budget(recipe, flows, d.index, x) for x in candidates])
        complete = np.isfinite(scenarios).all(axis=1) & use
        d.loc[complete, 'q_proxy_low_m3s'] = scenarios[complete].min(axis=1)
        d.loc[complete, 'q_proxy_high_m3s'] = scenarios[complete].max(axis=1)
        out.derivations.append(f'{use.sum()} missing Q values filled by {recipe["name"]}; primary lag {lag:g} h; {lag_note}.')
        if validation: out.notes.append(f'{recipe["name"]} routing validation: {validation}')
        out.notes.append(recipe.get('notes', 'Unmeasured lateral inflow and reach storage are not represented.'))
    both = sediment & d.ssc_mg_l.notna() & d.discharge_m3s.notna() & d.ssl_kg_s.isna()
    if both.any():
        d.loc[both, 'ssl_kg_s'] = flux_from_concentration(d.loc[both, 'ssc_mg_l'], d.loc[both, 'discharge_m3s'])
        d.loc[both, 'qualifier'] = (d.loc[both, 'qualifier'].fillna('').astype(str)+' ssl=derived(SSCxQ)').str.strip()
        out.derivations.append(f'{both.sum()} loads derived from SSC × filled Q; proxy uncertainty also affects these loads.')
    remaining = int((sediment & ~np.isfinite(d.discharge_m3s)).sum())
    if remaining: out.notes.append(f'{remaining} sediment records still lack discharge; incomplete budgets and unsupported routing are left unknown.')
    if d.q_is_proxy.any():
        out.notes.append('Proxy Q is estimated, not measured. Lag sensitivity bounds are not confidence intervals; daily means do not resolve sample-time flow fluctuations.')
    return out
