"""Model-side data service: turns an opened results file into analysis-ready frames.

Frames use canonical SI units (see :mod:`sediment.units`).  Display conversion happens at the
plot/export layer so analysis never mixes unit systems.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.exceptions import AnalysisError
from ras.hdf_reader import RasResults
from ras.hydraulics import HydraulicSeries, read_hydraulics
from ras.sediment import ClassTransport, read_class_transport
from sediment.aggregation import aggregate
from sediment.grain_classes import SedimentGroup, build_groups
from sediment.rouse import RouseConfig
from sediment.units import concentration_from_flux

logger = logging.getLogger(__name__)

FRAME_COLUMNS = ["Q", "Stage", "Velocity", "BedStress", "ShearVelocity", "Temperature", "Conc", "Flux", "dt_days"]


@dataclass
class ModelFrame:
    df: pd.DataFrame
    meta: dict = field(default_factory=dict)

    def between(self, start, end) -> "ModelFrame":
        """Copy restricted to an inclusive date range (either bound may be None)."""
        from analysis.calibration_metrics import filter_date_range
        return ModelFrame(filter_date_range(self.df, start, end), self.meta)


class ModelDataService:
    def __init__(self, res: RasResults, sand_min_mm: float = 0.063, negative_policy: str = "keep",
                 drop_initial_step: bool = True):
        self.res = res
        self.sand_min_mm = sand_min_mm
        self.negative_policy = negative_policy
        self.drop_initial_step = drop_initial_step
        self._lock = threading.RLock()
        self._hyd: dict[int, HydraulicSeries] = {}
        self._trans: dict[tuple, ClassTransport] = {}
        self._frames: dict[tuple, ModelFrame] = {}

    # -- groups --------------------------------------------------------------------------------
    def set_negative_policy(self, policy: str) -> None:
        with self._lock:
            if policy != self.negative_policy:
                self.negative_policy = policy
                self._trans.clear()
                self._frames.clear()

    @property
    def rouse_reason(self) -> str:
        info = self.res.info
        if info.has_class_variable("Rouse #"):
            return ""
        if info.has_variable("Shear Velocity") or info.has_variable("Shear Stress"):
            return ""
        return "needs HEC-RAS 'Rouse #' or shear velocity/stress results, none are stored in this file"

    def groups(self) -> list[SedimentGroup]:
        return build_groups(self.res.info.grain_classes, self.sand_min_mm, not self.rouse_reason, self.rouse_reason)

    def group(self, key: str) -> SedimentGroup:
        for g in self.groups():
            if g.key == key:
                return g
        raise AnalysisError(f"Unknown sediment group '{key}'.")

    # -- cached building blocks ----------------------------------------------------------------
    def hydraulics(self, xs_index: int) -> HydraulicSeries:
        with self._lock:
            if xs_index not in self._hyd:
                self._hyd[xs_index] = read_hydraulics(self.res, xs_index)
            return self._hyd[xs_index]

    def transport(self, xs_index: int, cfg: RouseConfig) -> ClassTransport:
        key = (xs_index, cfg.source, cfg.kappa, cfg.ferguson_c1, cfg.ferguson_c2)
        with self._lock:
            if key not in self._trans:
                self._trans[key] = read_class_transport(
                    self.res, xs_index, self.hydraulics(xs_index), cfg, self.negative_policy, self.drop_initial_step)
            return self._trans[key]

    # -- public --------------------------------------------------------------------------------
    def frame(self, xs_index: int, group_key: str, cfg: RouseConfig) -> ModelFrame:
        key = (xs_index, group_key, cfg.key())
        with self._lock:
            if key in self._frames:
                return self._frames[key]
        hyd = self.hydraulics(xs_index)
        tr = self.transport(xs_index, cfg)
        group = self.group(group_key)
        if group.kind == "rouse" and tr.rouse is None:
            raise AnalysisError(f"{group.label} is unavailable: {self.rouse_reason or 'Rouse numbers could not be computed'}.")
        flux = aggregate(tr.flux_kg_s, tr.class_indices, group, tr.rouse, cfg)
        conc = aggregate(tr.conc_mg_l, tr.class_indices, group, tr.rouse, cfg)
        times = self.res.info.times
        dt = np.concatenate([[np.nan], self.res.info.timestep_days()])
        nan = np.full(len(times), np.nan)
        df = pd.DataFrame({
            "Q": hyd.discharge,
            "Stage": hyd.stage if hyd.stage is not None else nan,
            "Velocity": hyd.velocity if hyd.velocity is not None else nan,
            "BedStress": hyd.shear_stress if hyd.shear_stress is not None else nan,
            "ShearVelocity": hyd.shear_velocity if hyd.shear_velocity is not None else nan,
            "Temperature": hyd.temperature if hyd.temperature is not None else nan,
            "Conc": conc, "Flux": flux, "dt_days": dt,
        }, index=pd.DatetimeIndex(times, name="DateTime"))
        xs = self.res.info.xs[xs_index]
        info = self.res.info
        if group.kind == "static":
            members = [c for c in info.grain_classes if c.index in group.class_indices]
        else:
            members = list(info.grain_classes)
        meta = {
            "source_hdf": info.path, "hec_ras_version": info.hec_version, "plan": info.plan_id,
            "plan_name": info.plan_name, "river": xs.river, "reach": xs.reach, "cross_section": xs.station,
            "xs_label": xs.label, "xs_index": xs_index, "sediment_group": group_key,
            "sediment_group_label": group.label, "group_estimated": group.estimated,
            "group_description": group.description, "classes": [f"{c.name} ({c.d_rep_mm:.3g} mm)" for c in members],
            "provenance": {**hyd.provenance, **tr.provenance}, "integrity": tr.integrity,
            "negative_concentrations": tr.negatives, "negative_policy": self.negative_policy,
            "warnings": list(dict.fromkeys(hyd.warnings + tr.warnings)),
            "rouse": {"kappa": cfg.kappa, "bed_min": cfg.bed_min, "susp_max": cfg.susp_max, "source": tr.rouse_source},
        }
        mf = ModelFrame(df, meta)
        with self._lock:
            self._frames[key] = mf
        return mf

    def class_flux_frame(self, xs_index: int, cfg: RouseConfig) -> pd.DataFrame:
        """Per-class flux (kg/s) with class-name columns, for the contribution plot."""
        tr = self.transport(xs_index, cfg)
        names = {c.index: c.name for c in self.res.info.grain_classes}
        return pd.DataFrame(tr.flux_kg_s, index=pd.DatetimeIndex(self.res.info.times, name="DateTime"),
                            columns=[names[k] for k in tr.class_indices])

    def total_reported(self, xs_index: int, cfg: RouseConfig) -> pd.Series | None:
        tr = self.transport(xs_index, cfg)
        if tr.reported_total_flux_kg_s is None:
            return None
        return pd.Series(tr.reported_total_flux_kg_s, index=pd.DatetimeIndex(self.res.info.times, name="DateTime"),
                         name="ReportedTotalFlux")

    def rouse_table(self, xs_index: int, cfg: RouseConfig) -> pd.DataFrame:
        """Median Rouse number per class (for display)."""
        tr = self.transport(xs_index, cfg)
        if tr.rouse is None:
            return pd.DataFrame()
        rows = []
        for j, k in enumerate(tr.class_indices):
            c = self.res.info.grain_classes[k - 1]
            p = tr.rouse[:, j]
            p = p[np.isfinite(p)]
            rows.append({"Class": c.name, "D_mm": c.d_rep_mm,
                         "Rouse_median": float(np.median(p)) if p.size else np.nan,
                         "Rouse_p10": float(np.percentile(p, 10)) if p.size else np.nan,
                         "Rouse_p90": float(np.percentile(p, 90)) if p.size else np.nan})
        return pd.DataFrame(rows)

    def concentration_from_flux_check(self, mf: ModelFrame) -> np.ndarray:
        """Re-derive concentration from flux/Q for verification (should equal ``Conc``)."""
        return concentration_from_flux(mf.df["Flux"].values, mf.df["Q"].values)
