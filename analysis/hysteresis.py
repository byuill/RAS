"""Hysteresis classification and diagnostics.

Origin of reused logic
----------------------
``classify_limbs`` follows ``classify_hysteresis`` in
``Sediment Boundary Conditions/SedRatingCurve/sed_rating/analysis.py``: daily discharge is interpolated
(<=3 days), the trailing ``window`` -day change is computed, and a day is **Rising** when the change is
>= ``rise_thresh`` (cfs) and discharge exceeds ``min_q`` (cfs, default 500,000).  The original tool
compares rising-limb and falling-limb rating curves by fitting them separately (see
``limb_fit_comparison``); it defines no numeric hysteresis index.  Falling (change <= -``rise_thresh``,
same discharge gate) mirrors the original docstring/plot labels.  Lawler et al. (2006) HI and the loop area
below are standard additions, clearly labelled as such.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from analysis.rating_curve import fit_power_law
from sediment.units import M3_PER_CFS


def classify_limbs(q_m3s: pd.Series, window_days: int = 7, rise_thresh_cfs: float = 5000.0,
                   min_q_cfs: float = 500_000.0, falling_min_q_cfs: float | None = None) -> pd.Series:
    """Daily-index Series of 'Rising' | 'Falling' | 'Other'."""
    if q_m3s.empty:
        return pd.Series(dtype=object)
    q = q_m3s.sort_index().resample("D").mean().interpolate(method="time", limit=3) / M3_PER_CFS
    delta = q - q.shift(window_days)
    fmin = min_q_cfs if falling_min_q_cfs is None else falling_min_q_cfs
    rising = ((delta >= rise_thresh_cfs) & (q > min_q_cfs)).fillna(False)
    falling = ((delta <= -rise_thresh_cfs) & (q > fmin)).fillna(False)
    labels = pd.Series("Other", index=q.index, dtype=object)
    labels[falling] = "Falling"
    labels[rising] = "Rising"
    return labels


def detect_events(q_m3s: pd.Series, min_prominence_frac: float = 0.15, min_separation_days: int = 30) -> list[dict]:
    """Hydrograph events = peaks with prominence >= fraction of the discharge range; each event extends from
    the lowest flow before the peak to the lowest flow after it (bounded by neighbouring peaks)."""
    q = q_m3s.sort_index().resample("D").mean().interpolate(method="time", limit=7).dropna()
    if len(q) < 10:
        return []
    rng = float(q.max() - q.min())
    if rng <= 0:
        return []
    peaks, _ = find_peaks(q.values, prominence=min_prominence_frac * rng, distance=min_separation_days)
    events = []
    for i, p in enumerate(peaks):
        lo = peaks[i - 1] if i > 0 else 0
        hi = peaks[i + 1] if i + 1 < len(peaks) else len(q) - 1
        s = lo + int(np.argmin(q.values[lo:p + 1]))
        e = p + int(np.argmin(q.values[p:hi + 1]))
        events.append({"peak": q.index[p], "start": q.index[s], "end": q.index[e], "peak_q_m3s": float(q.values[p])})
    return events


def limb_fit_comparison(x, y, labels, q_ref=None) -> dict:
    """Separate power-law fits for Rising vs Falling points (the original tool's approach).

    Returns the fits and, if both exist, the ratio rising/falling predicted at ``q_ref`` (default: the
    median x of all labelled points)."""
    x, y, labels = np.asarray(x, float), np.asarray(y, float), np.asarray(labels)
    out: dict = {}
    for name in ("Rising", "Falling"):
        m = labels == name
        out[name] = fit_power_law(x[m], y[m]) if m.sum() >= 3 else None
    lab = np.isin(labels, ["Rising", "Falling"]) & np.isfinite(x)
    if q_ref is None and lab.any():
        q_ref = float(np.median(x[lab]))
    out["q_ref"] = q_ref
    if out["Rising"] and out["Falling"] and q_ref:
        r, f = float(out["Rising"].predict(q_ref)), float(out["Falling"].predict(q_ref))
        out["ratio_rising_to_falling"] = r / f if f > 0 else np.nan
    return out


def event_hysteresis(x, y, levels=(0.25, 0.5, 0.75)) -> dict:
    """Loop diagnostics for ONE event (time-ordered x = hydraulic driver, y = sediment).

    * ``HI_*``: Lawler et al. (2006) index at fractions of the x range, HI = y_rising / y_falling - 1 (>0:
      sediment higher on the rising limb, i.e. clockwise loop; <0 counter-clockwise).
    * ``loop_area_norm``: signed shoelace area of the loop in unit-normalised (x, y) space
      (negative = clockwise).  Both are descriptive statistics, not an established calibration target.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 6 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return {}
    ip = int(np.argmax(x))
    xr, yr, xf, yf = x[:ip + 1], y[:ip + 1], x[ip:], y[ip:]
    out: dict = {"n": int(len(x))}
    if len(xr) < 2 or len(xf) < 2:
        return out
    xmin, xmax = x.min(), x.max()
    his = []
    for lv in levels:
        xl = xmin + lv * (xmax - xmin)
        yr_i = _interp_monotone(xr, yr, xl)
        yf_i = _interp_monotone(xf, yf, xl)
        hi = (yr_i / yf_i - 1.0) if (np.isfinite(yr_i) and np.isfinite(yf_i) and yf_i != 0) else np.nan
        out[f"HI_{int(lv * 100)}"] = float(hi)
        his.append(hi)
    out["HI_mean"] = float(np.nanmean(his)) if np.isfinite(his).any() else np.nan
    xn = (x - xmin) / (xmax - xmin)
    yn = (y - y.min()) / (y.max() - y.min())
    xc, yc = np.append(xn, xn[0]), np.append(yn, yn[0])
    area = 0.5 * np.sum(xc[:-1] * yc[1:] - xc[1:] * yc[:-1])
    out["loop_area_norm"] = float(area)
    out["direction"] = "clockwise" if area < 0 else "counter-clockwise"
    return out


def _interp_monotone(xs: np.ndarray, ys: np.ndarray, x0: float) -> float:
    order = np.argsort(xs)
    xs_s, ys_s = xs[order], ys[order]
    if x0 < xs_s[0] or x0 > xs_s[-1]:
        return np.nan
    return float(np.interp(x0, xs_s, ys_s))
