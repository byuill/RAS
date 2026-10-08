"""USACE provider: CWMS Data API (public) time series configured per station in stations.yaml."""
from __future__ import annotations

import logging

import pandas as pd

from core.exceptions import ProviderError, UnitError
from sediment.units import quantity_of
from observations.providers import FetchResult, ObservationProvider, http_get
from observations.station_catalog import Station

logger = logging.getLogger(__name__)

CWMS_TS = "https://cwms-data.usace.army.mil/cwms-data/timeseries"
CWMS_CATALOG = "https://cwms-data.usace.army.mil/cwms-data/catalog/TIMESERIES"
_TZ = {"CST6CDT": "America/Chicago", "US/Central": "America/Chicago", "UTC": "UTC", "GMT": "UTC"}


class UsaceCwmsProvider(ObservationProvider):
    name = "usace_cwms"
    parameters = {"cwms_flow": "USACE CWMS discharge", "cwms_stage": "USACE CWMS stage (gage height or elevation, see station config)",
                  "cwms_ssc": "USACE suspended-sediment concentration (configured/unique discovered series)",
                  "cwms_ssl": "USACE suspended-sediment load (configured/unique discovered series)"}

    def fetch(self, station: Station, parameter: str, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
        key = {"cwms_flow": "flow", "cwms_stage": "stage", "cwms_ssc": "ssc", "cwms_ssl": "ssl"}[parameter]
        tsid = station.cwms.get(key)
        office = station.cwms.get("office")
        if not tsid and office and station.cwms.get(key + "_pattern"):
            tsid = discover_series(office, station.cwms[key + "_pattern"], key, start, end)
        if not tsid or not office:
            raise ProviderError(f"{station.short_name} has no CWMS '{key}' time series configured.")
        params = {"name": tsid, "office": office, "unit": "EN",
                  "begin": start.tz_localize(station.timezone).tz_convert("UTC").isoformat(),
                  "end": (end + pd.Timedelta(days=1)).tz_localize(station.timezone).tz_convert("UTC").isoformat(), "page-size": 5000}
        hdr = {"Accept": "application/json;version=2"}
        rows, units, tzname, datum, page = [], "", "UTC", {}, None
        seen_pages = set()
        for _ in range(200):
            q = dict(params)
            if page:
                if page in seen_pages: raise ProviderError("CWMS pagination loop; partial results are not cached.")
                seen_pages.add(page)
                q["page"] = page
            resp = http_get(CWMS_TS, q, hdr, timeout=120)
            if resp.status_code in (204, 404):
                break
            try:
                j = resp.json()
            except ValueError as exc:
                raise ProviderError("USACE CWMS returned an unreadable response.") from exc
            units = j.get("units", units)
            tzname = j.get("time-zone", tzname)
            datum = j.get("vertical-datum-info", datum) or datum
            rows += [(v[0], v[1], v[2] if len(v) > 2 else 0) for v in j.get("values", []) if v[1] is not None]
            page = j.get("next-page")
            if not page:
                break
        else: raise ProviderError("CWMS pagination limit reached; partial results are not cached.")
        df = pd.DataFrame(rows, columns=["epoch_ms", "value", "quality_code"])
        notes = []
        if df.empty:
            out = pd.DataFrame({"DateTime": pd.to_datetime([]), "value": [], "quality_code": [], "agency": []})
        else:
            t = pd.to_datetime(df["epoch_ms"], unit="ms", utc=True)
            tz = station.timezone
            df["DateTime"] = t.dt.tz_convert(tz).dt.tz_localize(None)
            df["agency"] = "USACE"
            df["qualifier"] = "CWMS quality-code=" + df.quality_code.astype(str)
            out = df[["DateTime", "value", "quality_code", "agency", "qualifier"]]
            notes.append(f"Time stamps converted from UTC to {tz} clock; CWMS series '{tsid}'.")
        if isinstance(datum, dict) and datum:
            notes.append(f"CWMS vertical datum: native {datum.get('native-datum')}, gage elevation {datum.get('elevation')} {datum.get('unit')}.")
        if not units:
            raise ProviderError("CWMS response omitted units; refusing to guess flow or sediment units.")
        expected = {"flow": "discharge", "stage": "length", "ssc": "concentration", "ssl": "mass_flux"}[key]
        try:
            if quantity_of(units) != expected: raise UnitError("Incompatible units")
        except UnitError as exc: raise ProviderError(f"CWMS {key} units are incompatible: {units}") from exc
        return FetchResult(out.reset_index(drop=True), {"value": units}, f"{CWMS_TS}?name={tsid}&office={office}", notes)


def discover_series(office, pattern, key, start, end):
    """Accept only a unique, compatible, overlapping series; never guess revisions."""
    quantity = {'flow': 'discharge', 'stage': 'length', 'ssc': 'concentration', 'ssl': 'mass_flux'}[key]
    candidates, page = [], None
    for _ in range(100):
        params = {'office': office, 'like': pattern, 'page-size': 100}
        if page: params['page'] = page
        response = http_get(CWMS_CATALOG, params, {'Accept': 'application/json;version=2'})
        if response.status_code in (204, 404): break
        try: payload = response.json()
        except ValueError as exc: raise ProviderError('Unreadable CWMS catalog.') from exc
        for entry in payload.get('entries', []):
            try:
                if quantity_of(entry.get('units', '')) != quantity: continue
            except UnitError: continue
            extents = entry.get('extents', [])
            overlap = not extents or any(
                pd.Timestamp(x['earliest-time']).tz_localize(None) <= end+pd.Timedelta(days=1) and
                pd.Timestamp(x['latest-time']).tz_localize(None) >= start
                for x in extents if x.get('earliest-time') and x.get('latest-time'))
            if overlap: candidates.append(entry['name'])
        page = payload.get('next-page')
        if not page: break
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise ProviderError(f'CWMS discovery for {pattern}: {len(candidates)} compatible overlapping series. '
            f'Configure an explicit {key} series in stations_user.yaml after review. Candidates: {candidates[:10]}')
    return candidates[0]
