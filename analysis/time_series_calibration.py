"""Observed sediment transport functions and time-series calibration, in canonical units."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis.calibration_metrics import filter_date_range, interpolate_model_to_times
from analysis.statistics import paired_statistics
from sediment.units import concentration_from_flux, flux_from_concentration
from observations.qaqc import excluded_mask


@dataclass
class TransportFunction:
    form: str
    coefficients: np.ndarray  # ascending powers in normalized predictor z
    center: float
    scale: float
    q_min: float
    q_max: float
    n_total: int
    n_used: int
    smearing_factor: float
    r2: float
    rmse: float
    r2_log: float = float('nan')

    def predict(self, discharge, extrapolate=False, smear=False):
        q = np.asarray(discharge, dtype=float)
        valid = np.isfinite(q) & (q > 0)
        if not extrapolate:
            valid &= (q >= self.q_min) & (q <= self.q_max)
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            x = np.log(q) if self.form in ('power', 'logarithmic') else q
            y = np.polynomial.polynomial.polyval((x - self.center) / self.scale, self.coefficients)
            if self.form == 'power':
                y = np.exp(y) * (self.smearing_factor if smear else 1.0)
        return np.where(valid & np.isfinite(y) & (y >= 0), y, np.nan)

    def summary(self):
        predictor = 'ln(Q)' if self.form in ('power', 'logarithmic') else 'Q'
        polynomial = np.polynomial.Polynomial(self.coefficients)
        raw = polynomial(np.polynomial.Polynomial([-self.center/self.scale, 1/self.scale])).coef
        if self.form == 'power':
            equation = f'ln(y) = {raw[0]:.6g} + ({raw[1]:.6g}) ln(Q)'
        elif self.form == 'logarithmic':
            equation = f'y = {raw[0]:.6g} + ({raw[1]:.6g}) ln(Q)'
        else:
            equation = f'y = {raw[0]:.6g}' + ''.join(f' + ({c:.6g}) Q^{i}' for i, c in enumerate(raw[1:], 1))
        return {'form': self.form, 'degree': len(self.coefficients) - 1,
                'coefficients_ascending': self.coefficients.tolist(), 'center': self.center, 'scale': self.scale,
                'normalized_predictor': f'z = ({predictor} - center)/scale',
                'q_min_m3s': self.q_min, 'q_max_m3s': self.q_max, 'n_total': self.n_total,
                'n_used': self.n_used, 'n_excluded': self.n_total - self.n_used,
                'smearing_factor': self.smearing_factor, 'r2_original_space': self.r2,
                'r2_log_space': self.r2_log, 'rmse_canonical': self.rmse,
                'equation_canonical_units': equation}


def fit_transport_function(q, sediment, form='power', degree=2, min_points=3):
    """Fit positive-flow samples; reject insufficient spread and unstable regressions.

    Linear/log/polynomial regressions allow zero sediment. Power regressions use
    ln(y) and require y>0. Negative/nonfinite predictions are unknown, not clipped.
    """
    if form not in ('linear', 'power', 'logarithmic', 'polynomial'):
        raise ValueError('Choose linear, power, logarithmic or polynomial.')
    if form == 'polynomial' and (not isinstance(degree, int) or not 1 <= degree <= 5):
        raise ValueError('Polynomial degree must be an integer from 1 to 5.')
    q, y = np.asarray(q, float), np.asarray(sediment, float)
    if q.ndim != 1 or y.shape != q.shape:
        raise ValueError('Rating discharge and sediment must be equally sized vectors.')
    valid = np.isfinite(q) & np.isfinite(y) & (q > 0) & (y >= 0)
    if form == 'power':
        valid &= y > 0
    n = int(valid.sum())
    order = degree if form == 'polynomial' else 1
    required = max(min_points, order + (1 if min_points == 2 else 2))
    if n < required or len(np.unique(q[valid])) < order + 1:
        raise ValueError(f'{form.capitalize()} fit needs at least {required} valid points '
                         f'and {order + 1} distinct positive discharges ({n}/{len(q)} valid).')
    x = np.log(q[valid]) if form in ('power', 'logarithmic') else q[valid]
    target = np.log(y[valid]) if form == 'power' else y[valid]
    center, scale = float(x.min()/2 + x.max()/2), float(np.ptp(x) / 2)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Rating discharge spread must be finite and positive.')
    z = (x - center) / scale
    design = np.polynomial.polynomial.polyvander(z, order)
    coefficients, _, rank, singular = np.linalg.lstsq(design, target, rcond=None)
    if rank < order + 1 or singular[0] / singular[-1] > 1e10:
        raise ValueError('Rating fit is ill-conditioned; reduce polynomial degree or use more discharge variation.')
    predicted = design @ coefficients
    denom = float(np.sum((target - target.mean()) ** 2))
    r2_target = float(1 - np.sum((target - predicted) ** 2) / denom) if denom > 0 else np.nan
    smear = float(np.mean(np.exp(target - predicted))) if form == 'power' else 1.0
    if form == 'power':
        predicted = np.exp(predicted)
    denom_y = float(np.sum((y[valid] - y[valid].mean()) ** 2))
    r2_y = float(1 - np.sum((y[valid] - predicted) ** 2) / denom_y) if denom_y > 0 else np.nan
    return TransportFunction(form, coefficients, center, scale, float(q[valid].min()), float(q[valid].max()),
                             len(q), n, smear, r2_y, float(np.sqrt(np.mean((predicted - y[valid]) ** 2))),
                             r2_target if form == 'power' else np.nan)


def comparison_statistics(obs, mod):
    """Existing calibration metrics plus KGE, normalized RMSE and diagnostic scale."""
    result = paired_statistics(obs, mod)
    o, m = np.asarray(obs, float), np.asarray(mod, float)
    valid = np.isfinite(o) & np.isfinite(m)
    o, m = o[valid], m[valid]
    if len(o) < 2:
        return result
    result['median_error'] = float(np.median(m - o))
    result['nrmse_pct'] = float(100 * result['rmse'] / abs(o.mean())) if o.mean() != 0 else np.nan
    denom = float(m @ m)
    result['scale_model_to_reference'] = float((m @ o) / denom) if denom > 0 else np.nan
    if len(o) >= 3 and np.std(o) > 0 and np.std(m) > 0 and o.mean() != 0:
        r = result['pearson_r']
        result['kge'] = float(1 - np.sqrt((r - 1)**2 + (np.std(m)/np.std(o) - 1)**2 + (m.mean()/o.mean() - 1)**2))
        result['r_squared_pearson'] = r**2
    return result


def sediment_records(obs_df, variable, group, kinds):
    """Keep Q and sediment from the same record, including duplicate sample times."""
    if variable not in ('Conc', 'Flux') or group not in ('total', 'sand', 'fines'):
        raise ValueError('Measured comparison supports Total, Sand and Fines concentration or load.')
    d = obs_df[obs_df['kind'].isin(kinds)].copy()
    q = pd.to_numeric(d.get('discharge_m3s', pd.Series(np.nan, index=d.index)), errors='coerce')
    ccol = {'total': 'ssc_mg_l', 'sand': 'sand_mg_l', 'fines': 'fines_mg_l'}[group]
    c = pd.to_numeric(d.get(ccol, pd.Series(np.nan, index=d.index)), errors='coerce')
    y = c.to_numpy(float)
    reported = pd.to_numeric(d.get('ssl_kg_s', pd.Series(np.nan, index=d.index)), errors='coerce').to_numpy(float)
    if variable == 'Conc' and group == 'total':
        derived = concentration_from_flux(reported, q.to_numpy(float))
        y = np.where(np.isfinite(y), y, derived)
    if variable == 'Flux':
        derived = flux_from_concentration(c.to_numpy(float), q.to_numpy(float))
        if group == 'total':
            y = np.where(np.isfinite(reported), reported, derived)
        else:
            y = derived
    target = ccol if variable == 'Conc' or group != 'total' else 'ssl_kg_s'
    y = np.where(excluded_mask(d, target), np.nan, y)
    result = pd.DataFrame({'Q': q.to_numpy(float), 'obs': y}, index=d.index)
    for column in ('q_is_proxy', 'q_method', 'q_sources', 'q_proxy_recipe', 'q_lag_hours',
                   'q_proxy_low_m3s', 'q_proxy_high_m3s', 'qaqc_excluded_fields'):
        if column in d: result[column] = d[column].to_numpy()
    return result


@dataclass
class TimeSeriesComparison:
    samples: pd.DataFrame
    series: pd.DataFrame
    fit: TransportFunction | None
    notes: list[str]


def build_comparison(model, observations, variable='Conc', group='total', kinds=('sample', 'daily', 'cwms'),
                     start=None, end=None, mode='interpolate', max_gap_hours=36, offset_hours=0,
                     form='power', degree=2, driver='observed', extrapolate=False, smear=False,
                     include_rating=True, min_discharge_m3s=None, rating_points=None):
    """Build measured pairs and an optional rating-derived reference on model times.

    Observed Q is shifted to the model clock and linearly interpolated with the
    same gap limit. Duplicate finite Q observations are averaged explicitly.
    Model-driven references are conditional on simulated hydraulics, not independent.
    """
    if driver not in ('observed', 'model'):
        raise ValueError('Rating driver must be observed or model discharge.')
    if not np.isfinite(offset_hours):
        raise ValueError('Observation clock offset must be finite.')
    samples = sediment_records(observations, variable, group, kinds)
    samples.index = pd.DatetimeIndex(samples.index) + pd.Timedelta(hours=offset_hours)
    samples = filter_date_range(samples, start, end)
    notes = []
    if 'q_is_proxy' in samples and samples.q_is_proxy.fillna(False).any():
        notes.append(f'{samples.q_is_proxy.fillna(False).sum()} sediment records use estimated discharge; inspect Q provenance and QA/QC before interpreting fits.')
    if min_discharge_m3s is not None:
        if not np.isfinite(min_discharge_m3s) or min_discharge_m3s < 0:
            raise ValueError('The low-flow threshold must be finite and nonnegative.')
        low = np.isfinite(samples.Q) & (samples.Q < min_discharge_m3s)
        samples = samples[~low].copy()
        notes.append(f'{low.sum()} low-Q measurements excluded from this tab only; missing-Q measurements retained. Raw observations remain unchanged.')
    if variable == 'Flux':
        notes.append('Loads use reported total load where available, otherwise concentration × same-record discharge.'
                     if group == 'total' else 'Fraction loads are derived from fraction concentration × same-record discharge.')
    elif group == 'total':
        notes.append('Concentration uses reported SSC where available, otherwise reported load / same-record discharge.')
    samples['mod'] = interpolate_model_to_times(model[variable], samples.index, mode, max_gap_hours).to_numpy()
    series = filter_date_range(model[[variable, 'Q']].rename(columns={variable: 'mod'}), start, end).copy()
    series['rating_q'] = np.nan
    series['reference'] = np.nan
    fit = None
    if include_rating:
        try:
            if rating_points is not None:
                points = np.asarray(rating_points, float).reshape(-1, 2)
                fit = fit_transport_function(points[:, 0], points[:, 1], form, degree, min_points=2)
                notes.append('Rating function fitted to manually drawn control points, not observed measurements; fit diagnostics describe control points only.')
            else:
                fit = fit_transport_function(samples.Q.to_numpy(), samples.obs.to_numpy(), form, degree)
        except ValueError as exc:
            notes.append(f'Rating curve unavailable: {exc}')
        if fit is not None:
            if driver == 'model':
                series['rating_q'] = series.Q
                notes.append('Rating reference uses model discharge; it is conditional on model hydraulics.')
            else:
                # Q-only records are retained for a daily/continuous measured hydrograph.
                q = sediment_records(observations, variable, group, kinds).Q
                q = q[np.isfinite(q.to_numpy(float)) & ~q.index.isna()]
                q.index = pd.DatetimeIndex(q.index) + pd.Timedelta(hours=offset_hours)
                duplicates = int(q.index.duplicated().sum())
                if duplicates:
                    notes.append(f'{duplicates} duplicate discharge times averaged for the observed hydrograph only.')
                q = q.groupby(level=0).mean().sort_index()
                series['rating_q'] = interpolate_model_to_times(q, series.index, 'interpolate', max_gap_hours).to_numpy()
                notes.append('Rating reference uses observed discharge interpolated to model times; no time extrapolation.')
                if 'q_is_proxy' in observations and observations.q_is_proxy.fillna(False).any():
                    notes.append('The observation-set hydrograph also contains proxy discharge estimates; it is not entirely measured.')
            predictions = fit.predict(series.rating_q.to_numpy(), extrapolate, smear)
            series['reference'] = predictions
            notes.append(f'Fit uses {fit.n_used}/{fit.n_total} records; '
                         f'{np.isfinite(predictions).sum()}/{len(series)} model times have valid rating predictions.')
            if extrapolate:
                q = series.rating_q.to_numpy()
                outside = np.isfinite(q) & (q > 0) & ((q < fit.q_min) | (q > fit.q_max))
                notes.append(f'Discharge extrapolation enabled: {outside.sum()} times outside the fitted range.')
            else:
                notes.append('Predictions outside the fitted discharge range are omitted.')
            notes.append('Negative/nonfinite predictions and nonpositive discharge are omitted, not clipped.')
    samples['residual'] = samples['mod'] - samples['obs']
    series['residual'] = series['mod'] - series['reference']
    return TimeSeriesComparison(samples, series, fit, notes)
