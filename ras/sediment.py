"""Per-grain-class sediment transport at one cross section.

What is read directly from HEC-RAS and what is derived
------------------------------------------------------
* ``Sediment Concentration k``  (mg/L, per class)      -> read
* ``Sediment Discharge``        (tons/day, TOTAL only)  -> read (used only as an integrity check)
* per-class mass flux           = C_k * Q * 0.0026969   -> DERIVED (HEC-RAS stores no per-class flux)
* ``Rouse # k`` / ``Fall Velocity k``                   -> read; computed here only if absent/requested

Negative values
---------------
HEC-RAS can write *negative* per-class concentrations (numerical under-shoot of the implicit
advection solver, seen in the cohesive classes downstream of the Old River Control Complex in the
template model).  HEC-RAS's reported total includes them, so the default policy ``keep`` retains the
values (class sums then reconcile with the reported total) and reports the extent of the problem.
``nan`` / ``zero`` are explicit user options for display purposes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from core.exceptions import MissingVariableError
from ras import variable_names as V
from ras.hdf_reader import RasResults
from ras.hydraulics import HydraulicSeries, sanitize, result_unit
from sediment.rouse import RouseConfig, rouse_number, settling_velocity
from sediment.units import SECONDS_PER_DAY, KG_PER_LB, flux_from_concentration, concentration_from_flux, convert

logger = logging.getLogger(__name__)

INTEGRITY_WARN_REL = 0.01  # >1 % disagreement between independent totals is reported loudly


@dataclass
class ClassTransport:
    class_indices: list[int]
    conc_mg_l: np.ndarray            # (T, K) after negative-value policy
    flux_kg_s: np.ndarray            # (T, K) after negative-value policy
    rouse: np.ndarray | None         # (T, K)
    rouse_source: str                # description
    reported_total_flux_kg_s: np.ndarray | None
    integrity: dict[str, float | str] = field(default_factory=dict)
    negatives: dict[str, tuple[float, float]] = field(default_factory=dict)  # class -> (fraction<0, minimum mg/L)
    provenance: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _apply_policy(a: np.ndarray, policy: str) -> np.ndarray:
    if policy == "nan":
        return np.where(a < 0, np.nan, a)
    if policy == "zero":
        return np.where(a < 0, 0.0, a)
    return a


def read_class_transport(res: RasResults, xs_index: int, hyd: HydraulicSeries, rouse_cfg: RouseConfig,
                         negative_policy: str = "keep", drop_initial_step: bool = True) -> ClassTransport:
    info = res.info
    if negative_policy not in ('keep','nan','zero'):
        raise ValueError('Negative concentration policy must be keep, nan or zero.')
    classes = info.grain_classes
    warnings: list[str] = []
    prov: dict[str, str] = {}
    idx = [c.index for c in classes]
    if not idx:
        raise MissingVariableError("Sediment grain-class metadata could not be located in this HDF file.")

    v_conc = info.layout.variables.get(V.CONCENTRATION)
    if v_conc and all(k in v_conc.class_paths for k in idx):
        conc_raw = np.column_stack([
            convert(sanitize(res.var_column(V.CONCENTRATION, xs_index, k), V.CONCENTRATION, warnings,
                             nonneg=False), result_unit(res,V.CONCENTRATION,'concentration',warnings,k),'mg/L')
            for k in idx])
        prov["concentration"] = f"HEC-RAS output: {v_conc.class_paths[idx[0]].rsplit(' ', 1)[0]} k [{v_conc.units}]"
        flux_raw = flux_from_concentration(conc_raw, hyd.discharge[:, None])
        prov["flux"] = "DERIVED: C_k x Q (HEC-RAS stores per-class concentration, not per-class mass flux)"
    elif info.has_class_variable(V.VOL_OUT) and np.all([np.isfinite(c.unit_weight_lb_ft3) for c in classes]):
        flux_raw, conc_raw = _flux_from_vol_out(res, xs_index, classes, hyd, warnings)
        prov["flux"] = "DERIVED: Vol Out_k x class unit weight / dt (per-class concentration not stored)"
        prov["concentration"] = "DERIVED: flux / Q"
    else:
        raise MissingVariableError(
            "Per-class sediment concentration (or volume-out) results are not stored in this HDF file.")

    if drop_initial_step and flux_raw.shape[0] > 1:
        if np.isfinite(conc_raw[0]).all() and (conc_raw[0] == 0).all() and np.any(
                np.isfinite(conc_raw[1:]) & (conc_raw[1:] != 0)):
            conc_raw[0, :] = np.nan
            flux_raw[0, :] = np.nan
            warnings.append("First output step is the zero-sediment initial condition; sediment values set to NaN.")

    negatives = {}
    for j, c in enumerate(classes):
        col = conc_raw[:, j]
        fin = np.isfinite(col)
        if fin.any() and (col[fin] < 0).any():
            negatives[c.name] = (float((col[fin] < 0).mean()), float(col[fin].min()))
    if negatives:
        worst = ", ".join(f"{k} {f:.0%} (min {m:.2g} mg/L)" for k, (f, m) in
                          sorted(negatives.items(), key=lambda kv: -kv[1][0])[:5])
        policy_text = {"keep": "kept as reported by HEC-RAS (class sums reconcile with the reported total)",
                       "nan": "set to NaN", "zero": "set to zero"}[negative_policy]
        warnings.append(f"HEC-RAS wrote NEGATIVE concentrations at this cross section [{worst}]; {policy_text}. "
                        "This is a numerical artefact of the model, not physical transport.")

    reported = None
    integrity: dict[str, float | str] = {}
    if info.has_variable(V.SEDIMENT_DISCHARGE) and info.layout.variables[V.SEDIMENT_DISCHARGE].total_path:
        raw = sanitize(res.var_column(V.SEDIMENT_DISCHARGE, xs_index), V.SEDIMENT_DISCHARGE, warnings, nonneg=False)
        unit = result_unit(res,V.SEDIMENT_DISCHARGE,'mass_flux',warnings)
        reported = convert(raw, unit, 'kg/s')
        prov["reported_total_flux"] = f"HEC-RAS output: {info.layout.variables[V.SEDIMENT_DISCHARGE].total_path} [{unit}]"
        integrity.update(_integrity_vs_reported(flux_raw, reported, warnings))
    if info.has_class_variable(V.VOL_OUT):
        integrity.update(_integrity_vs_vol_out(res, xs_index, classes, flux_raw, info.timestep_days()))

    conc = _apply_policy(conc_raw, negative_policy)
    flux = flux_raw.copy()
    if negative_policy in ('nan','zero'):
        flux[conc_raw < 0] = np.nan if negative_policy == 'nan' else 0.0

    rouse, rsrc = _rouse(res, xs_index, classes, hyd, rouse_cfg, warnings)
    prov["rouse"] = rsrc
    return ClassTransport(idx, conc, flux, rouse, rsrc, reported, integrity, negatives, prov, warnings)


def _flux_from_vol_out(res, xs_index, classes, hyd, warnings):
    dt_days = np.concatenate([[np.nan], res.info.timestep_days()])
    cols = []
    for c in classes:
        vol = sanitize(res.var_column(V.VOL_OUT, xs_index, c.index), V.VOL_OUT, warnings, nonneg=False)
        vol = convert(vol,result_unit(res,V.VOL_OUT,'volume',warnings,c.index),'ft3')
        cols.append(vol * c.unit_weight_lb_ft3 * KG_PER_LB / (dt_days * SECONDS_PER_DAY))
    flux = np.column_stack(cols)
    conc = concentration_from_flux(flux,hyd.discharge[:,None])
    return flux, conc


def _integrity_vs_reported(flux_kg_s: np.ndarray, reported_kg_s: np.ndarray, warnings: list[str]) -> dict:
    tot = flux_kg_s.sum(axis=1)
    scale = np.nanmax(np.abs(reported_kg_s)) if np.isfinite(reported_kg_s).any() else 0.0
    valid = np.isfinite(reported_kg_s) & (np.abs(reported_kg_s) > 1e-6 * max(scale, 1e-12)) & \
        np.isfinite(flux_kg_s).all(axis=1)
    if valid.sum() == 0:
        return {"sum_classes_vs_reported_n": 0}
    rel = (tot[valid] - reported_kg_s[valid]) / np.abs(reported_kg_s[valid])
    out = {"sum_classes_vs_reported_n": int(valid.sum()),
           "sum_classes_vs_reported_median_rel": float(np.median(rel)),
           "sum_classes_vs_reported_max_abs_rel": float(np.max(np.abs(rel)))}
    if out["sum_classes_vs_reported_max_abs_rel"] > INTEGRITY_WARN_REL:
        msg = (f"INTEGRITY: sum of class fluxes differs from HEC-RAS 'Sediment Discharge' by up to "
               f"{out['sum_classes_vs_reported_max_abs_rel']:.1%}. Investigate before using results.")
        warnings.append(msg)
        logger.error(msg)
    return out


def _integrity_vs_vol_out(res, xs_index, classes, flux_kg_s, dt_days) -> dict:
    """Independent check: sum_k VolOut_k * UnitWeight_k / dt vs sum_k C_k Q (median ratio)."""
    if not all(np.isfinite(c.unit_weight_lb_ft3) for c in classes) or len(dt_days) == 0:
        return {}
    try:
        total_mass = np.zeros(res.info.n_steps)
        for c in classes:
            vol = res.var_column(V.VOL_OUT, xs_index, c.index)
            vol = convert(vol,result_unit(res,V.VOL_OUT,'volume',[],c.index),'ft3')
            total_mass += vol * c.unit_weight_lb_ft3 * KG_PER_LB
        flux2 = total_mass[1:] / (dt_days * SECONDS_PER_DAY)
    except MissingVariableError:
        return {}
    f1 = flux_kg_s.sum(axis=1)[1:]
    ok = np.isfinite(f1) & np.isfinite(flux2) & (np.abs(f1) > 0) & (np.abs(flux2) > 0)
    if ok.sum() == 0:
        return {}
    ratio = flux2[ok] / f1[ok]
    return {"vol_out_unit_weight_vs_conc_flux_median_ratio": float(np.median(ratio)),
            "vol_out_unit_weight_vs_conc_flux_p05_p95": f"{np.percentile(ratio, 5):.5f}..{np.percentile(ratio, 95):.5f}"}


def _rouse(res, xs_index, classes, hyd, cfg: RouseConfig, warnings):
    idx = [c.index for c in classes]
    info = res.info
    if cfg.source == "hecras" and info.has_class_variable(V.ROUSE) and \
            all(k in info.layout.variables[V.ROUSE].class_paths for k in idx):
        cols = []
        for k in idx:
            r = res.var_column(V.ROUSE, xs_index, k)
            cols.append(np.where(np.isfinite(r) & (r >= 0) & (r < 1e9), r, np.nan))
        return np.column_stack(cols), f"HEC-RAS output: '{V.ROUSE}' per class (kappa=0.4 verified)"
    if hyd.shear_velocity is None:
        warnings.append("Rouse number unavailable: no shear velocity/stress. Suspended/bed-load estimates disabled.")
        return None, "unavailable (no shear velocity)"
    d = np.array([c.d_rep_mm for c in classes])
    if not np.all(np.isfinite(d)):
        warnings.append("Rouse number unavailable: grain diameters unknown.")
        return None, "unavailable (unknown diameters)"
    sg = np.array([c.specific_gravity for c in classes])
    temp = hyd.temperature if hyd.temperature is not None else np.full(len(hyd.times), 20.0)
    if hyd.temperature is None:
        warnings.append('Computed Rouse numbers assume 20 degC because water temperature is not stored.')
    elif (~np.isfinite(temp)).any():
        warnings.append('Computed Rouse numbers assume 20 degC where stored water temperature is missing.')
    temp = np.where(np.isfinite(temp), temp, 20.0)
    ws = settling_velocity(d[None, :], temp[:, None], sg[None, :], cfg.ferguson_c1, cfg.ferguson_c2)
    p = rouse_number(ws, hyd.shear_velocity[:, None], cfg.kappa)
    return p, (f"DERIVED: P = ws/(kappa u*), ws Ferguson & Church (2004) C1={cfg.ferguson_c1:g} C2={cfg.ferguson_c2:g}, "
               f"kappa={cfg.kappa:g}, u* from {hyd.provenance.get('shear_velocity', 'shear stress')}")
