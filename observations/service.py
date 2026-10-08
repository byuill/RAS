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
from observations.usgs_instantaneous import UsgsInstantaneousProvider
from observations.discharge_proxy import load_rules, flow_series, fill_discharge

logger = logging.getLogger(__name__)

DEFAULT_PARAMETERS = ["usgs_wqp_samples", "usgs_dv_discharge", "usgs_dv_stage", "usgs_dv_ssc", "usgs_dv_ssl",
                      "cwms_flow", "cwms_stage", "cwms_ssc", "cwms_ssl"]


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
        self.providers = providers or [UsgsDiscreteSampleProvider(), UsgsDailyValuesProvider(), UsaceCwmsProvider(), UsgsInstantaneousProvider()]

    def provider_for(self, parameter: str) -> ObservationProvider:
        for p in self.providers:
            if p.handles(parameter):
                return p
        raise ProviderError(f"No provider handles parameter '{parameter}'.")

    def available_parameters(self, station: Station) -> list[str]:
        return [p for p in DEFAULT_PARAMETERS if station.supports(p)]

    def load(self, station: Station, start, end, parameters: list[str] | None = None, refresh: bool = False,
             progress: Callable[[str], None] | None = None, derive_discharge: bool = True,
             include_subdaily: bool = False) -> tuple[ObservationSet, LoadReport]:
        """Load (cache first) every parameter available for ``station`` over [start, end]."""
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        params = self.available_parameters(station) if parameters is None else parameters
        if start > end: raise ValueError("Start date must be on or before end date.")
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
                migrate = prov.name == "usgs_wqp" and lk.meta is not None and lk.meta.revision != "wqp-units-censoring-v2"
                if migrate:
                    lk_missing = [(start, end)]
                downloaded = 0
                notes: list[str] = []
                for (ms, me) in lk_missing:
                    say(f"Downloading {param} for {station.short_name} {ms.date()} to {me.date()} ...")
                    res: FetchResult = prov.fetch(station, param, ms, me)
                    self.cache.store(prov.name, station.id, param, res.df, ms, me, station_name=station.name,
                                     units=res.units, endpoint=res.endpoint, processing=res.notes,
                                     revision=res.revision, replace_range=(param == "usgs_wqp_samples"), reset=migrate)
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
        for param, (_, _) in raw.items():
            meta = self.cache.read_meta(self.provider_for(param).name, station.id, param)
            if meta: obs.notes.extend(meta.processing)


        if derive_discharge and not obs.df.empty:
            obs = self.enrich_discharge(obs, station, start, end, refresh, include_subdaily, progress)
        return obs, report

    def enrich_discharge(self, obs, station, start, end, refresh=False, include_subdaily=False, progress=None):
        from dataclasses import replace
        obs = replace(obs, notes=list(obs.notes), derivations=list(obs.derivations), sources=list(obs.sources))
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        sediment_cols = [c for c in ('ssc_mg_l','ssl_kg_s','sand_mg_l','fines_mg_l') if c in obs.df]
        missing = obs.df[sediment_cols].notna().any(axis=1) & obs.df.discharge_m3s.isna()
        if missing.any():
            say = progress or (lambda message: None)
            local_parameters = [p for p in ('usgs_dv_discharge','cwms_flow') if station.supports(p)]
            local = obs
            if local_parameters:
                local, _ = self.load(station, start-pd.Timedelta(days=2), end+pd.Timedelta(days=2),
                    local_parameters, refresh, derive_discharge=False)
            if include_subdaily and station.site_no:
                # Fetch only days around missing sediment-sample Q, not a multi-decade IV record.
                days = sorted(set(obs.df.index[missing].normalize()))
                frames = [local.df]
                for day in days:
                    say(f'Loading same-site subdaily Q near {day.date()}...')
                    iv, iv_report = self.load(station, day-pd.Timedelta(days=1), day+pd.Timedelta(days=1),
                        ['usgs_iv_discharge'], refresh, derive_discharge=False)
                    frames.append(iv.df)
                    obs.notes.extend(iv_report.lines())
                from dataclasses import replace
                local = replace(local, df=pd.concat(frames).sort_index())
            recipes = load_rules().get(station.id, [])
            flows = {}
            for source_id in {term['station'] for recipe in recipes for term in recipe['terms']}:
                source = self.catalog.get(source_id)
                keys = [p for p in ('usgs_dv_discharge','cwms_flow') if source.supports(p)]
                if not keys:
                    obs.notes.append(f'Proxy component {source_id} has no configured flow source.'); continue
                say(f'Loading required proxy flow from {source.short_name}...')
                source_obs, source_report = self.load(source, start-pd.Timedelta(days=6), end+pd.Timedelta(days=6),
                    keys, refresh, derive_discharge=False)
                flows[source_id] = flow_series(source_obs)
                obs.notes.extend(f'Proxy {source_id}: {line}' for line in source_report.lines())
            obs = fill_discharge(obs, local, recipes, flows, local_station_id=station.id)
        return obs
