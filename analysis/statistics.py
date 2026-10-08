"""Goodness-of-fit statistics for paired observed / modelled values.

Percent bias is computed on sums (sum(m - o) / sum(o)) so near-zero observations cannot blow up the metric;
log-space statistics only use pairs with both values > 0 and report how many were used.
"""
from __future__ import annotations

import numpy as np


def paired_statistics(obs, mod, min_pairs: int = 2) -> dict:
    o = np.asarray(obs, dtype=float)
    m = np.asarray(mod, dtype=float)
    ok = np.isfinite(o) & np.isfinite(m)
    o, m = o[ok], m[ok]
    n = int(len(o))
    out: dict = {"n_pairs": n}
    if n < min_pairs:
        return out
    err = m - o
    out["bias"] = float(err.mean())
    out["pbias_pct"] = float(100.0 * err.sum() / o.sum()) if o.sum() != 0 else np.nan
    out["mae"] = float(np.abs(err).mean())
    out["rmse"] = float(np.sqrt((err ** 2).mean()))
    out["mean_obs"] = float(o.mean())
    out["mean_mod"] = float(m.mean())
    if n >= 3 and np.std(o) > 0 and np.std(m) > 0:
        out["pearson_r"] = float(np.corrcoef(o, m)[0, 1])
    denom = float(((o - o.mean()) ** 2).sum())
    out["nse"] = float(1.0 - (err ** 2).sum() / denom) if denom > 0 else np.nan
    pos = (o > 0) & (m > 0)
    out["n_pairs_log"] = int(pos.sum())
    if pos.sum() >= min_pairs:
        lr = np.log10(m[pos] / o[pos])
        out["log10_mean_ratio"] = float(lr.mean())         # geometric bias: 10**x = typical mod/obs factor
        out["geometric_ratio"] = float(10 ** lr.mean())
        out["log10_rmse"] = float(np.sqrt((lr ** 2).mean()))
        if pos.sum() >= 3 and np.std(np.log10(o[pos])) > 0 and np.std(np.log10(m[pos])) > 0:
            out["pearson_r_log"] = float(np.corrcoef(np.log10(o[pos]), np.log10(m[pos]))[0, 1])
    return out
