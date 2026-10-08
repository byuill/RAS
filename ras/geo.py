"""Minimal Albers Equal-Area Conic projection (ellipsoidal, Snyder 1987 pp. 98-103).

Used to place HEC-RAS cross sections (model projection read from the project ``.prj``) on a
lat/lon basis so gauges can be mapped to the nearest cross section without ``pyproj``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from sediment.units import M_PER_FT

# GRS80 (NAD83)
_A = 6378137.0
_F = 1.0 / 298.257222101
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)

US_SURVEY_FOOT_M = 0.3048006096012192

# USA Contiguous Albers Equal Area Conic (USGS version): default for LMR models
DEFAULT_ALBERS_WKT = (
    'PROJCS["USA_Contiguous_Albers_Equal_Area_Conic_USGS_version",GEOGCS["GCS_North_American_1983",'
    'DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],PROJECTION["Albers"],PARAMETER["False_Easting",0.0],'
    'PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-96.0],PARAMETER["Standard_Parallel_1",29.5],'
    'PARAMETER["Standard_Parallel_2",45.5],PARAMETER["Latitude_Of_Origin",23.0],UNIT["Foot_US",0.3048006096012192]]'
)


def _q(phi: float) -> float:
    s = math.sin(phi)
    return (1 - _E2) * (s / (1 - _E2 * s * s) - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s)))


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - _E2 * s * s)


@dataclass(frozen=True)
class AlbersProjection:
    lat1: float
    lat2: float
    lat0: float
    lon0: float
    false_easting: float = 0.0
    false_northing: float = 0.0
    unit_m: float = 1.0

    def _consts(self):
        p1, p2, p0 = map(math.radians, (self.lat1, self.lat2, self.lat0))
        n = (_m(p1) ** 2 - _m(p2) ** 2) / (_q(p2) - _q(p1))
        c = _m(p1) ** 2 + n * _q(p1)
        rho0 = _A * math.sqrt(c - n * _q(p0)) / n
        return n, c, rho0

    def forward(self, lon, lat):
        """lon/lat (deg) -> projected x/y in the projection's own length unit."""
        n, c, rho0 = self._consts()
        lam = np.radians(np.asarray(lon, dtype=float))
        phi = np.radians(np.asarray(lat, dtype=float))
        s = np.sin(phi)
        q = (1 - _E2) * (s / (1 - _E2 * s * s) - (1 / (2 * _E)) * np.log((1 - _E * s) / (1 + _E * s)))
        rho = _A * np.sqrt(c - n * q) / n
        theta = n * (lam - math.radians(self.lon0))
        x = rho * np.sin(theta)
        y = rho0 - rho * np.cos(theta)
        return (x / self.unit_m + self.false_easting, y / self.unit_m + self.false_northing)

    def inverse(self, x, y):
        """Projected x/y (own unit) -> lon/lat (deg)."""
        n, c, rho0 = self._consts()
        xm = (np.asarray(x, dtype=float) - self.false_easting) * self.unit_m
        ym = (np.asarray(y, dtype=float) - self.false_northing) * self.unit_m
        dy = rho0 - ym
        rho = np.sqrt(xm ** 2 + dy ** 2)
        q = (c - (rho * n / _A) ** 2) / n
        theta = np.arctan2(xm, dy)
        lam = math.radians(self.lon0) + theta / n
        phi = np.arcsin(np.clip(q / 2.0, -1, 1))
        for _ in range(12):
            s = np.sin(phi)
            corr = ((1 - _E2 * s * s) ** 2 / (2 * np.cos(phi))) * (
                q / (1 - _E2) - s / (1 - _E2 * s * s) + (1 / (2 * _E)) * np.log((1 - _E * s) / (1 + _E * s)))
            phi = phi + corr
        return np.degrees(lam), np.degrees(phi)


def parse_albers_wkt(wkt: str) -> AlbersProjection | None:
    """Parse an ESRI-style WKT string; returns None if the projection is not Albers."""
    if not wkt or 'PROJECTION["Albers"' not in wkt and "Albers_Conic_Equal_Area" not in wkt:
        return None

    def par(name: str, default: float | None = None) -> float:
        m = re.search(rf'PARAMETER\["{name}",\s*([-+0-9.eE]+)\]', wkt, flags=re.I)
        if m:
            return float(m.group(1))
        if default is None:
            raise ValueError(f"WKT is missing parameter {name}")
        return default

    unit = re.findall(r'UNIT\["[^"]+",\s*([-+0-9.eE]+)\]', wkt)
    unit_m = float(unit[-1]) if unit else 1.0
    try:
        return AlbersProjection(
            lat1=par("Standard_Parallel_1"), lat2=par("Standard_Parallel_2"),
            lat0=par("Latitude_Of_Origin"), lon0=par("Central_Meridian"),
            false_easting=par("False_Easting", 0.0), false_northing=par("False_Northing", 0.0),
            unit_m=unit_m)
    except ValueError:
        return None


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


__all__ = ["AlbersProjection", "parse_albers_wkt", "haversine_km", "DEFAULT_ALBERS_WKT", "M_PER_FT"]
