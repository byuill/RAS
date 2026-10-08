"""Plain data containers describing an opened HEC-RAS sediment results file."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sediment.grain_classes import GrainClass


@dataclass(frozen=True)
class CrossSection:
    index: int                 # column index in the HDF time-series datasets
    river: str
    reach: str
    station: str               # RS exactly as stored in the HDF
    name: str = ""
    station_value: float = float("nan")
    x: float = float("nan")    # projected centroid of XS cut line (model coordinates)
    y: float = float("nan")
    lon: float = float("nan")
    lat: float = float("nan")

    @property
    def label(self) -> str:
        return f"{self.river} | {self.reach} | {self.station}"


@dataclass
class VariableInfo:
    name: str
    units: str
    total_path: str | None
    class_paths: dict[int, str]
    grain_class_attr: str = ""
    shape: tuple = ()

    @property
    def per_class(self) -> bool:
        return bool(self.class_paths)


@dataclass
class RasLayout:
    """HDF paths used for this file.  All version-dependent knowledge is confined to discovery."""
    xs_ts_group: str
    time_path: str
    time_stamp_path: str | None
    xs_attr_path: str | None
    geometry_xs_attr_path: str | None
    geometry_polyline_info_path: str | None
    geometry_polyline_points_path: str | None
    grain_names_path: str | None
    grain_bounds_path: str | None
    density_path: str | None
    cohesive_path: str | None
    plan_info_path: str | None
    variables: dict[str, VariableInfo] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def path_table(self) -> dict[str, str | None]:
        return {
            "XS time-series group": self.xs_ts_group, "Time": self.time_path,
            "Time date stamp": self.time_stamp_path, "XS attributes": self.xs_attr_path,
            "Geometry XS attributes": self.geometry_xs_attr_path,
            "XS polyline info": self.geometry_polyline_info_path,
            "XS polyline points": self.geometry_polyline_points_path,
            "Grain class names": self.grain_names_path, "Grain class bounds": self.grain_bounds_path,
            "Grain density data": self.density_path, "Cohesive flags": self.cohesive_path,
            "Plan information": self.plan_info_path,
        }


@dataclass
class RasModelInfo:
    path: str
    hec_version: str
    units_system: str
    plan_file: str            # e.g. "p01"
    plan_name: str
    plan_title: str
    short_id: str
    project_title: str
    geometry_title: str
    flow_title: str
    sim_start: str
    sim_end: str
    times: pd.DatetimeIndex
    xs: list[CrossSection]
    grain_classes: list[GrainClass]
    layout: RasLayout
    warnings: list[str] = field(default_factory=list)
    projection_wkt: str | None = None

    @property
    def n_steps(self) -> int:
        return len(self.times)

    @property
    def plan_id(self) -> str:
        return self.plan_file or self.short_id

    def has_variable(self, name: str) -> bool:
        return name in self.layout.variables

    def has_class_variable(self, name: str) -> bool:
        v = self.layout.variables.get(name)
        return bool(v and v.per_class)

    def timestep_days(self) -> np.ndarray:
        """Seconds between successive output times, expressed in days (length n_steps-1)."""
        return np.diff(self.times.asi8).astype(float) / (86400.0 * 1e9)
