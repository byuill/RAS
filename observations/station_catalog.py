"""Observation station catalog (YAML) - easy to extend by editing stations.yaml / stations_user.yaml."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from config.settings import STATIONS_FILE, USER_STATIONS_FILE
from core.exceptions import ObservationError

logger = logging.getLogger(__name__)


@dataclass
class Station:
    id: str
    name: str
    short_name: str
    agency: str
    site_no: str = ""
    river: str = "Mississippi"
    river_mile: float | None = None
    river_mile_basis: str = ""
    lat: float | None = None
    lon: float | None = None
    parameters: dict[str, list[str]] = field(default_factory=dict)  # key -> [first_date, last_date] (verified)
    cwms: dict = field(default_factory=dict)
    gage_zero_elev_ft: float | None = None
    gage_zero_datum: str = ""
    ngvd29_to_navd88_shift_ft: float | None = None
    legacy_ras_station: str = ""
    notes: str = ""
    endpoints: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.short_name} ({self.agency} {self.site_no})" if self.site_no else self.short_name

    def supports(self, parameter: str) -> bool:
        """Parameter is offered if verified in the catalog or (CWMS) configured."""
        if parameter in self.parameters:
            return True
        if parameter == "cwms_flow":
            return "flow" in self.cwms
        if parameter == "cwms_stage":
            return "stage" in self.cwms
        return False


_ENDPOINTS = {
    "usgs_dv": "https://waterservices.usgs.gov/nwis/dv/",
    "usgs_wqp": "https://www.waterqualitydata.us/data/Result/search",
    "cwms": "https://cwms-data.usace.army.mil/cwms-data/timeseries",
}


def _to_station(d: dict) -> Station:
    try:
        params = {k: [str(x) for x in (v or [])] for k, v in (d.get("parameters") or {}).items()}
        st = Station(
            id=str(d["id"]), name=d["name"], short_name=d.get("short_name", d["name"]), agency=d.get("agency", "USGS"),
            site_no=str(d.get("site_no", "")), river=d.get("river", "Mississippi"),
            river_mile=d.get("river_mile"), river_mile_basis=d.get("river_mile_basis", ""),
            lat=d.get("lat"), lon=d.get("lon"), parameters=params, cwms=d.get("cwms") or {},
            gage_zero_elev_ft=d.get("gage_zero_elev_ft"), gage_zero_datum=d.get("gage_zero_datum", ""),
            ngvd29_to_navd88_shift_ft=d.get("ngvd29_to_navd88_shift_ft"),
            legacy_ras_station=str(d.get("legacy_ras_station", "") or ""), notes=d.get("notes", ""))
    except KeyError as exc:
        raise ObservationError(f"Station entry is missing required field {exc}: {d}") from exc
    st.endpoints = dict(_ENDPOINTS)
    return st


class StationCatalog:
    def __init__(self, stations: list[Station]):
        self._stations = {s.id: s for s in stations}

    @classmethod
    def load(cls, path: Path = STATIONS_FILE, user_path: Path = USER_STATIONS_FILE) -> "StationCatalog":
        stations: dict[str, Station] = {}
        for p in (path, user_path):
            if not p.exists():
                continue
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise ObservationError(f"Station catalog {p.name} could not be read: {exc}") from exc
            for d in data.get("stations", []):
                s = _to_station(d)
                stations[s.id] = s
        logger.info("Loaded %d observation stations", len(stations))
        return cls(list(stations.values()))

    def all(self) -> list[Station]:
        return list(self._stations.values())

    def get(self, station_id: str) -> Station:
        try:
            return self._stations[station_id]
        except KeyError as exc:
            raise ObservationError(f"Unknown station '{station_id}'.") from exc

    def __len__(self) -> int:
        return len(self._stations)
