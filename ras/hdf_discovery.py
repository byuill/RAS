"""Discovery of the sediment-results layout of a HEC-RAS ``.p##.hdf`` file.

This is the *only* module that knows HEC-RAS HDF path conventions.  Known paths are tried first
(HEC-RAS 6.x / 7.x layout, verified on 7.0.1) and a recursive search is used as a fallback so that
other versions degrade gracefully instead of failing.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

import h5py

from core.exceptions import HdfStructureError
from ras.model import RasLayout, VariableInfo

logger = logging.getLogger(__name__)

# --- version-dependent knowledge (verified: HEC-RAS 7.0.1) -----------------------------------
KNOWN_XS_TS_GROUPS = [
    "Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections",
]
KNOWN_XS_ATTR = ["Results/Sediment/Geometry Info/Cross Section Attributes",
                 "Geometry/Cross Sections/Attributes"]
KNOWN_GEOM_XS_ATTR = "Geometry/Cross Sections/Attributes"
KNOWN_POLY_INFO = "Geometry/Cross Sections/Polyline Info"
KNOWN_POLY_POINTS = "Geometry/Cross Sections/Polyline Points"
KNOWN_GRAIN_NAMES = ["Sediment/Grain Class Data/Grain Class Names", "Event Conditions/Sediment/Grain Class Names"]
KNOWN_GRAIN_BOUNDS = "Sediment/Grain Class Data/Grain Class Bounds"
KNOWN_DENSITY = "Sediment/Grain Class Data/Density Data"
KNOWN_COHESIVE = "Sediment/Grain Class Data/Cohesive Classes"
KNOWN_PLAN_INFO = "Plan Data/Plan Information"
# ---------------------------------------------------------------------------------------------

_SUFFIX = re.compile(r"^(?P<base>.+?) (?P<k>\d+)$")


def _attr_text(obj: h5py.Dataset | h5py.Group, key: str, default: str = "") -> str:
    v = obj.attrs.get(key, default)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace").strip()
    if hasattr(v, "tolist"):
        v = v.tolist()
    if isinstance(v, list) and v:
        v = v[0]
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace").strip()
    return str(v).strip()


def _first_existing(h5: h5py.File, paths: Iterable[str]) -> str | None:
    for p in paths:
        if p in h5:
            return p
    return None


def _find_group_fallback(h5: h5py.File) -> str | None:
    """Recursive search for a group holding many 2-D (time x xs) datasets, including 'Flow'."""
    found: list[str] = []

    def visit(name: str, obj) -> None:
        if isinstance(obj, h5py.Group) and name.endswith("Cross Sections"):
            has_flow = any(k.startswith("Flow") for k in obj.keys())
            two_d = sum(1 for k in list(obj.keys())[:20] if isinstance(obj[k], h5py.Dataset) and obj[k].ndim == 2)
            if has_flow and two_d >= 3 and "Results" in name:
                found.append(name)

    h5.visititems(visit)
    found.sort(key=lambda n: ("Sediment" not in n, len(n)))
    return found[0] if found else None


def discover_layout(h5: h5py.File) -> RasLayout:
    """Locate every dataset group the application needs; raises :class:`HdfStructureError` if the
    file contains no per-cross-section sediment time series."""
    notes: list[str] = []
    group = _first_existing(h5, KNOWN_XS_TS_GROUPS)
    if group is None:
        group = _find_group_fallback(h5)
        if group is None:
            raise HdfStructureError(
                "No sediment time-series results were found in this HDF file. Open the plan results file "
                "(.p##.hdf) of a computed sediment-transport simulation.")
        notes.append(f"Time-series group located by recursive search: {group}")
    parent = group.rsplit("/", 1)[0]
    time_path = f"{parent}/Time"
    if time_path not in h5:
        raise HdfStructureError("Time array not found next to the cross-section results in this HDF file.")
    stamp = f"{parent}/Time Date Stamp"
    stamp = stamp if stamp in h5 else None
    if stamp is None:
        notes.append("No 'Time Date Stamp' dataset; dates will be derived from simulation start + Time (days).")

    layout = RasLayout(
        xs_ts_group=group, time_path=time_path, time_stamp_path=stamp,
        xs_attr_path=_first_existing(h5, KNOWN_XS_ATTR),
        geometry_xs_attr_path=KNOWN_GEOM_XS_ATTR if KNOWN_GEOM_XS_ATTR in h5 else None,
        geometry_polyline_info_path=KNOWN_POLY_INFO if KNOWN_POLY_INFO in h5 else None,
        geometry_polyline_points_path=KNOWN_POLY_POINTS if KNOWN_POLY_POINTS in h5 else None,
        grain_names_path=_first_existing(h5, KNOWN_GRAIN_NAMES),
        grain_bounds_path=KNOWN_GRAIN_BOUNDS if KNOWN_GRAIN_BOUNDS in h5 else None,
        density_path=KNOWN_DENSITY if KNOWN_DENSITY in h5 else None,
        cohesive_path=KNOWN_COHESIVE if KNOWN_COHESIVE in h5 else None,
        plan_info_path=KNOWN_PLAN_INFO if KNOWN_PLAN_INFO in h5 else None,
        notes=notes,
    )
    if layout.xs_attr_path is None:
        notes.append("Cross-section attribute table not found; cross sections will be numbered only.")
    if layout.grain_names_path is None:
        notes.append("Sediment grain-class metadata could not be located in this HDF file.")
    layout.variables = _discover_variables(h5[group], n_classes=_n_classes(h5, layout))
    logger.info("Discovered %d result variables in %s", len(layout.variables), group)
    return layout


def _n_classes(h5: h5py.File, layout: RasLayout) -> int:
    if layout.grain_names_path:
        return int(h5[layout.grain_names_path].shape[0])
    return 0


def _discover_variables(grp: h5py.Group, n_classes: int) -> dict[str, VariableInfo]:
    """Group dataset names into variables: ``Name`` (total/scalar) and ``Name k`` (grain class k)."""
    names = [k for k, v in grp.items() if isinstance(v, h5py.Dataset) and v.ndim == 2]
    nameset = set(names)
    variables: dict[str, VariableInfo] = {}
    for nm in names:
        ds = grp[nm]
        m = _SUFFIX.match(nm)
        is_class = False
        if m and m.group("base") in nameset:
            base, k = m.group("base"), int(m.group("k"))
            gc = _attr_text(ds, "Grain Class")
            # per-class datasets carry the class number in 'Grain Class' (the base carries 'All')
            if (gc == str(k) or gc.lower() == "all") and (n_classes == 0 or k <= n_classes):
                info = variables.setdefault(base, VariableInfo(base, "", None, {}, "All", tuple(ds.shape)))
                info.class_paths[k] = f"{grp.name}/{nm}".lstrip("/")
                is_class = True
        if not is_class:
            info = variables.setdefault(nm, VariableInfo(nm, "", None, {}, _attr_text(ds, "Grain Class"), tuple(ds.shape)))
            info.total_path = f"{grp.name}/{nm}".lstrip("/")
    for info in variables.values():
        probe = info.total_path or next(iter(info.class_paths.values()))
        info.units = _attr_text(grp.file[probe], "Units", "")
        info.grain_class_attr = info.grain_class_attr or _attr_text(grp.file[probe], "Grain Class")
    return variables


# --------------------------------------------------------------------------------------------
# Diagnostic tree dump
# --------------------------------------------------------------------------------------------
_DATE_RE = re.compile(r"\d{1,2}[A-Za-z]{3}\d{4} \d\d:\d\d:\d\d")


def dump_tree(h5: h5py.File, root: str = "/", max_depth: int = 6, collapse: bool = True) -> str:
    """Printable HDF hierarchy.  With ``collapse`` names that differ only by a date stamp or a trailing
    grain-class number are merged and shown as ``Name [1..20]`` / ``<DATE> x N``."""
    lines: list[str] = []

    def describe(obj) -> str:
        if isinstance(obj, h5py.Dataset):
            extra = f" chunks={obj.chunks} {obj.compression}" if obj.chunks else ""
            return f"{obj.shape} {obj.dtype}{extra}"
        return f"group[{len(obj)}]"

    def walk(g: h5py.Group, depth: int) -> None:
        if depth > max_depth:
            return
        groups: dict[str, list[str]] = {}
        order: list[str] = []
        for k in g.keys():
            key = _DATE_RE.sub("<DATE>", k) if collapse else k
            if collapse:
                m = _SUFFIX.match(key)
                if m and isinstance(g[k], h5py.Dataset) and m.group("base") in g:
                    key = m.group("base") + " [k]"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(k)
        for key in order:
            members = groups[key]
            first = g[members[0]]
            suffix = f"  x{len(members)}" if len(members) > 1 else ""
            attrs = ""
            if isinstance(first, h5py.Dataset):
                u = _attr_text(first, "Units")
                attrs = f"  units={u}" if u else ""
            lines.append(f"{'  ' * depth}{key}  {describe(first)}{suffix}{attrs}")
            if isinstance(first, h5py.Group):
                walk(first, depth + 1)

    start = h5[root]
    walk(start, 0)
    return "\n".join(lines)
