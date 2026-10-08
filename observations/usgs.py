"""USGS providers: NWIS daily values and discrete samples from the Water Quality Portal.

Endpoint choices follow the original ``SedRatingCurve/sed_rating/data_fetcher.py`` (NWIS DV for 00060 / 80154 /
80155, WQP for discrete samples) and ``RAS_Sed_Viewer.py`` (WQP pCodes 80154, 80155, 70331, 00061/00060).
"""
from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd

from core.exceptions import ProviderError
from observations.providers import FetchResult, ObservationProvider, http_get
from observations.station_catalog import Station

logger = logging.getLogger(__name__)

NWIS_DV = "https://waterservices.usgs.gov/nwis/dv/"
WQP_RESULT = "https://www.waterqualitydata.us/data/Result/search"

DV_PARAMS = {
    "usgs_dv_discharge": ("00060", "cfs", "Daily mean discharge"),
    "usgs_dv_stage": ("00065", "ft", "Daily mean gage height (above gage zero)"),
    "usgs_dv_ssc": ("80154", "mg/L", "Daily suspended-sediment concentration"),
    "usgs_dv_ssl": ("80155", "tons/day", "Daily suspended-sediment discharge (short tons/day)"),
}

# USGS parameter codes on discrete samples
PCODE_SSC, PCODE_SSL, PCODE_PCT_FINES = "80154", "80155", "70331"   # 70331: % finer than 0.0625 mm
PCODE_Q_INST, PCODE_Q, PCODE_GAGE, PCODE_TEMP = "00061", "00060", "00065", "00010"


class UsgsDailyValuesProvider(ObservationProvider):
    name = "usgs_dv"
    parameters = {k: v[2] for k, v in DV_PARAMS.items()}

    def fetch(self, station: Station, parameter: str, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
        pcode, unit, _ = DV_PARAMS[parameter]
        if not station.site_no:
            raise ProviderError(f"{station.short_name} has no USGS site number.")
        from observations.usgs_api import fetch_values
        try:
            return fetch_values(station, pcode, unit, start, end)
        except ProviderError as exc:
            logger.info("Modern USGS daily API unavailable; trying legacy NWIS: %s", exc)
        resp = http_get(NWIS_DV, {"format": "json", "sites": station.site_no, "parameterCd": pcode,
                                  "startDT": start.date().isoformat(), "endDT": end.date().isoformat(),
                                  "siteStatus": "all"})
        notes: list[str] = []
        if resp.status_code in (204, 404):
            return FetchResult(_empty_dv(), {"value": unit}, NWIS_DV, ["USGS reports no data for this request."])
        try:
            payload = resp.json()
            series = payload["value"]["timeSeries"]
        except (ValueError, KeyError) as exc:
            raise ProviderError("USGS returned an unexpected response for the daily-values request.") from exc
        rows = []
        # one DataFrame row per (date, statistic); prefer the mean statistic (00003) when several exist
        for ts in series:
            stat = _stat_code(ts)
            nodata = float(ts.get("variable", {}).get("noDataValue", -999999))
            for block in ts.get("values", []):
                for pt in block.get("value", []):
                    try:
                        v = float(pt["value"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if v == nodata or v <= -999990:
                        continue
                    rows.append((pt.get("dateTime", "")[:19], v, ",".join(pt.get("qualifiers", []) or []), stat))
        df = pd.DataFrame(rows, columns=["DateTime", "value", "qualifier", "statistic"])
        if not df.empty:
            df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
            df = df.dropna(subset=["DateTime"])
            stats = set(df["statistic"])
            if "00003" in stats and len(stats) > 1:
                notes.append(f"Several statistics returned ({sorted(stats)}); only the daily mean (00003) is cached.")
                df = df[df["statistic"] == "00003"]
        df["agency"] = "USGS"
        return FetchResult(df.reset_index(drop=True), {"value": unit}, NWIS_DV, notes)


def _empty_dv() -> pd.DataFrame:
    return pd.DataFrame({"DateTime": pd.to_datetime([]), "value": [], "qualifier": [], "statistic": [], "agency": []})


def _stat_code(ts: dict) -> str:
    try:
        opts = ts["variable"]["options"]["option"]
        for o in opts:
            if o.get("name", "").lower() == "statistic":
                return str(o.get("optionCode", ""))
    except (KeyError, TypeError):
        pass
    return ""


class UsgsDiscreteSampleProvider(ObservationProvider):
    """Discrete water-quality / sediment samples via the Water Quality Portal (WQP)."""
    name = "usgs_wqp"
    parameters = {"usgs_wqp_samples": "Discrete samples: SSC, sediment discharge, % fines, paired Q / gage height / temperature"}

    def fetch(self, station: Station, parameter: str, start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:
        if not station.site_no:
            raise ProviderError(f"{station.short_name} has no USGS site number.")
        pcodes = ";".join([PCODE_SSC, PCODE_SSL, PCODE_PCT_FINES, PCODE_Q_INST, PCODE_Q, PCODE_GAGE, PCODE_TEMP])
        resp = http_get(WQP_RESULT, {
            "siteid": f"USGS-{station.site_no}", "pCode": pcodes,
            "startDateLo": (start-pd.Timedelta(days=1)).strftime("%m-%d-%Y"), "startDateHi": (end+pd.Timedelta(days=1)).strftime("%m-%d-%Y"),
            "mimeType": "csv", "zip": "no", "dataProfile": "narrowResult"}, timeout=180)
        units = {"ssc_mg_l": "mg/L", "ssl_tons_day": "tons/day", "pct_fines": "%", "discharge_cfs": "cfs",
                 "gage_height_ft": "ft", "water_temp_c": "degC"}
        if resp.status_code in (204, 404) or not resp.text.strip():
            return FetchResult(_empty_samples(), units, WQP_RESULT, ["The Water Quality Portal returned no samples."], revision="wqp-units-censoring-v2")
        try:
            raw = pd.read_csv(io.StringIO(resp.text), dtype=str, low_memory=False)
        except (ValueError, pd.errors.ParserError) as exc:
            raise ProviderError("The Water Quality Portal returned a file that could not be parsed.") from exc
        return FetchResult(parse_wqp_samples(raw, station.timezone), units, WQP_RESULT,
            ["WQP units converted per result; detection limits flagged; known UTC/CST/CDT clocks converted to station time."],
            revision="wqp-units-censoring-v2")


def _empty_samples() -> pd.DataFrame:
    cols = ["DateTime", "sample_id", "ssc_mg_l", "ssl_tons_day", "pct_fines", "discharge_cfs", "gage_height_ft",
            "water_temp_c", "time_is_date_only", "tz", "qualifier", "organization", "agency"]
    return pd.DataFrame({c: [] for c in cols}).astype({"DateTime": "datetime64[ns]"})


def parse_wqp_samples(raw: pd.DataFrame, timezone="America/Chicago") -> pd.DataFrame:
    from observations.wqp_parser import parse_samples
    return parse_samples(raw, timezone)
