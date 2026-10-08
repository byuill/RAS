"""Aggregation of per-class sediment transport into user-selectable groups."""
from __future__ import annotations

import numpy as np

from sediment.grain_classes import SedimentGroup
from sediment.rouse import CAT_BED, CAT_MIXED, CAT_SUSPENDED, RouseConfig, rouse_category


def nansum_min1(a: np.ndarray, axis: int = 1) -> np.ndarray:
    """Sum ignoring NaN, but NaN when *every* element along ``axis`` is NaN (no silent zeros)."""
    a = np.asarray(a, dtype=float)
    out = np.nansum(a, axis=axis)
    all_nan = np.all(np.isnan(a), axis=axis)
    return np.where(all_nan, np.nan, out)


def sum_classes(values: np.ndarray, class_positions: list[int]) -> np.ndarray:
    """Sum selected columns (0-based positions) of a (time x class) array."""
    if not class_positions:
        return np.full(values.shape[0], np.nan)
    selected = values[:, class_positions]
    # A partial sum is not a complete sand/fines/total load.
    return np.where(np.isfinite(selected).all(axis=1), selected.sum(axis=1), np.nan)


def rouse_mask(p: np.ndarray, group_key: str, cfg: RouseConfig) -> np.ndarray:
    """Boolean (time x class) mask of class-time pairs belonging to a Rouse-based group."""
    cat = rouse_category(p, cfg.susp_max, cfg.bed_min)
    if group_key == "suspended_est":
        return (cat == CAT_SUSPENDED) | (cat == CAT_MIXED)
    if group_key == "bedload_est":
        return cat == CAT_BED
    if group_key == "rouse_suspended":
        return cat == CAT_SUSPENDED
    if group_key == "rouse_mixed":
        return cat == CAT_MIXED
    if group_key == "rouse_bed":
        return cat == CAT_BED
    raise KeyError(f"Unknown Rouse group '{group_key}'")


def aggregate(values: np.ndarray, class_indices: list[int], group: SedimentGroup,
              rouse: np.ndarray | None = None, cfg: RouseConfig | None = None) -> np.ndarray:
    """Aggregate a (time x class) additive quantity (flux or concentration) for ``group``.

    ``class_indices`` maps array columns to 1-based grain-class numbers.
    """
    if group.kind == "static":
        pos = [class_indices.index(k) for k in group.class_indices if k in class_indices]
        return sum_classes(values, pos)
    if rouse is None or cfg is None:
        raise ValueError("Rouse numbers are required for Rouse-based groups.")
    mask = rouse_mask(rouse, group.key, cfg)
    usable = np.isfinite(values)
    out = np.where(mask & usable, values, 0.0).sum(axis=1)
    out = np.where(usable.any(axis=1), out, np.nan)
    # Rouse number invalid for a class that carries sediment: the partition is unknown, not zero.
    unknown = ((np.isnan(rouse) | (rouse < 0)) & usable & (values != 0)).any(axis=1)
    unknown |= (mask & ~usable).any(axis=1)
    return np.where(unknown, np.nan, out)
