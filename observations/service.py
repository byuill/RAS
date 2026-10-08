"""Observation service: cache-first loading from provider adapters."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from core.exceptions import CacheError, ProviderError
from observations.cache import ObservationCache
from observations.processing import ObservationSet, build_observation_set
from observations.providers import FetchResult, ObservationProvider
from observations.station_catalog import Station, StationCatalog
from observations.usace import UsaceCwmsProvider
from observations.usgs import UsgsDailyValuesProvider, UsgsDiscreteSampleProvider

logger = logging.getLogger(__name__)

DEFAULT_PARAMETERS = ["usgs_wqp_samples", "usgs_dv_discharge", "usgs_dv_stage", "usgs_dv_ssc", "usgs_dv_ssl",
                      "cwms_flow", "cwms_stage"]


@dataclass
class ParameterReport:
    parameter: str
    provider: str
    status: str                 # cache hit | downloaded | partial download | error | no data
    rows: int = 0
    downloaded_rows: int = 0
    message: str = ""


@dataclass
class LoadReport:
    parameters: list[ParameterReport] = field(default_factory=list)

    @property
    def all_from_cache(self) -> bool:
        return bool(self.parameters) and all(p.status == "cache hit" for p in self.parameters)

    def lines(self) -> list[str]:
        out = []
        for p in self.parameters:
            extra = f" - {p.message}" if p.message else ""
            out.append(f"{p.parameter}: {p.status} ({p.rows} rows{', ' + str(p.downloaded_rows) + ' new' if p.downloaded_rows else ''}){extra}")
        return out


class ObservationService:
    def __init__(self, catalog: StationCatalog, cache: ObservationCache,
                 providers: list[ObservationProvider] | None = None):
        self.catalog = catalog
        self.cache = cache
        self.providers = providers or [UsgsDiscreteSampleProvider(), UsgsDailyValuesProvider(), UsaceCwmsProvider()]

    def provider_for(self, parameter: str) -> ObservationProvider:
        for p in self.providers:
            if p.handles(parameter):
                return p
        raise ProviderError(f"No provider handles parameter '{parameter}'.")

    def available_parameters(self, station: Station) -> list[str]:
        return [p for p in DEFAULT_PARAMETERS if station.supports(p)]

    def load(self, station: Station, start, end, parameters: list[str] | None = None, refresh: bool = False,
             progress: Callable[[str], None] | None = None) -> tuple[ObservationSet, LoadReport]:
        """Load (cache first) every parameter available for ``station`` over [start, end]."""
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        params = parameters or self.available_parameters(station)
        report = LoadReport()
        raw: dict[str, tuple[pd.DataFrame, dict]] = {}
        for param in params:
            prov = self.provider_for(param)
            say = progress or (lambda m: None)
            try:
                if refresh:
                    lk_missing = [(start, end)]
                    lk = self.cache.lookup(prov.name, station.id, param, start, end)
                else:
                    lk = self.cache.lookup(prov.name, station.id, param, start, end)
                    lk_missing = lk.missing
                downloaded = 0
                notes: list[str] = []
                for (ms, me) in lk_missing:
                    say(f"Downloading {param} for {station.short_name} {ms.date()} to {me.date()} ...")
                    res: FetchResult = prov.fetch(station, param, ms, me)
                    self.cache.store(prov.name, station.id, param, res.df, ms, me, station_name=station.name,
                                     units=res.units, endpoint=res.endpoint, processing=res.notes,
                                     revision=res.revision)
                    downloaded += len(res.df)
                    notes += res.notes
                final = self.cache.lookup(prov.name, station.id, param, start, end)
                df = final.df if final.df is not None else pd.DataFrame()
                units = (final.meta.units if final.meta else {}) or {}
                raw[param] = (df, units)
                if not lk_missing:
                    status = "cache hit"
                elif downloaded == 0:
                    status = "no data"
                else:
                    status = "downloaded" if lk.df is None or lk.df.empty else "partial download"
                report.parameters.append(ParameterReport(param, prov.name, status, len(df), downloaded, "; ".join(notes[:1])))
            except (ProviderError, CacheError) as exc:
                logger.warning("Observation load failed for %s/%s: %s", station.id, param, exc)
                report.parameters.append(ParameterReport(param, prov.name, "error", 0, 0, str(exc)))
        obs = build_observation_set(station, raw)
        obs.cache_status = report.lines()

        # --- SPECIAL CASE: UNION POINT SYNTHETIC DISCHARGE ---
        if station.id == "USGS-07295025":
            say = progress or (lambda m: None)
            say("Deriving Union Point discharge from Vicksburg + Big Black River...")
            try:
                vick = self.catalog.get("USGS-07289000")
                try:
                    bbr = self.catalog.get("USGS-07290000")
                except Exception:
                    bbr = Station(id="USGS-07290000", name="Big Black River near Bovina, MS", 
                                  short_name="Bovina", agency="USGS", site_no="07290000", 
                                  parameters={"usgs_dv_discharge": [str(start.date()), str(end.date())]})
                
                # Fetch Vicksburg flow (try USGS first, then CWMS)
                vick_obs, _ = self.load(vick, start, end, ["usgs_dv_discharge"], refresh)
                vick_q = vick_obs.series("discharge_m3s", kinds=["daily"])
                if vick_q.empty:
                    vick_obs, _ = self.load(vick, start, end, ["cwms_flow"], refresh)
                    vick_q = vick_obs.series("discharge_m3s")

                # Fetch Big Black River flow
                bbr_obs, _ = self.load(bbr, start, end, ["usgs_dv_discharge"], refresh)
                bbr_q = bbr_obs.series("discharge_m3s", kinds=["daily"])

                if not vick_q.empty and not bbr_q.empty:
                    vq = vick_q.groupby(vick_q.index.normalize()).mean()
                    bq = bbr_q.groupby(bbr_q.index.normalize()).mean()
                    combined = vq.add(bq, fill_value=0).dropna()

                    if not combined.empty and not obs.df.empty:
                        idx = obs.df.index.normalize()
                        matched = combined.reindex(idx, method='nearest', tolerance=pd.Timedelta('2D'))
                        obs.df["discharge_m3s"] = matched.values
                        obs.derivations.append("Discharge derived as Vicksburg + Big Black River (07290000).")

                        # Re-derive SSL if needed
                        if "ssc_mg_l" in obs.df.columns and "ssl_kg_s" in obs.df.columns:
                            both = obs.df["ssc_mg_l"].notna() & obs.df["discharge_m3s"].notna() & obs.df["ssl_kg_s"].isna()
                            if both.any():
                                from sediment.units import flux_from_concentration
                                obs.df.loc[both, "ssl_kg_s"] = flux_from_concentration(
                                    obs.df.loc[both, "ssc_mg_l"].values,
                                    obs.df.loc[both, "discharge_m3s"].values
                                )
                                obs.df.loc[both, "qualifier"] = (obs.df.loc[both, "qualifier"].fillna("").astype(str) + " ssl=derived(SSCxQ)").str.strip()
            except Exception as e:
                logger.warning("Could not derive Union Point discharge: %s", e)

        return obs, report
