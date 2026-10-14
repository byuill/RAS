# -*- coding: utf-8 -*-
"""
Generate_dataFile_Input.py

Downloads observed daily discharge from the USACE CWMS Data API for a user-specified
start/end date and assembles the data_RF*.csv input file consumed by
Generate_Discharge_BC_Ver3.py (RonFormat == 1).

OUTPUT (new_data_RF.csv), 4 comma-separated columns:
    date       : mm/dd/yyyy
    discharge  : Mississippi River discharge at Union Point (cfs) =
                 Tarbert Landing discharge + Old River Control Complex (ORCC) total outflow
    Red_River  : Red River discharge (cfs)
    ORCC       : Old River Control Complex (ORCC) total outflow (cfs)

DATA SOURCES (all USACE CWMS Data API, office MVN - New Orleans District):
    - "Red_River_Ldg.Flow.Inst.~1Day.0.DailyComputed"
          Mississippi River flow at Red River Landing / Tarbert Landing, i.e. the
          mainstem flow measured just DOWNSTREAM of the Old River diversion (after
          the ORCC has already removed water from the river).
    - ORCC total outflow = sum of the four diversion structures:
          "ORCC-Auxiliary_Control_Structure.Flow-Total.Inst.~1Day.0.DailyComputed"
          "ORCC-Hydroelectric_Power.Flow-Total.Inst.~1Day.0.DailyComputed"
          "ORCC-Low_Sill_Structure.Flow-Total.Inst.~1Day.0.DailyComputed"
          "ORCC-Overbank.Flow-Total.Inst.~1Day.0.DailyComputed"
    - "TOTALLAT.Flow.Inst.~1Day.0.DailyComputed"
          "Total Latitude Flow": the combined Mississippi + Red River flow at the
          latitude of Red River Landing.

DERIVED QUANTITIES (matches the user-specified definition and the historical
Ron's-method dataset used by Generate_Discharge_BC_Ver3.py):
    discharge (Union Point, pre-diversion) = Red_River_Ldg + ORCC_total
    Red_River                              = TOTALLAT - discharge

These CWMS time series identifiers and the relationships above were reverse-engineered
and verified against D:\\LMR Comp Phase 2\\LMRComp_Hydrograph_Tool (a companion hydrograph
tool with a verified, working CWMS station registry and cached multi-decade records) by
cross-checking computed values against the historical Flow_TimeSeries_new.csv record.

Created on 2026-09-25
"""

import sys
import argparse
from datetime import datetime

import requests
import pandas as pd

## __________________________________________________________________________________________________
## 1. USER INPUTS
## __________________________________________________________________________________________________

# Default start/end dates for the downloaded time series (overridable via command line).
DEFAULT_START_DATE = datetime(2000, 1, 1)
DEFAULT_END_DATE = datetime(2025, 12, 31)

# Name of the output file expected by Generate_Discharge_BC_Ver3.py (RonFormat == 1).
OUTPUT_FILE = 'new_data_RF.csv'

# ---- USACE CWMS Data API settings ----
CWMS_API_ROOT = 'https://cwms-data.usace.army.mil/cwms-data'
CWMS_OFFICE = 'MVN'  # New Orleans District (owns the Old River Control Complex project)

CWMS_TSID_RED_RIVER_LDG = 'Red_River_Ldg.Flow.Inst.~1Day.0.DailyComputed'
CWMS_TSID_TOTALLAT = 'TOTALLAT.Flow.Inst.~1Day.0.DailyComputed'
CWMS_TSID_ORCC_STRUCTURES = [
    'ORCC-Auxiliary_Control_Structure.Flow-Total.Inst.~1Day.0.DailyComputed',
    'ORCC-Hydroelectric_Power.Flow-Total.Inst.~1Day.0.DailyComputed',
    'ORCC-Low_Sill_Structure.Flow-Total.Inst.~1Day.0.DailyComputed',
    'ORCC-Overbank.Flow-Total.Inst.~1Day.0.DailyComputed',
]

CWMS_UNITS = 'cfs'
REQUEST_TIMEOUT = 60  # seconds


## __________________________________________________________________________________________________
## 2. USACE CWMS DATA API DOWNLOAD
## __________________________________________________________________________________________________

def fetch_cwms_timeseries(ts_id, start_date, end_date):
    """Downloads a CWMS time series and aggregates it to a daily mean (cfs).

    Returns a DataFrame with columns ['date', 'value'] indexed across the full date range.
    """
    params = {
        "office": CWMS_OFFICE,
        "name": ts_id,
        "begin": f"{start_date:%Y-%m-%d}T00:00:00Z",
        "end": f"{end_date:%Y-%m-%d}T23:59:59Z",
        "unit": CWMS_UNITS,
        "page-size": 500000,
    }
    print(f"Downloading CWMS time series '{ts_id}' ({start_date:%Y-%m-%d} to {end_date:%Y-%m-%d})...")
    resp = requests.get(
        f"{CWMS_API_ROOT}/timeseries", params=params,
        headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    rows = [(v[0], v[1]) for v in payload.get('values', []) if v[1] is not None]
    if not rows:
        raise RuntimeError(
            f"No CWMS data returned for time series '{ts_id}'. Verify the office, ID, and date range."
        )

    df = pd.DataFrame(rows, columns=['ts', 'value'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.tz_convert(None).dt.normalize()
    daily = df.groupby('date', as_index=False)['value'].mean()
    
    # Reindex to full date range
    full_range = pd.date_range(start_date, end_date, freq='D')
    daily = daily.set_index('date').reindex(full_range).rename_axis('date').reset_index()

    # Linearly interpolate short gaps (up to 7 days) if any exist in continuous series
    if 'Overbank' not in ts_id:
        daily['value'] = daily['value'].interpolate(method='linear', limit=7)
    else:
        # Overbank structure is closed/0 flow when not operating
        daily['value'] = daily['value'].fillna(0.0)
        daily.loc[daily['value'].abs() < 1.0, 'value'] = 0.0

    print(f"  Retrieved and aligned {len(daily)} daily values.")
    return daily


def download_orcc_total(start_date, end_date):
    """Downloads and sums the four ORCC diversion structures into a single total-outflow series."""
    total = None
    for ts_id in CWMS_TSID_ORCC_STRUCTURES:
        df = fetch_cwms_timeseries(ts_id, start_date, end_date)
        df = df.rename(columns={'value': ts_id})
        total = df if total is None else pd.merge(total, df, on='date', how='outer')

    structure_cols = [c for c in total.columns if c != 'date']
    total['ORCC'] = total[structure_cols].sum(axis=1, min_count=1)
    return total[['date', 'ORCC']]


## __________________________________________________________________________________________________
## 3. MAIN
## __________________________________________________________________________________________________

def main():
    parser = argparse.ArgumentParser(
        description="Download observed discharge from the USACE CWMS Data API and build the "
                    "data_RF*.csv input file for Generate_Discharge_BC_Ver3.py."
    )
    parser.add_argument('--start', type=str, default=DEFAULT_START_DATE.strftime('%m/%d/%Y'),
                         help='Start date, mm/dd/yyyy (default: %(default)s)')
    parser.add_argument('--end', type=str, default=DEFAULT_END_DATE.strftime('%m/%d/%Y'),
                         help='End date, mm/dd/yyyy (default: %(default)s)')
    parser.add_argument('--output', type=str, default=OUTPUT_FILE,
                         help='Output CSV file name (default: %(default)s)')
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, '%m/%d/%Y')
    end_date = datetime.strptime(args.end, '%m/%d/%Y')
    if end_date < start_date:
        sys.exit("End date must be on or after the start date.")

    red_river_ldg = fetch_cwms_timeseries(CWMS_TSID_RED_RIVER_LDG, start_date, end_date)
    red_river_ldg = red_river_ldg.rename(columns={'value': 'Red_River_Ldg'})

    orcc = download_orcc_total(start_date, end_date)

    totallat = fetch_cwms_timeseries(CWMS_TSID_TOTALLAT, start_date, end_date)
    totallat = totallat.rename(columns={'value': 'TOTALLAT'})

    df = pd.merge(red_river_ldg, orcc, on='date', how='outer')
    df = pd.merge(df, totallat, on='date', how='outer')
    df = df.sort_values('date').reset_index(drop=True)

    missing = df[df[['Red_River_Ldg', 'ORCC', 'TOTALLAT']].isnull().any(axis=1)]
    if not missing.empty:
        print(f"Warning: {len(missing)} date(s) have missing data from one or more CWMS sources.")

    # discharge = Union Point (pre-diversion) flow = post-diversion mainstem flow + diverted ORCC flow.
    df['discharge'] = df['Red_River_Ldg'] + df['ORCC']
    # Red River contribution = Total Latitude Flow minus the Union Point mainstem discharge.
    df['Red_River'] = df['TOTALLAT'] - df['discharge']

    negative = df['Red_River'] < 0
    if negative.any():
        print(f"Warning: {negative.sum()} date(s) had a negative computed Red_River value "
              "(small inconsistencies between the CWMS DailyComputed series); clipped to 0.")
        df.loc[negative, 'Red_River'] = 0.0

    out = df[['date', 'discharge', 'Red_River', 'ORCC']].copy()

    # Round flow values to 1 decimal place to prevent float precision artifacts in output
    for col in ['discharge', 'Red_River', 'ORCC']:
        out[col] = out[col].round(1)

    out['date'] = out['date'].dt.strftime('%m/%d/%Y')

    out.to_csv(args.output, index=False)
    print(f"Successfully generated {len(out)} daily records in '{args.output}' from {args.start} to {args.end}.")


if __name__ == '__main__':
    main()

