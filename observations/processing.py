"""Convert raw provider tables into the canonical observation table (SI units) with provenance."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from observations.station_catalog import Station
from sediment.units import convert, flux_from_concentration, M_PER_FT

OBS_VARIABLES = {
    "discharge_m3s": ("Discharge", "discharge"),
    "stage_gage_m": ("Gage height (above gage zero)", "length"),
    "stage_elev_m": ("Stage elevation (NAVD88)", "length"),
    "ssc_mg_l": ("Suspended-sediment concentration", "concentration"),
    "ssl_kg_s": ("Suspended-sediment discharge", "mass_flux"),
    "sand_mg_l": ("Sand concentration", "concentration"),
    "fines_mg_l": ("Fines concentration", "concentration"),
    "pct_fines": ("Percent fines (<0.0625 mm)", "dimensionless"),
    "water_temp_c": ("Water temperature", "temperature"),
}
META_COLS = ["kind", "source", "agency", "sample_id", "qualifier", "time_is_date_only", "censored_fields", "sample_timezone"]


@dataclass
class ObservationSet:
    station_id: str
    station_name: str
    df: pd.DataFrame                              # index DateTime; canonical columns + META_COLS
    sources: list[str] = field(default_factory=list)
    derivations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cache_status: list[str] = field(default_factory=list)
    qaqc: dict = field(default_factory=dict)

    def available_variables(self) -> list[str]:
        return [c for c in OBS_VARIABLES if c in self.df.columns and self.df[c].notna().any()]

    def series(self, var: str, kinds: list[str] | None = None) -> pd.Series:
        if var not in self.df.columns:
            return pd.Series(dtype=float)
        d = self.df if not kinds else self.df[self.df["kind"].isin(kinds)]
        return d[var].dropna()

    @property
    def n_records(self) -> int:
        return len(self.df)


def _blank(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(index=index, columns=list(OBS_VARIABLES) + META_COLS, dtype=object)


def _stage_elevation_m(height_ft: pd.Series, station: Station, notes: list[str]) -> pd.Series | None:
    """Gage height + gage-zero elevation, only when the vertical datum is known (see stations.yaml)."""
    if station.gage_zero_elev_ft is None:
        return None
    datum = (station.gage_zero_datum or "").upper()
    shift = 0.0
    if datum == "NGVD29":
        if station.ngvd29_to_navd88_shift_ft is None:
            notes.append(f"{station.short_name}: gage zero is NGVD29 and no NGVD29->NAVD88 shift is configured; "
                         "stage elevation not computed.")
            return None
        shift = station.ngvd29_to_navd88_shift_ft
    elif datum != "NAVD88":
        return None
    return (height_ft + station.gage_zero_elev_ft + shift) * M_PER_FT


def build_observation_set(station: Station, raw: dict[str, tuple[pd.DataFrame, dict]]) -> ObservationSet:
    """``raw`` maps parameter key -> (raw table, units dict)."""
    frames: list[pd.DataFrame] = []
    derivations: list[str] = []
    notes: list[str] = []
    sources: list[str] = []

    for param, (df, units) in raw.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d["DateTime"] = pd.to_datetime(d["DateTime"])
        d = d.set_index("DateTime").sort_index()
        out = _blank(d.index)
        if param == "usgs_wqp_samples":
            out["discharge_m3s"] = convert(d["discharge_cfs"].astype(float).values, "cfs", "m3/s")
            out["stage_gage_m"] = d["gage_height_ft"].astype(float).values * M_PER_FT
            el = _stage_elevation_m(d["gage_height_ft"].astype(float), station, notes)
            if el is not None:
                out["stage_elev_m"] = el.values
            ssc = d["ssc_mg_l"].astype(float)
            out["ssc_mg_l"] = ssc.values
            out["ssl_kg_s"] = convert(d["ssl_tons_day"].astype(float).values, "tons/day", "kg/s")
            pct = d["pct_fines"].astype(float)
            out["pct_fines"] = pct.values
            out["fines_mg_l"] = (ssc * pct / 100.0).values
            out["sand_mg_l"] = (ssc * (1.0 - pct / 100.0)).values
            out["water_temp_c"] = d["water_temp_c"].astype(float).values
            out["kind"] = "sample"
            out["sample_id"] = d["sample_id"].values
            out["qualifier"] = d["qualifier"].values
            out["time_is_date_only"] = d["time_is_date_only"].values
            out["source"] = "USGS WQP discrete sample"
            out["censored_fields"] = d.get("censored_fields", "")
            out["sample_timezone"] = d.get("tz", "")
            derived_fraction = pct.notna() & ssc.notna()
            out.loc[derived_fraction, "qualifier"] = (out.loc[derived_fraction, "qualifier"].fillna("").astype(str) + " fractions=derived").str.strip()
            if pct.notna().any():
                derivations.append("Sand/fines concentration = SSC x (1 - %fines/100) / SSC x %fines/100 using USGS pCode 70331 "
                                   "(percent finer than 0.0625 mm).")
        else:
            u = (units or {}).get("value", "")
            val = d["value"].astype(float)
            out["kind"] = "daily" if param.startswith("usgs_dv") else "instantaneous" if param == "usgs_iv_discharge" else "cwms"
            out["qualifier"] = d["qualifier"].values if "qualifier" in d.columns else ""
            if param in ("usgs_dv_discharge", "usgs_iv_discharge", "cwms_flow"):
                out["discharge_m3s"] = convert(val.values, u or "cfs", "m3/s")
            elif param in ("usgs_dv_stage", "cwms_stage"):
                kind = station.cwms.get("stage_kind", "gage_height") if param == "cwms_stage" else "gage_height"
                ft = convert(val.values, u or "ft", "ft")
                if kind == "elevation":
                    datum = (station.cwms.get("stage_datum") or "").upper()
                    if datum == "NAVD88":
                        out["stage_elev_m"] = ft * M_PER_FT
                    elif datum == "NGVD29" and station.ngvd29_to_navd88_shift_ft is not None:
                        out["stage_elev_m"] = (ft + station.ngvd29_to_navd88_shift_ft) * M_PER_FT
                    else:
                        notes.append(f"{station.short_name}: CWMS stage elevation is {datum or 'datum unknown'}; "
                                     "not converted to NAVD88 (set ngvd29_to_navd88_shift_ft in stations.yaml).")
                else:
                    out["stage_gage_m"] = ft * M_PER_FT
                    el = _stage_elevation_m(pd.Series(ft, index=d.index), station, notes)
                    if el is not None:
                        out["stage_elev_m"] = el.values
            elif param in ("usgs_dv_ssc", "cwms_ssc"):
                out["ssc_mg_l"] = val.values
            elif param in ("usgs_dv_ssl", "cwms_ssl"):
                out["ssl_kg_s"] = convert(val.values, "tons/day", "kg/s")
            out["source"] = "USGS NWIS subdaily value" if param == "usgs_iv_discharge" else "USGS NWIS daily value" if param.startswith("usgs_dv") else "USACE CWMS"
            out["agency"] = d["agency"].values if "agency" in d.columns else ""
            out["sample_id"] = ""
            out["time_is_date_only"] = param.startswith("usgs_dv")
        if "agency" not in out.columns or out["agency"].isna().all():
            out["agency"] = station.agency
        out["agency"] = out["agency"].fillna(station.agency)
        sources.append(f"{param}: {len(d)} records")
        frames.append(out)

    if not frames:
        empty = _blank(pd.DatetimeIndex([], name="DateTime"))
        return ObservationSet(station.id, station.name, empty, sources, derivations, notes)
    df = pd.concat([f.dropna(axis=1, how="all") for f in frames]).sort_index()
    df = df.reindex(columns=list(OBS_VARIABLES) + META_COLS)
    df.index.name = "DateTime"
    for c in OBS_VARIABLES:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time_is_date_only"] = df["time_is_date_only"].fillna(True).astype(bool)

    # Flux derived from SSC x Q only where a reported load is absent, and labelled
    both = df["ssc_mg_l"].notna() & df["discharge_m3s"].notna() & df["ssl_kg_s"].isna()
    if both.any():
        df.loc[both, "ssl_kg_s"] = flux_from_concentration(df.loc[both, "ssc_mg_l"].values,
                                                           df.loc[both, "discharge_m3s"].values)
        df.loc[both, "qualifier"] = (df.loc[both, "qualifier"].fillna("").astype(str) + " ssl=derived(SSCxQ)").str.strip()
        derivations.append(f"{int(both.sum())} sediment-discharge values derived as SSC x Q (no reported load at that sample); "
                           "flagged 'ssl=derived(SSCxQ)' in the qualifier column.")
    return ObservationSet(station.id, station.name, df, sources, derivations, notes)
