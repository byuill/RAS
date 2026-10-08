"""Observed-series selection for a model variable / sediment group (no fabrication of unavailable data)."""
from __future__ import annotations

import pandas as pd

from sediment.units import flux_from_concentration


def observed_series(obs_df: pd.DataFrame, var_key: str, group_key: str, kinds: list[str] | None = None
                    ) -> tuple[pd.Series, str]:
    """Return (series in canonical units indexed by time, short note).  Empty if no comparable observation."""
    if obs_df is None or obs_df.empty:
        return pd.Series(dtype=float), ""
    d = obs_df if not kinds else obs_df[obs_df["kind"].isin(kinds)]
    note = ""
    if var_key == "Q":
        s = d["discharge_m3s"]
    elif var_key == "Stage":
        s = d["stage_elev_m"]
        note = "NAVD88 elevation = gage height + gage zero"
    elif var_key == "Conc":
        col = {"total": "ssc_mg_l", "sand": "sand_mg_l", "fines": "fines_mg_l"}.get(group_key)
        s = d[col] if col else pd.Series(dtype=float)
    elif var_key == "Flux":
        if group_key == "total":
            s = d["ssl_kg_s"]
        elif group_key in ("sand", "fines"):
            col = "sand_mg_l" if group_key == "sand" else "fines_mg_l"
            s = pd.Series(flux_from_concentration(d[col].values, d["discharge_m3s"].values), index=d.index)
            note = "derived: fraction concentration x sample discharge"
        else:
            s = pd.Series(dtype=float)
    else:
        s = pd.Series(dtype=float)
    return s.dropna(), note


def observed_rating_pairs(obs_df: pd.DataFrame, x_key: str, y_key: str, group_key: str,
                          kinds: list[str] | None = None) -> pd.DataFrame:
    """Observed (x, y) at the same record: only discharge and stage are observed hydraulic drivers."""
    if x_key not in ("Q", "Stage"):
        return pd.DataFrame(columns=["x", "y"])
    y, _ = observed_series(obs_df, y_key, group_key, kinds)
    if y.empty:
        return pd.DataFrame(columns=["x", "y"])
    d = obs_df if not kinds else obs_df[obs_df["kind"].isin(kinds)]
    x = d["discharge_m3s"] if x_key == "Q" else d["stage_elev_m"]
    out = pd.DataFrame({"x": x, "y": y}).dropna()
    return out
