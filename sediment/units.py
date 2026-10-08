"""Centralised unit handling.

Canonical internal units (SI-based):

=============  ==========  =====================================
quantity       canonical   notes
=============  ==========  =====================================
discharge      m3/s
length         m           stage / elevation / depth
velocity       m/s
shear_stress   Pa
concentration  mg/L        (= g/m3)
mass_flux      kg/s
mass           kg
diameter       mm
temperature    degC
=============  ==========  =====================================

All conversion factors live in this module.  A "ton" in HEC-RAS US Customary output is the
short ton (2000 lb); metric tons are written ``tonnes``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from core.exceptions import UnitError

# Exact definitions
M_PER_FT = 0.3048
M3_PER_FT3 = M_PER_FT ** 3
M3_PER_CFS = M3_PER_FT3  # 1 cfs = 1 ft3/s
KG_PER_LB = 0.45359237
KG_PER_SHORT_TON = 2000.0 * KG_PER_LB  # 907.18474
KG_PER_TONNE = 1000.0
G_ACCEL_SI = 9.80665  # m/s2
N_PER_LBF = 4.4482216152605
PA_PER_LBF_FT2 = N_PER_LBF / (M_PER_FT ** 2)
SECONDS_PER_DAY = 86400.0
DAYS_PER_YEAR = 365.25  # Julian year, used only for the "per year" display units


@dataclass(frozen=True)
class UnitDef:
    name: str          # canonical key used throughout the code
    quantity: str
    to_canonical: float  # value_canonical = value * to_canonical + offset
    offset: float = 0.0
    label: str = ""    # display label


QUANTITIES = ("discharge", "length", "velocity", "shear_stress", "concentration",
              "mass_flux", "mass", "diameter", "temperature", "dimensionless")

CANONICAL = {
    "discharge": "m3/s", "length": "m", "velocity": "m/s", "shear_stress": "Pa",
    "concentration": "mg/L", "mass_flux": "kg/s", "mass": "kg", "diameter": "mm",
    "temperature": "degC", "dimensionless": "1",
}

_DEFS: dict[str, UnitDef] = {}


def _add(name: str, quantity: str, factor: float, offset: float = 0.0, label: str | None = None) -> None:
    _DEFS[name] = UnitDef(name, quantity, factor, offset, label or name)


_add("m3/s", "discharge", 1.0, label="m\u00b3/s")
_add("cfs", "discharge", M3_PER_CFS, label="cfs")
_add("m", "length", 1.0)
_add("ft", "length", M_PER_FT)
_add("m/s", "velocity", 1.0)
_add("ft/s", "velocity", M_PER_FT)
_add("Pa", "shear_stress", 1.0)
_add("N/m2", "shear_stress", 1.0, label="N/m\u00b2")
_add("lb/ft2", "shear_stress", PA_PER_LBF_FT2, label="lb/ft\u00b2")
_add("mg/L", "concentration", 1.0)
_add("g/L", "concentration", 1000.0)
_add("kg/m3", "concentration", 1000.0, label="kg/m\u00b3")
_add("ppm", "concentration", 1.0)
_add("kg/s", "mass_flux", 1.0)
_add("tonnes/day", "mass_flux", KG_PER_TONNE / SECONDS_PER_DAY, label="tonnes/day (metric)")
_add("tons/day", "mass_flux", KG_PER_SHORT_TON / SECONDS_PER_DAY, label="tons/day (short)")
_add("tonnes/year", "mass_flux", KG_PER_TONNE / (SECONDS_PER_DAY * DAYS_PER_YEAR), label="tonnes/yr (metric)")
_add("tons/year", "mass_flux", KG_PER_SHORT_TON / (SECONDS_PER_DAY * DAYS_PER_YEAR), label="tons/yr (short)")
_add("kg", "mass", 1.0)
_add("tonnes", "mass", KG_PER_TONNE, label="tonnes (metric)")
_add("tons", "mass", KG_PER_SHORT_TON, label="tons (short)")
_add("mm", "diameter", 1.0)
_add("m_d", "diameter", 1000.0, label="m")
_add("degC", "temperature", 1.0, label="\u00b0C")
_add("degF", "temperature", 5.0 / 9.0, offset=-32.0 * 5.0 / 9.0, label="\u00b0F")
_add("1", "dimensionless", 1.0, label="-")

# Strings found in HEC-RAS "Units" attributes (US customary and SI) and common observation files.
_ALIASES = {
    "cfs": "cfs", "ft3/s": "cfs", "ft^3/s": "cfs", "cubic feet per second": "cfs",
    "m3/s": "m3/s", "m^3/s": "m3/s", "cms": "m3/s", "cubic meters per second": "m3/s",
    "ft": "ft", "feet": "ft", "foot": "ft", "m": "m", "meter": "m", "meters": "m",
    "ft/s": "ft/s", "fps": "ft/s", "m/s": "m/s",
    "lb/sqft": "lb/ft2", "lb/ft2": "lb/ft2", "lb/ft^2": "lb/ft2", "lbf/ft2": "lb/ft2", "psf": "lb/ft2",
    "pa": "Pa", "n/m2": "N/m2", "n/m^2": "N/m2", "n/sqm": "N/m2",
    "mg/l": "mg/L", "g/l": "g/L", "kg/m3": "kg/m3", "kg/m^3": "kg/m3", "ppm": "ppm",
    "kg/s": "kg/s",
    "tons/day": "tons/day", "ton/day": "tons/day", "tons/d": "tons/day", "short tons/day": "tons/day",
    "tonnes/day": "tonnes/day", "tonne/day": "tonnes/day", "metric tons/day": "tonnes/day",
    "tons/year": "tons/year", "tonnes/year": "tonnes/year",
    "kg": "kg", "tons": "tons", "ton": "tons", "tonnes": "tonnes", "tonne": "tonnes",
    "mm": "mm",
    "f": "degF", "degf": "degF", "\u00b0f": "degF", "c": "degC", "degc": "degC", "\u00b0c": "degC",
    "none": "1", "": "1", "-": "1", "fraction": "1", "1": "1",
}


def normalize_unit(unit: str | bytes | None) -> str:
    """Map a free-form unit string to a canonical key; raises :class:`UnitError` if unknown."""
    if isinstance(unit, bytes):
        unit = unit.decode("utf-8", "replace")
    key = (unit or "").strip().lower()
    key = key.replace("sq ", "sq").replace("sq.", "sq").replace(" ", " ")
    key = re.sub(r"\s+", " ", key)
    compact = key.replace(" ", "")
    for candidate in (key, compact, compact.replace("sqft", "ft2").replace("sqm", "m2")):
        if candidate in _ALIASES:
            return _ALIASES[candidate]
    if (unit or "") in _DEFS:
        return str(unit)
    raise UnitError(f"Unrecognised unit '{unit}'. Add it to sediment/units.py.")


def unit_def(unit: str) -> UnitDef:
    return _DEFS[normalize_unit(unit)]


def quantity_of(unit: str) -> str:
    return unit_def(unit).quantity


def unit_label(unit: str) -> str:
    return unit_def(unit).label


def convert(values, from_unit: str, to_unit: str):
    """Convert numbers/arrays between two units of the same physical quantity."""
    f, t = unit_def(from_unit), unit_def(to_unit)
    if f.quantity != t.quantity:
        raise UnitError(f"Cannot convert {f.quantity} ({from_unit}) to {t.quantity} ({to_unit}).")
    if f.name == t.name:
        return values
    arr = np.asarray(values, dtype=float) if not np.isscalar(values) else float(values)
    canonical = arr * f.to_canonical + f.offset
    out = (canonical - t.offset) / t.to_canonical
    return out


def to_canonical(values, unit: str):
    return convert(values, unit, CANONICAL[quantity_of(unit)])


def from_canonical(values, quantity: str, unit: str):
    if quantity_of(unit) != quantity:
        raise UnitError(f"Unit {unit} is not a {quantity} unit.")
    return convert(values, CANONICAL[quantity], unit)


def units_for(quantity: str) -> list[str]:
    return [u.name for u in _DEFS.values() if u.quantity == quantity and u.name != "m_d"]


# ---------------------------------------------------------------------------------------------
# Concentration <-> flux.  Explicit and dimensional: C [mg/L = g/m3] * Q [m3/s] = g/s = 1e-3 kg/s
# ---------------------------------------------------------------------------------------------
G_PER_KG = 1000.0


def flux_from_concentration(conc_mg_l, q_m3s):
    """Mass flux (kg/s) = C (mg/L) * Q (m3/s) / 1000.  Inputs canonical; NaN propagates."""
    return np.asarray(conc_mg_l, dtype=float) * np.asarray(q_m3s, dtype=float) / G_PER_KG


def concentration_from_flux(flux_kg_s, q_m3s):
    """Concentration (mg/L) = flux (kg/s) * 1000 / Q (m3/s); NaN where Q <= 0 (undefined)."""
    q = np.asarray(q_m3s, dtype=float)
    f = np.asarray(flux_kg_s, dtype=float)
    out = np.full(np.broadcast(f, q).shape, np.nan)
    ok = q > 0
    np.divide(f * G_PER_KG, q, out=out, where=ok)
    return out


def sediment_conversion_factor(conc_unit: str = "mg/L", q_unit: str = "cfs", flux_unit: str = "tons/day") -> float:
    """Multiplier turning ``C[conc_unit] * Q[q_unit]`` into ``flux[flux_unit]``.

    ``sediment_conversion_factor()`` is 0.0026969 (the well-known 0.0027 rule of thumb).
    """
    c = convert(1.0, conc_unit, "mg/L")
    q = convert(1.0, q_unit, "m3/s")
    kg_s = float(flux_from_concentration(c, q))
    return float(convert(kg_s, "kg/s", flux_unit))


def validate_units(names: Iterable[str]) -> None:
    for n in names:
        normalize_unit(n)
