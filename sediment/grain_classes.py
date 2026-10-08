"""Grain-class definitions and size-based grouping (sand / fines).

Representative diameter
-----------------------
HEC-RAS stores, per class, a ``Lower Bound``, ``Geometric Mean`` and ``Upper Bound`` (mm).  The
class is represented by its **geometric mean** diameter. Sand = 0.063 <= representative D < 2 mm,
fines = representative D < 0.063 mm.  Grouping is by diameter, never by class name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SAND_MIN_D_MM = 0.063


@dataclass(frozen=True)
class GrainClass:
    index: int                    # 1-based, as used in HDF dataset suffixes
    name: str
    d_lower_mm: float
    d_rep_mm: float               # representative (geometric mean) diameter
    d_upper_mm: float
    specific_gravity: float = 2.65
    porosity: float = float("nan")
    unit_weight_lb_ft3: float = float("nan")
    cohesive: bool = False
    d_source: str = "HDF Grain Class Bounds (geometric mean)"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.d_rep_mm:.3g} mm)"


@dataclass(frozen=True)
class SedimentGroup:
    """A selectable aggregation of grain classes."""
    key: str
    label: str
    class_indices: tuple[int, ...]   # 1-based; empty for dynamic groups (Rouse-based)
    description: str
    kind: str = "static"             # static | rouse
    estimated: bool = False


def classify_by_diameter(classes: list[GrainClass], sand_min_mm: float = SAND_MIN_D_MM
                         ) -> tuple[list[GrainClass], list[GrainClass]]:
    """Return (sand, fines) using representative diameters."""
    sand = [c for c in classes if sand_min_mm <= c.d_rep_mm < 2.0]
    fines = [c for c in classes if c.d_rep_mm < sand_min_mm]
    return sand, fines


def _fmt_classes(cs: list[GrainClass]) -> str:
    if not cs:
        return "none"
    return ", ".join(f"{c.name} ({c.d_rep_mm:.3g} mm)" for c in cs)


def build_groups(classes: list[GrainClass], sand_min_mm: float = SAND_MIN_D_MM,
                 rouse_available: bool = True, rouse_reason: str = "") -> list[SedimentGroup]:
    """All sediment groups offered in the GUI, with tooltip text listing the member classes."""
    sand, fines = classify_by_diameter(classes, sand_min_mm)
    coarse = [c for c in classes if c.d_rep_mm >= 2.0]
    groups = [
        SedimentGroup("total", "Total sediment", tuple(c.index for c in classes),
                      f"Sum of all {len(classes)} grain classes: {_fmt_classes(classes)}"),
        SedimentGroup("sand", f"Sand ({sand_min_mm:g} \u2264 D < 2 mm)", tuple(c.index for c in sand),
                      f"Classes with representative {sand_min_mm:g} \u2264 D < 2 mm: {_fmt_classes(sand)}"),
        SedimentGroup("fines", f"Fines (D < {sand_min_mm:g} mm)", tuple(c.index for c in fines),
                      f"Classes with representative D < {sand_min_mm:g} mm: {_fmt_classes(fines)}"),
        SedimentGroup('coarse','Gravel and coarser (D \u2265 2 mm)',tuple(c.index for c in coarse),
                      f'Classes with representative D \u2265 2 mm: {_fmt_classes(coarse)}'),
    ]
    for c in classes:
        groups.append(SedimentGroup(f"class:{c.index}", f"{c.name}  ({c.d_rep_mm:.3g} mm)", (c.index,),
                                    f"Single grain class {c.index}: {c.name}, "
                                    f"{c.d_lower_mm:g}\u2013{c.d_upper_mm:g} mm, representative {c.d_rep_mm:.4g} mm"
                                    + (" (cohesive)" if c.cohesive else "")))
    suffix = "" if rouse_available else f" [disabled: {rouse_reason}]"
    groups += [
        SedimentGroup("suspended_est", "Suspended load (Rouse estimate)", (),
                      "ESTIMATE: classes whose Rouse number P < bed threshold at each time step. "
                      "HEC-RAS does not store a suspended/bed-load split." + suffix, "rouse", True),
        SedimentGroup("bedload_est", "Bed load (Rouse estimate)", (),
                      "ESTIMATE: classes whose Rouse number P \u2265 bed threshold at each time step." + suffix,
                      "rouse", True),
        SedimentGroup("rouse_suspended", "Suspended-dominated, P < upper-susp. limit (est.)", (),
                      "ESTIMATE: P below the suspended-dominated limit (wash + fully suspended)." + suffix,
                      "rouse", True),
        SedimentGroup("rouse_mixed", "Mixed, susp. limit \u2264 P < bed limit (est.)", (),
                      "ESTIMATE: P between the suspended-dominated and bed-dominated limits." + suffix,
                      "rouse", True),
        SedimentGroup("rouse_bed", "Bed-dominated, P \u2265 bed limit (est.)", (),
                      "ESTIMATE: P at or above the bed-dominated limit." + suffix, "rouse", True),
    ]
    return groups


def class_array(classes: list[GrainClass], attr: str) -> np.ndarray:
    return np.array([getattr(c, attr) for c in classes], dtype=float)
