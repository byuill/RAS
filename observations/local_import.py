"""Import observations from CSV / Excel with automatic column detection and user override."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from core.exceptions import ObservationError, UnitError
from observations.processing import OBS_VARIABLES, ObservationSet, _blank
from sediment.units import convert, flux_from_concentration, normalize_unit, quantity_of

# target field -> (header synonyms, quantity, default unit)
FIELDS: dict[str, tuple[list[str], str, str]] = {
    "datetime": (["datetime", "date_time", "date time", "timestamp", "date", "sample date", "activitystartdate", "time"], "", ""),
    "discharge": (["discharge", "flow", "streamflow", "q", "q_cfs", "discharge_cfs", "flow_cfs"], "discharge", "cfs"),
    "stage": (["stage", "gage height", "gageheight", "gage_height", "stage_ft", "height"], "length", "ft"),
    "ssc": (["ssc", "suspended sediment concentration", "concentration", "conc", "ssc_mg_l", "sediment concentration"], "concentration", "mg/L"),
    "ssl": (["ssl", "sediment load", "load", "sediment discharge", "qs", "load_tons_day", "sediment flux"], "mass_flux", "tons/day"),
    "sand": (["sand", "sand concentration", "sand_ssc", "sand_mg_l"], "concentration", "mg/L"),
    "fines": (["fines", "fines concentration", "fines_ssc", "fines_mg_l"], "concentration", "mg/L"),
    "station": (["station", "site", "site_no", "station id"], "", ""),
}


@dataclass
class ColumnChoice:
    column: str | None
    unit: str


def read_table(path: str | Path, sheet: str | int | None = 0) -> pd.DataFrame:
    p = Path(path)
    try:
        if p.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
            return pd.read_excel(p, sheet_name=sheet)
        return pd.read_csv(p, sep=None, engine="python")
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ObservationError(f"'{p.name}' could not be read as a table: {exc}") from exc


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _guess_unit(header: str, default: str, quantity: str) -> str:
    tokens = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", str(header))
    if quantity and tokens:
        valid = []
        for token in tokens:
            try:
                unit = normalize_unit(token)
            except UnitError:
                continue
            if quantity_of(unit) == quantity:
                valid.append(unit)
        if valid:
            return valid[0]
        raise UnitError(f"Header '{header}' contains unrecognised or incompatible units. "
                        'Specify supported units before importing this column.')
    for t in tokens + re.split(r"[_ ]+", str(header)):
        try:
            u = normalize_unit(t)
            if quantity and quantity_of(u) == quantity:
                return u
        except UnitError:
            continue
    return default


def detect_mapping(df: pd.DataFrame) -> dict[str, ColumnChoice]:
    """Best-effort header matching (exact normalised synonym first, then substring)."""
    norm = {c: _norm(c) for c in df.columns}
    out: dict[str, ColumnChoice] = {}
    used: set[str] = set()
    for field_name, (syn, qty, default) in FIELDS.items():
        found = None
        for c, n in norm.items():
            if c in used:
                continue
            first = n.split(" ")[0] if n else n
            if n in syn or first in syn:
                found = c
                break
        if found is None:
            for c, n in norm.items():
                if c not in used and any(s in n for s in syn if len(s) > 3):
                    found = c
                    break
        if found is not None:
            used.add(found)
        out[field_name] = ColumnChoice(found, _guess_unit(found, default, qty) if found else default)
    return out


def to_observation_set(df: pd.DataFrame, mapping: dict[str, ColumnChoice], station_id: str, station_name: str,
                       source_label: str) -> ObservationSet:
    dt = mapping.get("datetime")
    if dt is None or dt.column is None:
        raise ObservationError("A date/time column must be mapped.")
    stamp = pd.to_datetime(df[dt.column], errors="coerce")
    ok = stamp.notna()
    if ok.sum() == 0:
        raise ObservationError(f"Column '{dt.column}' contains no recognisable dates/times.")
    d = df[ok].copy()
    out = _blank(pd.DatetimeIndex(stamp[ok], name="DateTime"))
    location = mapping.get("station")
    if location is not None and location.column is not None:
        sites = d[location.column].dropna().astype(str).str.strip()
        if len(sites[sites != ""].unique()) > 1:
            raise ObservationError("The table contains multiple sampling stations. Filter to one station before importing for calibration/proxy discharge.")
        out["sample_station_id"] = d[location.column].fillna("").astype(str).to_numpy()

    def col(name: str) -> np.ndarray | None:
        ch = mapping.get(name)
        if ch is None or ch.column is None:
            return None
        return pd.to_numeric(d[ch.column], errors="coerce").to_numpy(dtype=float)

    q = col("discharge")
    if q is not None:
        out["discharge_m3s"] = convert(q, mapping["discharge"].unit, "m3/s")
    st = col("stage")
    if st is not None:
        out["stage_gage_m"] = convert(st, mapping["stage"].unit, "m")
    for name, target, qty_unit in (("ssc", "ssc_mg_l", "mg/L"), ("sand", "sand_mg_l", "mg/L"), ("fines", "fines_mg_l", "mg/L")):
        v = col(name)
        if v is not None:
            out[target] = convert(v, mapping[name].unit, qty_unit)
    ssl = col("ssl")
    if ssl is not None:
        out["ssl_kg_s"] = convert(ssl, mapping["ssl"].unit, "kg/s")
    derivations = []
    out["kind"] = "sample"
    out["source"] = source_label
    out["agency"] = "user file"
    out["sample_id"] = ""
    out["qualifier"] = ""
    out["time_is_date_only"] = False
    for c in OBS_VARIABLES:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    both = out["ssc_mg_l"].notna() & out["discharge_m3s"].notna() & out["ssl_kg_s"].isna()
    if both.any():
        out.loc[both, "ssl_kg_s"] = flux_from_concentration(out.loc[both, "ssc_mg_l"].values, out.loc[both, "discharge_m3s"].values)
        out.loc[both, "qualifier"] = "ssl=derived(SSCxQ)"
        derivations.append(f"{int(both.sum())} sediment-discharge values derived as SSC x Q.")
    out = out.sort_index()
    return ObservationSet(station_id, station_name, out, [f"{source_label}: {len(out)} records"], derivations, [])


def merge_sets(a: ObservationSet | None, b: ObservationSet) -> ObservationSet:
    if a is None or a.df.empty:
        return b
    df = pd.concat([a.df, b.df]).sort_index()
    return ObservationSet(a.station_id, a.station_name, df, a.sources + b.sources, a.derivations + b.derivations,
                          a.notes + b.notes, a.cache_status)
