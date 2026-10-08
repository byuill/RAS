"""Shared plot styling, display-unit conversion and data containers for pinned datasets."""
from __future__ import annotations

import itertools
import copy
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from config.settings import AppSettings
from sediment import units as U

PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22"]
CURRENT_COLOR = "#000000"
SECONDARY_COLOR = "#7a7a7a"
OBS_COLOR = "#d95f02"
SEASON_COLORS = {"DJF": "#3b78c4", "MAM": "#4dac26", "JJA": "#e66101", "SON": "#8e5fb0"}
LIMB_COLORS = {"Rising": "#d9534f", "Falling": "#0275d8", "Other": "#9a9a9a"}
HYDRO_COLORS = {"FIRST_RISING": "#e8a838", "Rising": "#d9534f", "Falling": "#0275d8",
                "BEFORE_PEAK_OTHER": "#5cb85c", "AFTER_PEAK_OTHER": "#9b59b6", "Other": "#9a9a9a"}

QUANTITY_UNIT_KEY = {"discharge": "discharge", "length": "length", "velocity": "velocity",
                     "shear_stress": "shear_stress", "concentration": "concentration", "mass_flux": "mass_flux",
                     "mass": "mass", "diameter": "diameter", "temperature": "temperature"}


class DisplayUnits:
    """Canonical -> display conversion, driven by :class:`AppSettings`."""

    def __init__(self, settings: AppSettings):
        self.s = settings

    def unit(self, quantity: str) -> str:
        if quantity == "mass":
            return {"tons/day": "tons", "tonnes/day": "tonnes", "kg/s": "kg", "tons/year": "tons",
                    "tonnes/year": "tonnes"}.get(self.s.display_flux_unit, "tonnes")
        if quantity == "dimensionless":
            return "1"
        return self.s.display_unit(quantity)

    def label(self, quantity: str) -> str:
        return U.unit_label(self.unit(quantity))

    def convert(self, values, quantity: str):
        if quantity == "dimensionless":
            return values
        return U.from_canonical(values, quantity, self.unit(quantity))


@dataclass(frozen=True)
class SeriesData:
    """Immutable snapshot of one plotted curve (canonical units) so pins are never silently modified."""
    x: np.ndarray
    y: np.ndarray
    x_quantity: str           # 'time' or a quantity key
    y_quantity: str
    label: str
    role: str = "model"       # model | model_secondary | obs | fit
    meta: dict = field(default_factory=dict)


@dataclass
class PinnedDataset:
    id: int
    label: str
    view: str                 # timeseries | rating
    series: list[SeriesData]
    meta: dict
    color: str
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class PinManager:
    """Holds pinned datasets (plain objects, not Matplotlib artists)."""

    def __init__(self):
        self._items: list[PinnedDataset] = []
        self._ids = itertools.count(1)

    def pin(self, label: str, view: str, series: list[SeriesData], meta: dict) -> PinnedDataset:
        used = {p.color for p in self._items}
        color = next((c for c in PALETTE if c not in used), PALETTE[len(self._items) % len(PALETTE)])
        snapshots = []
        for s in series:
            x,y = np.array(s.x,copy=True),np.array(s.y,copy=True)
            x.setflags(write=False); y.setflags(write=False)
            snapshots.append(SeriesData(x,y,s.x_quantity,s.y_quantity,s.label,s.role,copy.deepcopy(s.meta)))
        item = PinnedDataset(next(self._ids), label, view, snapshots, copy.deepcopy(meta), color)
        self._items.append(item)
        return item

    def items(self, view: str | None = None) -> list[PinnedDataset]:
        return [p for p in self._items if view is None or p.view == view]

    def remove(self, pin_id: int) -> None:
        self._items = [p for p in self._items if p.id != pin_id]

    def clear(self, view: str | None = None) -> None:
        self._items = [p for p in self._items if view is not None and p.view != view]

    def __len__(self) -> int:
        return len(self._items)
