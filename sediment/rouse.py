"""Settling velocity, Rouse number and the (estimated) suspended / bed-associated classification.

Rouse number
------------
    P = ws / (kappa * u*),     u* = sqrt(tau_b / rho)

Classification thresholds (defaults after Rouse 1937 / Julien 2010; *all user-adjustable*):

* P <  0.8        wash load (fully suspended, uniformly distributed)
* 0.8 <= P < 1.2  100 % suspended
* 1.2 <= P < 2.5  ~50 % suspended (mixed)
* P >= 2.5        bed load (no appreciable suspension)

The GUI exposes two thresholds: ``susp_max`` (default 1.2) and ``bed_min`` (default 2.5).  The
"suspended load" group is every class with ``P < bed_min``; the "bed load" group is
``P >= bed_min``.  This is a *simplified, equilibrium-profile estimate* applied to the total
transport rate of each class; it does not replace a transport-function-specific partition.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sediment.units import G_ACCEL_SI

KAPPA_DEFAULT = 0.4  # von Karman constant (HEC-RAS "Rouse #" output was verified to use 0.4)
RHO_WATER_DEFAULT = 1000.0
BED_MIN_DEFAULT = 2.5
SUSP_MAX_DEFAULT = 1.2

CAT_SUSPENDED, CAT_MIXED, CAT_BED, CAT_INVALID = 0, 1, 2, -1


@dataclass(frozen=True)
class RouseConfig:
    kappa: float = KAPPA_DEFAULT
    bed_min: float = BED_MIN_DEFAULT
    susp_max: float = SUSP_MAX_DEFAULT
    source: str = "hecras"       # "hecras" (use stored Rouse #) or "computed"
    ferguson_c1: float = 18.0
    ferguson_c2: float = 1.0     # natural grains

    def key(self) -> tuple:
        return (self.kappa, self.bed_min, self.susp_max, self.source, self.ferguson_c1, self.ferguson_c2)


def water_density(temp_c):
    """Pure-water density (kg/m3), Kell (1975) polynomial; valid 0-40 degC."""
    t = np.asarray(temp_c, dtype=float)
    return (999.842594 + 6.793952e-2 * t - 9.095290e-3 * t ** 2 + 1.001685e-4 * t ** 3
            - 1.120083e-6 * t ** 4 + 6.536332e-9 * t ** 5)


def kinematic_viscosity(temp_c):
    """Kinematic viscosity (m2/s) from Vogel's dynamic-viscosity equation and Kell density."""
    t = np.asarray(temp_c, dtype=float)
    mu = 2.414e-5 * 10.0 ** (247.8 / (t + 273.15 - 140.0))
    return mu / water_density(t)


def settling_velocity(d_mm, temp_c=20.0, specific_gravity=2.65, c1=18.0, c2=1.0):
    """Particle settling velocity (m/s), Ferguson & Church (2004).

        ws = R g D^2 / (C1 nu + sqrt(0.75 C2 R g D^3)),   R = SG - 1

    Reduces to Stokes' law (ws = R g D^2 / 18 nu) for small D and to a constant-drag form for
    gravel, so it is valid across the clay-to-boulder range of HEC-RAS grain classes.
    ``c2 = 1.0`` is the natural-grain value (0.4 for smooth spheres).
    """
    d = np.asarray(d_mm, dtype=float) * 1e-3
    nu = kinematic_viscosity(temp_c)
    r = np.asarray(specific_gravity, dtype=float) - 1.0
    num = r * G_ACCEL_SI * d ** 2
    den = c1 * nu + np.sqrt(0.75 * c2 * r * G_ACCEL_SI * d ** 3)
    return num / den


def shear_velocity(tau_pa, rho=RHO_WATER_DEFAULT):
    """u* = sqrt(tau_b / rho) (m/s); negative or NaN stress gives NaN."""
    tau = np.asarray(tau_pa, dtype=float)
    out = np.full(tau.shape, np.nan)
    ok = tau >= 0
    out[ok] = np.sqrt(tau[ok] / rho)
    return out


def rouse_number(ws, ustar, kappa=KAPPA_DEFAULT):
    """P = ws / (kappa u*).  u* == 0 with ws > 0 gives +inf (no suspension); NaN propagates."""
    ws = np.asarray(ws, dtype=float)
    u = np.asarray(ustar, dtype=float)
    shape = np.broadcast(ws, u).shape
    out = np.full(shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = kappa * u
        ok = np.isfinite(ws) & np.isfinite(u)
        pos = ok & (denom > 0)
        out = np.where(pos, ws / np.where(denom > 0, denom, 1.0), out)
        out = np.where(ok & (denom <= 0) & (ws > 0), np.inf, out)
    return out


def rouse_category(p, susp_max=SUSP_MAX_DEFAULT, bed_min=BED_MIN_DEFAULT):
    """Integer category per value: 0 suspended-dominated, 1 mixed, 2 bed-dominated, -1 invalid."""
    p = np.asarray(p, dtype=float)
    cat = np.full(p.shape, CAT_INVALID, dtype=int)
    valid = ~np.isnan(p)
    cat[valid & (p < susp_max)] = CAT_SUSPENDED
    cat[valid & (p >= susp_max) & (p < bed_min)] = CAT_MIXED
    cat[valid & (p >= bed_min)] = CAT_BED
    return cat


def validate_thresholds(susp_max: float, bed_min: float) -> None:
    if not (0 < susp_max <= bed_min):
        raise ValueError("Rouse thresholds must satisfy 0 < suspended limit <= bed limit.")
