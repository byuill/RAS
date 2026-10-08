"""USACE provider: CWMS Data API (public) time series configured per station in stations.yaml."""
from __future__ import annotations

import logging

import pandas as pd

from core.exceptions import ProviderError
from observations.providers import FetchResult, ObservationProvider, http_get
from observations.station_catalog import Station

logger = logging.getLogger(__name__)

CWMS_TS = "https://cwms-data.usace.army.mil/cwms-data/timeseries"
_TZ = {"CST6CDT": "America/Chicago", "US/Central": "America/Chicago", "UTC": "UTC", "GMT": "UTC"}


class UsaceCwmsProvider(ObservationProvider):
    name = "usace_cwms"
    parameters = {"cwms_flow": "USACE CWMS discharge", "cwms_stage": "USACE CWMS stage (gage height or elevation, see station config)"}

    def fetch(self, station: Station, parameter: str, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
        key = "flow" if parameter == "cwms_flow" else "stage"
        tsid = station.cwms.get(key)
        office = station.cwms.get("office")
        if not tsid or not office:
            raise ProviderError(f"{station.short_name} has no CWMS '{key}' time series configured.")
        params = {"name": tsid, "office": office, "unit": "EN",
                  "begin": start.strftime("%Y-%m-%dT00:00:00Z"),
                  "end": (end + pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"), "page-size": 5000}
        hdr = {"Accept": "application/json;version=2"}
        rows, units, tzname, datum, page = [], "", "UTC", {}, None
        for _ in range(200):
            q = dict(params)
            if page:
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
        df = pd.DataFrame(rows, columns=["epoch_ms", "value", "quality_code"])
        notes = []
        if df.empty:
            out = pd.DataFrame({"DateTime": pd.to_datetime([]), "value": [], "quality_code": [], "agency": []})
        else:
            t = pd.to_datetime(df["epoch_ms"], unit="ms", utc=True)
            tz = _TZ.get(tzname, "UTC")
            df["DateTime"] = t.dt.tz_convert(tz).dt.tz_localize(None)
            df["agency"] = "USACE"
            out = df[["DateTime", "value", "quality_code", "agency"]]
            notes.append(f"Time stamps converted from UTC to {tz} clock; CWMS series '{tsid}'.")
        if isinstance(datum, dict) and datum:
            notes.append(f"CWMS vertical datum: native {datum.get('native-datum')}, gage elevation {datum.get('elevation')} {datum.get('unit')}.")
        return FetchResult(out.reset_index(drop=True), {"value": units or "ft"}, f"{CWMS_TS}?name={tsid}&office={office}", notes)
