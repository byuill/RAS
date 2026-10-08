"""Local observation cache: Parquet data + JSON metadata, with date-range coverage tracking.

Layout::

    <root>/<provider>/<station_id>/<parameter>.parquet
    <root>/<provider>/<station_id>/<parameter>.json

``coverage`` lists the day ranges that have been *requested and answered* (even when the answer was
empty), so identical requests are served from disk and only uncovered gaps are downloaded.  The most
recent ``RECENT_DAYS`` are never marked covered because provisional data keep arriving.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.exceptions import CacheError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
RECENT_DAYS = 3

Range = tuple[pd.Timestamp, pd.Timestamp]


@dataclass
class CacheMeta:
    provider: str
    station_id: str
    parameter: str
    station_name: str = ""
    units: dict = field(default_factory=dict)
    retrieved: str = ""
    coverage: list[list[str]] = field(default_factory=list)
    actual_start: str | None = None
    actual_end: str | None = None
    n_records: int = 0
    source_endpoints: list[str] = field(default_factory=list)
    processing: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    revision: str = ""


@dataclass
class CacheLookup:
    df: pd.DataFrame | None
    missing: list[Range]
    meta: CacheMeta | None

    @property
    def complete(self) -> bool:
        return not self.missing


def merge_ranges(ranges: list[Range]) -> list[Range]:
    """Union of closed day ranges (adjacent days are merged)."""
    out: list[Range] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + pd.Timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract_ranges(start: pd.Timestamp, end: pd.Timestamp, covered: list[Range]) -> list[Range]:
    """Parts of [start, end] not inside ``covered``."""
    missing: list[Range] = []
    cur = start
    for s, e in merge_ranges(covered):
        if e < cur:
            continue
        if s > end:
            break
        if s > cur:
            missing.append((cur, min(s - pd.Timedelta(days=1), end)))
        cur = max(cur, e + pd.Timedelta(days=1))
        if cur > end:
            break
    if cur <= end:
        missing.append((cur, end))
    return missing


class ObservationCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    # -- paths ---------------------------------------------------------------------------------
    def _dir(self, provider: str, station_id: str) -> Path:
        return self.root / _safe(provider) / _safe(station_id)

    def _paths(self, provider: str, station_id: str, parameter: str) -> tuple[Path, Path]:
        d = self._dir(provider, station_id)
        return d / f"{_safe(parameter)}.parquet", d / f"{_safe(parameter)}.json"

    def folder(self, station_id: str | None = None) -> Path:
        if station_id is None:
            return self.root
        for p in self.root.glob("*"):
            if (p / _safe(station_id)).is_dir():
                return p / _safe(station_id)
        return self.root

    # -- read ----------------------------------------------------------------------------------
    def read_meta(self, provider: str, station_id: str, parameter: str) -> CacheMeta | None:
        _, jp = self._paths(provider, station_id, parameter)
        if not jp.exists():
            return None
        try:
            raw = json.loads(jp.read_text(encoding="utf-8"))
            return CacheMeta(**raw)
        except (OSError, ValueError, TypeError) as exc:
            raise CacheError(f"Cache metadata {jp.name} is unreadable ({exc}). Clear the station cache to rebuild it.") from exc

    def lookup(self, provider: str, station_id: str, parameter: str, start, end) -> CacheLookup:
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        meta = self.read_meta(provider, station_id, parameter)
        pp, _ = self._paths(provider, station_id, parameter)
        if meta is None or not pp.exists():
            self.misses += 1
            logger.info("Cache MISS %s/%s/%s %s..%s", provider, station_id, parameter, start.date(), end.date())
            return CacheLookup(None, [(start, end)], None)
        try:
            df = pd.read_parquet(pp)
        except (OSError, ValueError) as exc:
            raise CacheError(f"Cached data file {pp.name} is unreadable ({exc}). Clear the station cache to rebuild it.") from exc
        covered = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in meta.coverage]
        missing = subtract_ranges(start, end, covered)
        lo, hi = start, end + pd.Timedelta(days=1) - pd.Timedelta(1, unit="ns")
        sel = df[(df["DateTime"] >= lo) & (df["DateTime"] <= hi)].copy()
        if missing:
            self.misses += 1
            logger.info("Cache PARTIAL %s/%s/%s: %d gap(s) to download", provider, station_id, parameter, len(missing))
        else:
            self.hits += 1
            logger.info("Cache HIT %s/%s/%s %s..%s (%d rows)", provider, station_id, parameter, start.date(), end.date(), len(sel))
        return CacheLookup(sel.reset_index(drop=True), missing, meta)

    # -- write ---------------------------------------------------------------------------------
    def store(self, provider: str, station_id: str, parameter: str, df: pd.DataFrame, start, end, *,
              station_name: str = "", units: dict | None = None, endpoint: str = "",
              processing: list[str] | None = None, revision: str = "") -> CacheMeta:
        """Merge ``df`` (must contain ``DateTime``) into the cache and extend the coverage.  Existing rows are
        never dropped; rows with the same key are replaced by the newer download."""
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        cov_end = min(end, pd.Timestamp.now().normalize() - pd.Timedelta(days=RECENT_DAYS))
        pp, jp = self._paths(provider, station_id, parameter)
        pp.parent.mkdir(parents=True, exist_ok=True)
        meta = self.read_meta(provider, station_id, parameter) or CacheMeta(provider, station_id, parameter)
        old = pd.read_parquet(pp) if pp.exists() else None
        new = df.copy()
        if "DateTime" not in new.columns:
            raise CacheError("Internal error: observation table has no DateTime column.")
        new["DateTime"] = pd.to_datetime(new["DateTime"])
        frames = [f for f in (old, new) if f is not None and not f.empty]
        merged = pd.concat(frames, ignore_index=True) if frames else new
        key = [c for c in ("DateTime", "sample_id", "statistic") if c in merged.columns]
        merged = merged.drop_duplicates(subset=key, keep="last").sort_values("DateTime").reset_index(drop=True)
        _atomic_parquet(merged, pp)
        covered = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in meta.coverage]
        if cov_end >= start:
            covered.append((start, cov_end))
        meta.coverage = [[a.date().isoformat(), b.date().isoformat()] for a, b in merge_ranges(covered)]
        meta.station_name = station_name or meta.station_name
        meta.units = {**meta.units, **(units or {})}
        meta.retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        meta.n_records = int(len(merged))
        if len(merged):
            meta.actual_start = pd.Timestamp(merged["DateTime"].min()).isoformat()
            meta.actual_end = pd.Timestamp(merged["DateTime"].max()).isoformat()
        if endpoint and endpoint not in meta.source_endpoints:
            meta.source_endpoints.append(endpoint)
        for p in processing or []:
            if p not in meta.processing:
                meta.processing.append(p)
        meta.revision = revision or meta.revision
        meta.schema_version = SCHEMA_VERSION
        tmp = jp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
        os.replace(tmp, jp)
        logger.info("Cache STORE %s/%s/%s: +%d rows, total %d", provider, station_id, parameter, len(new), len(merged))
        return meta

    # -- management ----------------------------------------------------------------------------
    def entries(self, station_id: str | None = None) -> list[CacheMeta]:
        out = []
        for jp in self.root.glob("*/*/*.json"):
            if station_id and jp.parent.name != _safe(station_id):
                continue
            try:
                out.append(CacheMeta(**json.loads(jp.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Skipping unreadable cache metadata %s: %s", jp, exc)
        return out

    def clear_station(self, station_id: str) -> int:
        n = 0
        for prov in self.root.glob("*"):
            d = prov / _safe(station_id)
            if d.is_dir():
                n += sum(1 for _ in d.glob("*"))
                shutil.rmtree(d)
        logger.info("Cleared cache for %s (%d files)", station_id, n)
        return n


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
