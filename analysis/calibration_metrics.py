"""Calibration helpers: date filtering, model/observation pairing, loads, bins, rolling means."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sediment.units import SECONDS_PER_DAY
from analysis.seasonality import water_year_of


def filter_date_range(df: pd.DataFrame | pd.Series, start, end, whole_end_day: bool = True):
    """Inclusive date filter on a DatetimeIndex.

    ``start``/``end`` may be None.  With ``whole_end_day`` a date-only ``end`` includes the entire day
    (up to 23:59:59.999999999), which matches GUI date pickers that have day resolution.
    """
    s = pd.Timestamp(start) if start is not None else None
    e = pd.Timestamp(end) if end is not None else None
    if e is not None and whole_end_day and e == e.normalize():
        e = e + pd.Timedelta(days=1) - pd.Timedelta(1, unit="ns")
    mask = np.ones(len(df), dtype=bool)
    if s is not None:
        mask &= df.index >= s
    if e is not None:
        mask &= df.index <= e
    return df[mask]


def interpolate_model_to_times(model: pd.Series, times: pd.DatetimeIndex, mode: str = "interpolate",
                               max_gap_hours: float = 36.0, time_offset_hours: float = 0.0) -> pd.Series:
    """Model value at each observation time.

    * ``interpolate``: linear in time between the two bracketing model steps (both finite, spacing
      <= ``max_gap_hours``); otherwise NaN.
    * ``nearest``: nearest model step within ``max_gap_hours / 2``.

    ``time_offset_hours`` shifts the observation clock to model time (e.g. -6 for UTC -> CST), default 0.
    Observations outside the model period are NaN, never extrapolated.
    """
    m = model.dropna().sort_index()
    t = pd.DatetimeIndex(times) + pd.Timedelta(hours=time_offset_hours)
    out = np.full(len(t), np.nan)
    if len(m) == 0:
        return pd.Series(out, index=times)
    mt = m.index.values.astype("datetime64[ns]").astype(np.int64)
    tv = t.values.astype("datetime64[ns]").astype(np.int64)
    gap = max_gap_hours * 3600e9
    pos = np.searchsorted(mt, tv)
    for i, (p, v) in enumerate(zip(pos, tv)):
        if mode == "nearest":
            cands = [j for j in (p - 1, p) if 0 <= j < len(mt)]
            if not cands:
                continue
            j = min(cands, key=lambda k: abs(mt[k] - v))
            if abs(mt[j] - v) <= gap / 2:
                out[i] = m.values[j]
        else:
            if p == 0 or p >= len(mt):
                if p == 0 and len(mt) and mt[0] == v:
                    out[i] = m.values[0]
                elif p < len(mt) and mt[p] == v:
                    out[i] = m.values[p]
                continue
            if mt[p] == v:
                out[i] = m.values[p]
                continue
            t0, t1 = mt[p - 1], mt[p]
            if t1 - t0 > gap:
                continue
            w = (v - t0) / (t1 - t0)
            out[i] = m.values[p - 1] * (1 - w) + m.values[p] * w
    return pd.Series(out, index=times)


def step_mass_kg(flux_kg_s: pd.Series, dt_days: pd.Series) -> pd.Series:
    """Mass passing during each output step = flux * dt (backward interval, as HEC-RAS accumulates)."""
    return flux_kg_s * dt_days * SECONDS_PER_DAY


def cumulative_load(flux_kg_s: pd.Series, dt_days: pd.Series) -> tuple[pd.Series, int]:
    """Cumulative mass (kg) using the actual time step; returns (series, number of steps with missing flux)."""
    mass = step_mass_kg(flux_kg_s, dt_days)
    n_missing = int(mass.isna().sum() - (1 if np.isnan(dt_days.iloc[0]) else 0)) if len(mass) else 0
    return mass.fillna(0.0).cumsum(), max(n_missing, 0)


def periodic_loads(flux_kg_s: pd.Series, dt_days: pd.Series, by: str = "calendar") -> pd.DataFrame:
    """Annual (calendar) or water-year (Oct-Sep) load in kg, with the number of steps and missing steps.

    Each step is attributed to the day it covers (interval midpoint)."""
    mass = step_mass_kg(flux_kg_s, dt_days)
    mid = mass.index - pd.to_timedelta(dt_days.fillna(0.0).values / 2.0, unit="D")
    key = water_year_of(pd.DatetimeIndex(mid)) if by == "water" else pd.DatetimeIndex(mid).year
    g = pd.DataFrame({"mass_kg": mass.values, "key": key}).dropna(subset=["mass_kg"]).groupby("key")
    out = pd.DataFrame({"load_kg": g["mass_kg"].sum(), "n_steps": g["mass_kg"].count()})
    out.index.name = "WaterYear" if by == "water" else "Year"
    return out


def flow_bins(q: np.ndarray, y: np.ndarray, edges: np.ndarray, min_count: int = 3) -> pd.DataFrame:
    """Median / quartiles of ``y`` in discharge bins (edges in the same unit as q)."""
    q, y = np.asarray(q, float), np.asarray(y, float)
    ok = np.isfinite(q) & np.isfinite(y)
    cats = pd.cut(q[ok], bins=edges, include_lowest=True)
    df = pd.DataFrame({"y": y[ok], "bin": cats, "q": q[ok]})
    g = df.groupby("bin", observed=True)
    out = pd.DataFrame({"q_median": g["q"].median(), "y_median": g["y"].median(), "y_q25": g["y"].quantile(0.25),
                        "y_q75": g["y"].quantile(0.75), "n": g["y"].count()})
    return out[out["n"] >= min_count].reset_index(drop=True)


def exceedance_bins(q: np.ndarray, y: np.ndarray, n_bins: int = 10, min_count: int = 3) -> pd.DataFrame:
    """Median of ``y`` within discharge-exceedance-probability bins (equal-count bins of q)."""
    q, y = np.asarray(q, float), np.asarray(y, float)
    ok = np.isfinite(q) & np.isfinite(y)
    if ok.sum() < n_bins:
        return pd.DataFrame()
    edges = np.unique(np.quantile(q[ok], np.linspace(0, 1, n_bins + 1)))
    out = flow_bins(q, y, edges, min_count)
    if out.empty:
        return out
    out["exceedance_pct"] = [100.0 * (q[ok] >= m).mean() for m in out["q_median"]]
    return out


def rolling_mean(s: pd.Series, window_days: float) -> pd.Series:
    """Centered rolling mean over a time window (``window_days`` days)."""
    if window_days <= 0 or s.empty:
        return s
    return s.rolling(f"{window_days:g}D", center=True, min_periods=1).mean()
