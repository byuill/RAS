"""Hydraulic time series at one cross section, in canonical units, with provenance."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.exceptions import MissingVariableError
from ras import variable_names as V
from ras.hdf_reader import RasResults
from sediment.rouse import RHO_WATER_DEFAULT
from sediment.units import G_ACCEL_SI, convert, to_canonical

logger = logging.getLogger(__name__)

SENTINEL_LOW = -9998.0   # HEC-RAS "undefined" sentinels (-9999, -3.4e38 ...) are all below this
SENTINEL_HIGH = 1e12

NONNEGATIVE = {V.FLOW, V.VELOCITY, V.SHEAR_STRESS, V.SHEAR_VELOCITY, V.CONCENTRATION, V.FALL_VELOCITY}


def sanitize(arr: np.ndarray, name: str, warnings: list[str], nonneg: bool | None = None,
             negative_policy: str = "nan") -> np.ndarray:
    """Replace sentinels / non-physical values with NaN; counts are appended to ``warnings``."""
    a = np.asarray(arr, dtype=float).copy()
    bad = ~np.isfinite(a) | (a <= SENTINEL_LOW) | (a >= SENTINEL_HIGH)
    n_bad = int(bad.sum())
    a[bad] = np.nan
    nonneg = (name in NONNEGATIVE) if nonneg is None else nonneg
    n_neg = 0
    if nonneg and negative_policy in ("nan", "zero"):
        neg = a < 0
        n_neg = int(neg.sum())
        a[neg] = np.nan if negative_policy == "nan" else 0.0
    if n_bad or n_neg:
        what = "NaN" if negative_policy != "zero" else "NaN (sentinels) / 0 (negatives)"
        warnings.append(f"{name}: {n_bad} undefined/sentinel and {n_neg} negative values set to {what}.")
    return a


@dataclass
class HydraulicSeries:
    times: pd.DatetimeIndex
    discharge: np.ndarray            # m3/s
    stage: np.ndarray | None         # m (water-surface elevation, model vertical datum)
    velocity: np.ndarray | None      # m/s
    shear_stress: np.ndarray | None  # Pa
    shear_velocity: np.ndarray | None  # m/s
    temperature: np.ndarray | None   # degC
    provenance: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _read(res: RasResults, name: str, xs_index: int, warnings: list[str], neg_policy: str):
    """Return (canonical values, provenance text) or (None, '') if the variable is absent."""
    if not res.info.has_variable(name) or res.info.layout.variables[name].total_path is None:
        return None, ""
    path = res.variable_path(name)
    units = res.var_units(name)
    raw = sanitize(res.column(path, xs_index), name, warnings, negative_policy=neg_policy)
    return raw, f"HEC-RAS output: {path} [{units or 'dimensionless'}]"


def read_hydraulics(res: RasResults, xs_index: int) -> HydraulicSeries:
    negative_policy = "nan"  # hydraulic quantities are never negative; negative sediment values are handled separately
    warnings: list[str] = []
    prov: dict[str, str] = {}
    info = res.info

    q_raw, p = _read(res, V.FLOW, xs_index, warnings, negative_policy)
    if q_raw is None:
        raise MissingVariableError("Flow discharge is not stored in this HDF file; the tool cannot continue.")
    q = to_canonical(q_raw, res.var_units(V.FLOW) or "cfs")
    prov["discharge"] = p

    def conv(name: str, quantity_default_unit: str):
        raw, pr = _read(res, name, xs_index, warnings, negative_policy)
        if raw is None:
            return None, ""
        return to_canonical(raw, res.var_units(name) or quantity_default_unit), pr

    stage, prov["stage"] = conv(V.WSE, "ft")
    vel, prov["velocity"] = conv(V.VELOCITY, "ft/s")
    ustar, prov["shear_velocity"] = conv(V.SHEAR_VELOCITY, "ft/s")
    temp, prov["temperature"] = conv(V.TEMPERATURE, "degF")
    tau, prov["shear_stress"] = conv(V.SHEAR_STRESS, "lb/ft2")
    if stage is None:
        prov.pop("stage")
        warnings.append("Water-surface elevation is not stored in this file; stage plots are disabled.")
    if vel is None:
        prov.pop("velocity")
        warnings.append("Velocity is not stored in this file; velocity plots are disabled.")

    if tau is None:
        tau, text = _derive_shear_stress(res, xs_index, ustar, warnings, negative_policy)
        if tau is not None:
            prov["shear_stress"] = text
        else:
            prov.pop("shear_stress", None)
            warnings.append("Bed shear stress is neither stored nor derivable; shear-stress options are disabled.")
    if ustar is None and tau is not None:
        ustar = np.sqrt(np.where(tau >= 0, tau, np.nan) / RHO_WATER_DEFAULT)
        prov["shear_velocity"] = f"DERIVED: sqrt(tau_b / rho), rho={RHO_WATER_DEFAULT:g} kg/m3"
    if ustar is None:
        prov.pop("shear_velocity", None)
    if temp is None:
        prov.pop("temperature", None)

    return HydraulicSeries(info.times, q, stage, vel, tau, ustar, temp, prov, warnings)


def _derive_shear_stress(res: RasResults, xs_index: int, ustar_si, warnings, neg_policy):
    """Fallbacks (clearly labelled DERIVED): rho*u*^2, else gamma*R*S."""
    if ustar_si is not None:
        return RHO_WATER_DEFAULT * ustar_si ** 2, f"DERIVED: rho u*^2 with rho={RHO_WATER_DEFAULT:g} kg/m3"
    r_raw, _ = _read(res, V.HYDRAULIC_RADIUS, xs_index, warnings, neg_policy)
    s_raw, _ = _read(res, V.ENERGY_SLOPE, xs_index, warnings, neg_policy)
    if r_raw is not None and s_raw is not None:
        r = to_canonical(r_raw, res.var_units(V.HYDRAULIC_RADIUS) or "ft")
        gamma = RHO_WATER_DEFAULT * G_ACCEL_SI
        return gamma * r * np.where(s_raw >= 0, s_raw, np.nan), "DERIVED: gamma R S (hydraulic radius x slope)"
    return None, ""
