"""Lazy, cached access to a HEC-RAS sediment results HDF file."""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from core.exceptions import HdfStructureError, MissingVariableError
from ras.geo import DEFAULT_ALBERS_WKT, haversine_km, parse_albers_wkt  # noqa: F401
from ras.hdf_discovery import _attr_text, discover_layout
from ras.model import CrossSection, RasLayout, RasModelInfo
from sediment.grain_classes import GrainClass

logger = logging.getLogger(__name__)

_STAMP_FMT = "%d%b%Y %H:%M:%S"


def _dec(v) -> str:
    if isinstance(v,np.ndarray) and v.size == 1:
        v = v.reshape(-1)[0]
    return v.decode("utf-8", "replace").strip() if isinstance(v, (bytes, np.bytes_)) else str(v).strip()


def parse_time_stamps(raw: np.ndarray) -> pd.DatetimeIndex:
    """Parse HEC-RAS stamps (``01JAN2004 00:00:00``); ``24:00:00`` means midnight of the next day."""
    strs = [_dec(s) for s in raw]
    fixed, carry = [], []
    for s in strs:
        if s.endswith("24:00:00"):
            fixed.append(s.replace("24:00:00", "00:00:00"))
            carry.append(1)
        else:
            fixed.append(s)
            carry.append(0)
    idx = pd.to_datetime(fixed, format=_STAMP_FMT, errors="coerce")
    if idx.isna().any():
        bad = [strs[i] for i in np.where(idx.isna())[0][:3]]
        raise HdfStructureError(f"Could not parse simulation time stamps (e.g. {bad}).")
    return idx + pd.to_timedelta(carry, unit="D")


def _station_value(s: str) -> float:
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else float("nan")


class RasResults:
    """Opened results file.  Use :func:`open_results`.  All HDF access is serialised with a lock."""

    def __init__(self, path: Path, h5: h5py.File, info: RasModelInfo, cache_mb: float = 900.0):
        self.path = path
        self._h5 = h5
        self.info = info
        self._lock = threading.RLock()
        if not np.isfinite(cache_mb) or cache_mb < 0:
            raise ValueError('cache_mb must be finite and nonnegative.')
        self._cache: OrderedDict[object, np.ndarray] = OrderedDict()
        self._cache_bytes = 0
        self._cache_limit = int(cache_mb * 1024 * 1024)
        self.cache_hits = 0
        self.cache_misses = 0

    # -- raw access ----------------------------------------------------------------------
    def _dataset(self, path):
        if not self._h5.id.valid:
            raise HdfStructureError('This results file has been closed. Reopen it before reading data.')
        try:
            ds = self._h5[path]
        except KeyError as exc:
            raise MissingVariableError(f"Dataset '{path}' is not present in this HDF file.") from exc
        expected = (self.info.n_steps, len(self.info.xs))
        if not isinstance(ds, h5py.Dataset) or ds.shape != expected or ds.dtype.kind not in 'fiu':
            raise HdfStructureError(f"Dataset '{path}' must be a numeric time-by-cross-section matrix "
                                    f'of shape {expected}; found {getattr(ds, "shape", None)}.')
        return ds

    def _remember(self, key, arr):
        # A single oversized entry must never bypass the advertised cache limit.
        if arr.nbytes <= self._cache_limit and self._cache_limit > 0:
            while self._cache_bytes + arr.nbytes > self._cache_limit and self._cache:
                _, old = self._cache.popitem(last=False)
                self._cache_bytes -= old.nbytes
            arr.setflags(write=False)
            self._cache[key] = arr
            self._cache_bytes += arr.nbytes
        return arr

    def cache_info(self):
        with self._lock:
            return {'bytes': self._cache_bytes, 'limit_bytes': self._cache_limit,
                    'entries': len(self._cache), 'hits': self.cache_hits, 'misses': self.cache_misses}

    def matrix(self, path: str) -> np.ndarray:
        """Read a small complete matrix without reducing stored numerical precision.

        Explicit full-matrix requests exceeding the cache budget are refused. Use
        column() for large files. Returned cached matrices are read-only.
        """
        with self._lock:
            ds = self._dataset(path)
            if path in self._cache:
                self._cache.move_to_end(path)
                self.cache_hits += 1
                return self._cache[path]
            self.cache_misses += 1
            if ds.size * ds.dtype.itemsize > self._cache_limit:
                raise HdfStructureError('Full result matrix exceeds the cache budget. Read individual cross sections instead.')
            return self._remember(path, ds[...])

    def column(self, path: str, xs_index: int) -> np.ndarray:
        with self._lock:
            ds = self._dataset(path)
            if not isinstance(xs_index, (int, np.integer)) or not 0 <= xs_index < ds.shape[1]:
                raise HdfStructureError(f'Cross-section index {xs_index} is outside this dataset.')
            if path in self._cache:
                self._cache.move_to_end(path)
                self.cache_hits += 1
                return self._cache[path][:, xs_index].astype(np.float64)
            key = (path, int(xs_index))
            if key in self._cache:
                self._cache.move_to_end(key)
                self.cache_hits += 1
                return self._cache[key].copy()
            # Small matrices can benefit from a single decompression. Large ones
            # use an HDF hyperslab so selecting one XS never allocates all XS.
            if ds.size * ds.dtype.itemsize <= min(self._cache_limit, 64 * 1024 * 1024):
                return self.matrix(path)[:, xs_index].astype(np.float64)
            self.cache_misses += 1
            arr = np.asarray(ds[:, xs_index], dtype=np.float64)
            self._remember(key, arr)
            return arr.copy() if key in self._cache else arr

    def variable_path(self, name: str, class_index: int | None = None) -> str:
        v = self.info.layout.variables.get(name)
        if v is None:
            raise MissingVariableError(f"Result variable '{name}' is not available in this HDF file.")
        if class_index is None:
            if v.total_path is None:
                raise MissingVariableError(f"'{name}' has no total/scalar dataset in this HDF file.")
            return v.total_path
        if class_index not in v.class_paths:
            raise MissingVariableError(f"'{name}' is not stored for grain class {class_index}.")
        return v.class_paths[class_index]

    def var_units(self, name: str, class_index: int | None = None) -> str:
        variable = self.info.layout.variables.get(name)
        if variable is None:
            raise MissingVariableError(f"Result variable '{name}' is not available.")
        path = self.variable_path(name,class_index) if class_index is not None or variable.total_path else next(iter(variable.class_paths.values()))
        with self._lock:
            return _attr_text(self._dataset(path),'Units',variable.units)

    def var_column(self, name: str, xs_index: int, class_index: int | None = None) -> np.ndarray:
        return self.column(self.variable_path(name, class_index), xs_index)

    def class_stack(self, name: str, xs_index: int, class_indices: list[int]) -> np.ndarray:
        """(n_time x n_classes) array of a per-class variable at one cross section."""
        return np.column_stack([self.var_column(name, xs_index, k) for k in class_indices])

    def prefetch(self, names: list[str], class_indices: list[int] | None = None) -> None:
        """Warm only matrices that fit the cache; large datasets remain lazy."""
        def small(path):
            with self._lock:
                ds = self._dataset(path)
                if ds.size * ds.dtype.itemsize <= min(self._cache_limit, 64 * 1024 * 1024):
                    self.matrix(path)
        for n in names:
            v = self.info.layout.variables.get(n)
            if v is None:
                continue
            if v.total_path:
                small(v.total_path)
            for k in (class_indices if class_indices is not None else list(v.class_paths)):
                if k in v.class_paths:
                    small(v.class_paths[k])

    def close(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0
            try:
                self._h5.close()
            except (ValueError, OSError) as exc:  # already closed
                logger.debug("HDF close: %s", exc)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------------------------------------------
# Opening / metadata assembly
# ------------------------------------------------------------------------------------------
def open_results(path: str | Path, cache_mb: float = 900.0) -> RasResults:
    if not np.isfinite(cache_mb) or cache_mb < 0:
        raise ValueError('cache_mb must be finite and nonnegative.')
    path = Path(path)
    if not path.is_file():
        raise HdfStructureError(f"File not found: {path}")
    try:
        h5 = h5py.File(path, "r")
    except OSError as exc:
        raise HdfStructureError(f"'{path.name}' could not be opened as a HEC-RAS HDF5 file ({exc}).") from exc
    try:
        layout = discover_layout(h5)
        info = _build_info(h5, path, layout)
    except Exception:
        h5.close()
        raise
    logger.info("Opened %s: %s, %d XS, %d steps, %d grain classes", path, info.hec_version,
                len(info.xs), info.n_steps, len(info.grain_classes))
    return RasResults(path, h5, info, cache_mb)


def _build_info(h5: h5py.File, path: Path, layout: RasLayout) -> RasModelInfo:
    warnings: list[str] = list(layout.notes)
    root = h5.attrs
    hec_version = _dec(root.get("File Version", "unknown"))
    units_system = _dec(root.get("Units System", "unknown"))

    pi = h5[layout.plan_info_path].attrs if layout.plan_info_path else {}

    def pa(key: str) -> str:
        return _dec(pi.get(key, "")) if key in pi else ""

    plan_file = pa("Plan Filename").rsplit(".", 1)[-1] if pa("Plan Filename") else ""
    m = re.search(r"\.(p\d+)\.hdf$", path.name, flags=re.I)
    if m:
        plan_file = m.group(1).lower()

    times = _read_times(h5, layout, pa("Simulation Start Time"), warnings)
    xs = _read_cross_sections(h5, layout, warnings)
    classes = _read_grain_classes(h5, layout, warnings)

    reference = layout.variables.get('Flow') or next(iter(layout.variables.values()), None)
    n_cols = reference.shape[1] if reference else None
    if n_cols is not None and n_cols != len(xs):
        raise HdfStructureError(f'Cross-section table has {len(xs)} entries but results have {n_cols} columns. '
                                'The application cannot safely map these results to cross sections.')

    wkt = _attr_text(h5,'Projection') or (_attr_text(h5['Geometry'],'Projection') if 'Geometry' in h5 else '')
    wkt = wkt or _find_projection(path, pa("Project Filename"))
    xs = _attach_coordinates(h5, layout, xs, wkt, warnings)
    for needed in ("Flow", "Water Surface", "Velocity"):
        if needed not in layout.variables:
            warnings.append(f"Hydraulic variable '{needed}' is not stored in this file.")
    if "Sediment Concentration" not in layout.variables and "Sediment Discharge" not in layout.variables:
        warnings.append("No sediment concentration or discharge datasets were found.")
    for w in warnings:
        logger.warning("%s: %s", path.name, w)
    return RasModelInfo(
        path=str(path), hec_version=hec_version, units_system=units_system, plan_file=plan_file,
        plan_name=pa("Plan Name"), plan_title=pa("Plan Title"), short_id=pa("Plan ShortID"),
        project_title=pa("Project Title"), geometry_title=pa("Geometry Title"), flow_title=pa("Flow Title"),
        sim_start=pa("Simulation Start Time"), sim_end=pa("Simulation End Time"),
        times=times, xs=xs, grain_classes=classes, layout=layout, warnings=warnings, projection_wkt=wkt)


def _read_times(h5, layout: RasLayout, sim_start: str, warnings: list[str]) -> pd.DatetimeIndex:
    days = h5[layout.time_path][...].astype(float).reshape(-1)
    if not len(days) or not np.isfinite(days).all() or (np.diff(days) <= 0).any():
        raise HdfStructureError('Time must contain finite, strictly increasing output times.')
    if layout.time_stamp_path:
        idx = parse_time_stamps(h5[layout.time_stamp_path][...].reshape(-1))
        if len(idx) != len(days) or not idx.is_monotonic_increasing or idx.has_duplicates:
            raise HdfStructureError('Date stamps must match the Time array and be strictly increasing.')
        # Consistency: stamps vs Time (days) offsets
        if len(idx) > 1 and len(days) == len(idx):
            offs = (idx - idx[0]).total_seconds().values / 86400.0
            if not np.allclose(offs, days - days[0], atol=1e-3):
                warnings.append("Time date stamps and Time (days) arrays disagree; using date stamps.")
        return idx
    if not sim_start:
        raise HdfStructureError("Neither time date stamps nor a simulation start time are available.")
    start = parse_time_stamps(np.array([sim_start]))[0]
    return start + pd.to_timedelta(days, unit="D")


def _read_cross_sections(h5, layout: RasLayout, warnings: list[str]) -> list[CrossSection]:
    if layout.xs_attr_path is None:
        reference = layout.variables.get('Flow') or next(iter(layout.variables.values()), None)
        n = reference.shape[1] if reference else 0
        return [CrossSection(i, "?", "?", str(i)) for i in range(n)]
    a = h5[layout.xs_attr_path][...]
    names = a.dtype.names or ()
    if not {'River','Reach'} <= set(names) or not {'Station','RS'} & set(names):
        raise HdfStructureError('Cross-section attributes require River, Reach and Station/RS fields.')
    stn = "Station" if "Station" in names else "RS"
    out = []
    for i, rec in enumerate(a):
        st = _dec(rec[stn])
        out.append(CrossSection(i, _dec(rec["River"]), _dec(rec["Reach"]), st,
                                _dec(rec["Name"]) if "Name" in names else "", _station_value(st)))
    return out


def _read_grain_classes(h5, layout: RasLayout, warnings: list[str]) -> list[GrainClass]:
    if layout.grain_names_path is None:
        warnings.append("Sediment grain-class metadata could not be located in this HDF file.")
        return []
    names = [_dec(n) for n in h5[layout.grain_names_path][...].reshape(-1)]
    n = len(names)
    bounds = h5[layout.grain_bounds_path][...] if layout.grain_bounds_path else None
    dens = h5[layout.density_path][...] if layout.density_path else None
    coh = h5[layout.cohesive_path][...] if layout.cohesive_path else None
    for title, data, columns in [('Grain Class Bounds',bounds,3),('Density Data',dens,3)]:
        if data is not None and (data.ndim != 2 or data.shape[0] != n or data.shape[1] < columns):
            raise HdfStructureError(f'{title} must have one row per grain class and at least {columns} columns.')
    if coh is not None:
        coh = coh.reshape(-1)
        if len(coh) != n:
            raise HdfStructureError('Cohesive Classes must have one value per grain class.')
    if bounds is None:
        warnings.append("Grain-class diameters are not stored; sand/fines grouping is unavailable.")
    imperial_density = _dec(h5.attrs.get('Units System','')).lower() not in ('si','metric')
    if dens is not None and not imperial_density:
        warnings.append('SI grain unit weights are not interpreted; volume-out mass reconstruction is disabled.')
    classes = []
    for i, nm in enumerate(names):
        if bounds is not None:
            lo, geo, hi = (float(v) for v in bounds[i][:3])
            if not np.isfinite(geo) or geo <= 0:
                geo = float(np.sqrt(lo * hi)) if lo > 0 and hi > 0 else float("nan")
        else:
            lo = geo = hi = float("nan")
        classes.append(GrainClass(
            index=i + 1, name=nm, d_lower_mm=lo, d_rep_mm=geo, d_upper_mm=hi,
            specific_gravity=float(dens[i][0]) if dens is not None else 2.65,
            porosity=float(dens[i][1]) if dens is not None else float("nan"),
            unit_weight_lb_ft3=float(dens[i][2]) if dens is not None and imperial_density else float("nan"),
            cohesive=bool(coh[i]) if coh is not None and i < len(coh) else False))
    return classes


def _find_projection(hdf_path: Path, project_file_attr: str) -> str | None:
    """Look for an ESRI .prj with a PROJCS definition near the project; None if not found."""
    dirs: list[Path] = [hdf_path.parent]
    if project_file_attr:
        dirs.append(Path(project_file_attr).parent)
    seen: set[Path] = set()
    for d in dirs:
        if not d.exists() or d in seen:
            continue
        seen.add(d)
        for p in list(d.glob("*.prj")) + list(d.glob("*/*.prj")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text.startswith("PROJCS"):
                return text
    return None


def _attach_coordinates(h5, layout: RasLayout, xs: list[CrossSection], wkt: str | None,
                        warnings: list[str]) -> list[CrossSection]:
    if not (layout.geometry_polyline_info_path and layout.geometry_polyline_points_path
            and layout.geometry_xs_attr_path):
        return xs
    ga = h5[layout.geometry_xs_attr_path][...]
    gnames = ga.dtype.names or ()
    if not {'River','Reach'} <= set(gnames) or not {'RS','Station'} & set(gnames):
        warnings.append('Geometry XS attributes cannot be matched to results; coordinates unavailable.')
        return xs
    gstn = "RS" if "RS" in gnames else "Station"
    key_to_geom = {(_dec(r["River"]), _dec(r["Reach"]), _dec(r[gstn])): i for i, r in enumerate(ga)}
    info = h5[layout.geometry_polyline_info_path][...]
    pts = h5[layout.geometry_polyline_points_path]
    if info.ndim != 2 or info.shape[0] != len(ga) or info.shape[1] < 2 or pts.ndim != 2 or pts.shape[1] < 2:
        warnings.append('Geometry XS polyline dimensions are invalid; coordinates unavailable.')
        return xs
    proj = parse_albers_wkt(wkt) if wkt else None
    if proj is None:
        warnings.append('Project projection is missing or unsupported. Projected XS coordinates are retained, '
                        'but automatic gauge mapping is disabled; map stations manually.')
    out = []
    for xsec in xs:
        gi = key_to_geom.get((xsec.river, xsec.reach, xsec.station))
        if gi is None:
            out.append(xsec)
            continue
        start, count = int(info[gi][0]), int(info[gi][1])
        if start < 0 or count <= 0 or start + count > len(pts):
            warnings.append(f'{xsec.label}: invalid XS polyline bounds; coordinates unavailable.')
            out.append(xsec)
            continue
        p = pts[start:start + count]
        x, y = float(p[:, 0].mean()), float(p[:, 1].mean())
        lon, lat = proj.inverse(x, y) if proj is not None else (np.nan,np.nan)
        out.append(CrossSection(xsec.index, xsec.river, xsec.reach, xsec.station, xsec.name,
                                xsec.station_value, x, y, float(lon), float(lat)))
    return out
