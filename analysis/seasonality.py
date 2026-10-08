"""Calendar and hydrologic seasonality.

Origin of reused logic
----------------------
``detect_first_major_flood`` and ``classify_hydrologic_periods`` are refactored from
``Sediment Boundary Conditions/SedRatingCurve/sed_rating/analysis.py`` (``detect_first_major_flood``,
``classify_seasonal``): per calendar year, the first date (Jan-Aug) where the trailing 7-day rise is at least
``rise_thresh`` AND discharge is at least ``abs_thresh`` starts the "first rising limb", which lasts to the
year's peak; other days are "before peak" / "after peak" (or Rising / Falling from the limb classifier).
Thresholds are specified in cfs as in the original tool and converted from the canonical m3/s here.
Calendar month / meteorological season labels (DJF, MAM, JJA, SON) are new.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sediment.units import M3_PER_CFS

SEASONS = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM", 6: "JJA", 7: "JJA", 8: "JJA",
           9: "SON", 10: "SON", 11: "SON"}
SEASON_ORDER = ["DJF", "MAM", "JJA", "SON"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

HYDRO_LABELS = {
    "FIRST_RISING": "First rising limb", "Rising": "Rising limb", "Falling": "Falling limb",
    "BEFORE_PEAK_OTHER": "Before peak - other", "AFTER_PEAK_OTHER": "After peak - other", "Other": "Other",
}


def month_of(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(index.month)


def season_of(index: pd.DatetimeIndex) -> np.ndarray:
    return np.array([SEASONS[m] for m in index.month])


def water_year_of(index: pd.DatetimeIndex) -> np.ndarray:
    return np.where(index.month >= 10, index.year + 1, index.year)


def add_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with Month, Season, WaterYear columns (index must be a DatetimeIndex)."""
    out = df.copy()
    out["Month"] = month_of(out.index)
    out["Season"] = season_of(out.index)
    out["WaterYear"] = water_year_of(out.index)
    return out


def filter_months(df: pd.DataFrame, months: list[int] | None = None, seasons: list[str] | None = None) -> pd.DataFrame:
    mask = np.ones(len(df), dtype=bool)
    if months:
        mask &= np.isin(df.index.month, months)
    if seasons:
        mask &= np.isin(season_of(df.index), seasons)
    return df[mask]


def _daily(q_m3s: pd.Series) -> pd.Series:
    s = q_m3s.sort_index()
    s = s.resample("D").mean()
    return s.interpolate(method="time", limit=7)


def detect_first_major_flood(q_year_cfs: pd.Series, rise_thresh_cfs: float = 300_000.0,
                             abs_thresh_cfs: float = 600_000.0, rise_window: int = 7):
    """(flood_start, peak_date) for one calendar year of daily discharge (cfs), else (None, None)."""
    if q_year_cfs.empty:
        return None, None
    q = q_year_cfs.sort_index().asfreq("D").interpolate(method="time", limit=7)
    delta = q - q.shift(rise_window)
    scan = q[q.index.month <= 8]
    for date in scan.index:
        d, v = delta.get(date, np.nan), q.get(date, np.nan)
        if np.isnan(d) or np.isnan(v):
            continue
        if d >= rise_thresh_cfs and v >= abs_thresh_cfs:
            return date, q.idxmax()
    return None, None


def classify_hydrologic_periods(q_m3s: pd.Series, rise_thresh_cfs: float = 300_000.0,
                                abs_thresh_cfs: float = 600_000.0, rise_window: int = 7,
                                limb_labels: pd.Series | None = None) -> pd.Series:
    """Label each day FIRST_RISING / Rising / Falling / BEFORE_PEAK_OTHER / AFTER_PEAK_OTHER.

    ``q_m3s`` is discharge in m3/s (any time step; daily means are used, as in the original tool).
    Returns a Series on the daily index; use :func:`map_daily_to_index` for other indices.
    """
    q = _daily(q_m3s) / M3_PER_CFS  # cfs, as the thresholds are defined
    labels = pd.Series("BEFORE_PEAK_OTHER", index=q.index, dtype=object)
    for year in q.index.year.unique():
        qy = q[q.index.year == year]
        if qy.dropna().empty:
            continue
        peak = qy.idxmax()
        start, _ = detect_first_major_flood(qy, rise_thresh_cfs, abs_thresh_cfs, rise_window)
        for d in qy.index:
            if start is not None and start <= d <= peak:
                labels[d] = "FIRST_RISING"
                continue
            h = limb_labels.get(d, "Other") if limb_labels is not None else "Other"
            if h in ("Rising", "Falling"):
                labels[d] = h
            else:
                labels[d] = "BEFORE_PEAK_OTHER" if d <= peak else "AFTER_PEAK_OTHER"
    return labels


def map_daily_to_index(daily_labels: pd.Series, index: pd.DatetimeIndex, default: str = "Other") -> np.ndarray:
    keys = index.normalize()
    return daily_labels.reindex(keys).fillna(default).to_numpy()
