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
            "startDateLo": start.strftime("%m-%d-%Y"), "startDateHi": end.strftime("%m-%d-%Y"),
            "mimeType": "csv", "zip": "no", "dataProfile": "narrowResult"}, timeout=180)
        units = {"ssc_mg_l": "mg/L", "ssl_tons_day": "tons/day", "pct_fines": "%", "discharge_cfs": "cfs",
                 "gage_height_ft": "ft", "water_temp_c": "degC"}
        if resp.status_code in (204, 404) or not resp.text.strip():
            return FetchResult(_empty_samples(), units, WQP_RESULT, ["The Water Quality Portal returned no samples."])
        try:
            raw = pd.read_csv(io.StringIO(resp.text), dtype=str, low_memory=False)
        except (ValueError, pd.errors.ParserError) as exc:
            raise ProviderError("The Water Quality Portal returned a file that could not be parsed.") from exc
        return FetchResult(parse_wqp_samples(raw), units, WQP_RESULT)


def _empty_samples() -> pd.DataFrame:
    cols = ["DateTime", "sample_id", "ssc_mg_l", "ssl_tons_day", "pct_fines", "discharge_cfs", "gage_height_ft",
            "water_temp_c", "time_is_date_only", "tz", "qualifier", "organization", "agency"]
    return pd.DataFrame({c: [] for c in cols}).astype({"DateTime": "datetime64[ns]"})


def parse_wqp_samples(raw: pd.DataFrame) -> pd.DataFrame:
    """Pivot WQP 'narrowResult' rows (one per parameter) into one row per sample activity."""
    need = {"ActivityIdentifier", "ActivityStartDate", "USGSPCode", "ResultMeasureValue"}
    if not need.issubset(raw.columns):
        raise ProviderError("The Water Quality Portal response is missing expected columns.")
    df = raw.copy()
    df["pcode"] = df["USGSPCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    df["val"] = pd.to_numeric(df["ResultMeasureValue"], errors="coerce")
    df = df[df["pcode"].isin([PCODE_SSC, PCODE_SSL, PCODE_PCT_FINES, PCODE_Q_INST, PCODE_Q, PCODE_GAGE, PCODE_TEMP])]
    df = df.dropna(subset=["val"])
    if df.empty:
        return _empty_samples()
    tcol = "ActivityStartTime/Time"
    tz = "ActivityStartTime/TimeZoneCode"
    df["time_txt"] = df[tcol] if tcol in df.columns else np.nan
    df["tz_txt"] = df[tz] if tz in df.columns else ""
    qual = "MeasureQualifierCode"
    df["qual"] = df[qual].fillna("") if qual in df.columns else ""
    det = "ResultDetectionConditionText"
    if det in df.columns:
        df["qual"] = (df["qual"] + " " + df[det].fillna("")).str.strip()
    rows = []
    for (act, date), g in df.groupby(["ActivityIdentifier", "ActivityStartDate"], sort=False):
        first = g.iloc[0]
        has_time = isinstance(first["time_txt"], str) and first["time_txt"].strip() != ""
        stamp = pd.to_datetime(f"{date} {first['time_txt'] if has_time else '00:00:00'}", errors="coerce")
        if pd.isna(stamp):
            continue

        def pick(*codes):
            for c in codes:
                s = g[g["pcode"] == c]["val"]
                if len(s):
                    return float(s.iloc[0])
            return np.nan

        quals = sorted({q for q in g["qual"] if q})
        rows.append({
            "DateTime": stamp, "sample_id": str(act), "ssc_mg_l": pick(PCODE_SSC), "ssl_tons_day": pick(PCODE_SSL),
            "pct_fines": pick(PCODE_PCT_FINES), "discharge_cfs": pick(PCODE_Q_INST, PCODE_Q),
            "gage_height_ft": pick(PCODE_GAGE), "water_temp_c": pick(PCODE_TEMP),
            "time_is_date_only": not has_time, "tz": str(first["tz_txt"]) if isinstance(first["tz_txt"], str) else "",
            "qualifier": ";".join(quals), "organization": str(first.get("OrganizationIdentifier", "")),
            "agency": "USGS"})
    out = pd.DataFrame(rows)
    return out.sort_values("DateTime").reset_index(drop=True) if not out.empty else _empty_samples()
