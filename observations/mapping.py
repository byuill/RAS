"""Observation station -> HEC-RAS cross-section mapping (automatic nearest + persisted manual override)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config.settings import MAPPINGS_FILE
from core.exceptions import WorkbenchError
from observations.station_catalog import Station
from ras.geo import haversine_km
from ras.model import CrossSection

logger = logging.getLogger(__name__)

MAX_AUTO_DISTANCE_KM = 10.0


@dataclass
class XsMatch:
    xs: CrossSection | None
    distance_km: float | None
    source: str             # auto | manual | none
    message: str = ""


def suggest_cross_section(station: Station, xs_list: list[CrossSection], max_km: float = MAX_AUTO_DISTANCE_KM) -> XsMatch:
    """Nearest cross section on the same river by great-circle distance of the XS cut-line centroid.

    Returns ``xs=None`` when the nearest section is farther than ``max_km`` (gauge outside the model domain)
    or no cross-section coordinates are available; similarly-named locations are never assumed colocated."""
    if station.lat is None or station.lon is None:
        return XsMatch(None, None, "none", "Station has no coordinates.")
    cand = [x for x in xs_list if np.isfinite(x.lat) and x.river.lower() == station.river.lower()]
    if not cand:
        return XsMatch(None, None, "none", "No cross-section coordinates available for automatic mapping.")
    d = np.array([haversine_km(station.lon, station.lat, x.lon, x.lat) for x in cand])
    j = int(np.argmin(d))
    if d[j] > max_km:
        return XsMatch(None, float(d[j]), "none",
                       f"Nearest cross section ({cand[j].label}) is {d[j]:.1f} km away - outside the model domain; "
                       "map manually if appropriate.")
    return XsMatch(cand[j], float(d[j]), "auto", f"Nearest cross section, {d[j]:.2f} km from the gauge.")


class MappingStore:
    """Manual overrides persisted as JSON: {geometry_key: {station_id: {"xs": "River|Reach|RS", ...}}}."""

    def __init__(self, path: Path = MAPPINGS_FILE):
        self.path = path
        self._data: dict = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("Could not read station mappings %s: %s", path, exc)

    def get(self, geometry_key: str, station_id: str) -> str | None:
        return self._data.get(geometry_key, {}).get(station_id, {}).get("xs")

    def set(self, geometry_key: str, station_id: str, xs_key: str, note: str = "") -> None:
        self._data.setdefault(geometry_key, {})[station_id] = {"xs": xs_key, "note": note}
        self._save()

    def clear(self, geometry_key: str, station_id: str) -> None:
        self._data.get(geometry_key, {}).pop(station_id, None)
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError as exc:
            raise WorkbenchError(f"Could not save station mapping to {self.path}: {exc}") from exc


def xs_key(xs: CrossSection) -> str:
    return f"{xs.river}|{xs.reach}|{xs.station}"


def resolve_mapping(station: Station, xs_list: list[CrossSection], store: MappingStore, geometry_key: str) -> XsMatch:
    """Manual mapping wins; otherwise automatic nearest."""
    saved = store.get(geometry_key, station.id)
    if saved:
        for x in xs_list:
            if xs_key(x) == saved:
                dist = float(haversine_km(station.lon, station.lat, x.lon, x.lat)) if (
                    station.lat is not None and np.isfinite(x.lat)) else None
                return XsMatch(x, dist, "manual", "User-defined mapping.")
        logger.warning("Saved mapping %s for %s is not in this model", saved, station.id)
    return suggest_cross_section(station, xs_list)
