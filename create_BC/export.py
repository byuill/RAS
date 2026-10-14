"""Non-destructive exports with explicit boundary roles and DSS round-trip checks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from .engine import INFLOW_COLUMNS, EXTRACTION_COLUMNS
from .plots import draw_hydrographs, draw_network


# Keep the historical B-parts so existing model links can be reviewed/reused.
DSS_NAMES = {'discharge': 'TL_UP', 'Thebes': 'Thebes', 'Ohio': 'Ohio', 'LMR_Tribs': 'Minor_Tribs',
    'BirdsPoint': 'Birds_Point', 'NewMadrid': 'NewMadrid', 'ORCC_HydroP': 'ORCC_HydroP',
    'ORCC_LowSill': 'ORCC_LowSill', 'ORCC_Auxil': 'ORCC_Aux', 'overBank': 'ORCC_Overbank',
    'Red_River': 'RedRiver', 'Morganza': 'Morganza', 'BonnetCarre': 'BonnetCarre',
    'Davis_Pond': 'Davis_Pond', 'Caernarvon': 'Caernarvon', 'Siphons': 'Siphons',
    'MGP': 'MGP', 'PALH': 'PALH', 'OstNep': 'OstNep', 'FSP': 'FSP', 'BapCol': 'BapCol',
    'GrandPass': 'GP', 'CubitsGapWB': 'CubitsGapWestBay', 'Hatchie': 'Hatchie',
    'Arkansas': 'Arkansas', 'Yazoo': 'Yazoo', 'Terminal_Passes': 'Terminal_Passes',
    'SWP_Flow': 'SWP_Flow', 'SouthPass': 'SouthPass', 'PassALoutre': 'PassALoutre',
    'UnionPoint': 'UnionPoint', 'TarbertLanding': 'TarbertLanding', 'Simmesport': 'Simmesport'}


def dss_available():
    try:
        from pydsstools.heclib.dss import HecDss
        return HecDss is not None
    except (ImportError, OSError):
        return False


def read_stage(result, stage):
    stage = pd.read_csv(stage) if not isinstance(stage, pd.DataFrame) else stage.copy()
    if not {'date', 'stage_ft'} <= set(stage):
        raise ValueError('Stage CSV requires date and stage_ft; use feet in the independently verified model datum')
    dates = pd.to_datetime(result.flows.date)
    stage_dates = pd.to_datetime(stage.date, errors='raise', format='mixed')
    if stage_dates.duplicated().any() or not stage_dates.reset_index(drop=True).equals(dates.reset_index(drop=True)):
        raise ValueError('Stage dates must exactly match the discharge dates in order and coverage')
    values = pd.to_numeric(stage.stage_ft, errors='raise').to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError('Stage values must all be finite')
    return pd.DataFrame(dict(date=dates, stage_ft=values))


def write_dss(result, path, scenario='Cal', stage=None):
    try:
        from pydsstools.heclib.dss import HecDss
        from pydsstools.core import TimeSeriesContainer
    except ImportError as exc:
        raise RuntimeError('DSS export requires pip install -r create_BC/requirements-dss.txt') from exc
    if not scenario.strip() or any(c in scenario for c in '/\\\n\r'):
        raise ValueError('DSS scenario must be nonempty without slashes or line breaks')
    path = Path(path)
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite {path}')
    dates = pd.to_datetime(result.flows.date)
    series = [(name, 'FLOW', result.flows[column].to_numpy(dtype=float), 'cfs')
              for column, name in DSS_NAMES.items()]
    if stage is not None:
        stage = read_stage(result, stage)
        series.append(('TIMESERIES', 'STAGE', stage.stage_ft.to_numpy(), 'ft'))
    records = []
    try:
        with HecDss.Open(str(path)) as fid:
            for name, quantity, values, units in series:
                pathname = f'/IRREGULAR/{name}/{quantity}//1DAY/{scenario}/'
                # E-part identifies regular daily data; no fabricated irregular minute offsets.
                tsc = TimeSeriesContainer(pathname, len(values), 1)
                tsc.start_time = dates.iloc[0].strftime('%d%b%Y %H:%M:%S')
                tsc.data_units, tsc.data_type, tsc.values = units, 'INST-VAL', values
                fid.put_ts(tsc)
                records.append(dict(pathname=pathname, count=len(values), units=units, data_type='INST-VAL'))
        # Read the exact requested window: yearly blocks can include leading/trailing missing slots.
        with HecDss.Open(str(path)) as fid:
            window = (dates.iloc[0].strftime('%d%b%Y %H:%M:%S'), dates.iloc[-1].strftime('%d%b%Y %H:%M:%S'))
            for record, (_, _, expected, _) in zip(records, series):
                ts = fid.read_ts(record['pathname'], window=window)
                actual = np.asarray(ts.values)
                if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=1e-6, atol=.02):
                    raise RuntimeError(f'DSS round-trip value/count check failed for {record["pathname"]}')
                record['max_abs_roundtrip_error'] = float(np.max(np.abs(actual-expected)))
                times = pd.DatetimeIndex([t.datetime() for t in ts.times])
                if not times.equals(pd.DatetimeIndex(dates)):
                    raise RuntimeError(f'DSS round-trip timestamp check failed for {record["pathname"]}')
                if ts.data_units != record['units'] or ts.data_type != 'INST-VAL':
                    raise RuntimeError(f'DSS round-trip units/type check failed for {record["pathname"]}')
    except Exception:
        if path.exists():
            path.unlink()
        raise
    return records


def export_result(result, parent, *, scenario='Cal', include_dss=False, stage=None, index=0):
    """Publish one complete run directory; existing data is never replaced."""
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    output = parent / ('boundary-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    staging = Path(tempfile.mkdtemp(prefix='.boundary-', dir=parent))
    try:
        result.flows.to_csv(staging/'flows.csv', index=False, float_format='%.17g')
        result.input_data.to_csv(staging/'input_data.csv', index=False)
        result.split_data.to_csv(staging/'monthly_splits.csv', index=False)
        if stage is not None:
            stage = read_stage(result, stage)
            stage.to_csv(staging/'stage_input.csv', index=False)
        result.issues.to_csv(staging/'qaqc_issues.csv', index=False)
        result.parameters.save(staging/'parameters.json')
        report = dict(result.summary, scenario=scenario, dss_requested=include_dss,
                      stage_supplied=stage is not None)
        mappings = []
        for col, name in DSS_NAMES.items():
            role = ('inflow' if col in INFLOW_COLUMNS else 'lateral extraction' if col in EXTRACTION_COLUMNS
                    and col not in ['SWP_Flow', 'SouthPass', 'PassALoutre'] else 'diagnostic / model-specific mapping')
            mappings.append(dict(column=col, dss_b_part=name, units='cfs', role=role,
                note='Each terminal pass has this magnitude; do not also use aliases/aggregate series as boundaries.'
                if col in ['Terminal_Passes', 'SouthPass', 'PassALoutre'] else 'Review river/reach/station mapping before linking.'))
        pd.DataFrame(mappings).to_csv(staging/'boundary_roles.csv', index=False)
        ron_cols = ['date', 'Red_River', 'ORCC_HydroP', 'overBank', 'ORCC_LowSill', 'ORCC_Auxil',
                    'Simmesport', 'TarbertLanding', 'Rising_ID']
        result.flows[ron_cols].to_excel(staging/'ForRon.xlsx', index=False, sheet_name='Daily flows')
        draw_network(Figure(figsize=(15, 9)), result, index).savefig(staging/'river_budget.png', dpi=150)
        draw_hydrographs(Figure(figsize=(12, 9)), result).savefig(staging/'hydrographs.png', dpi=150)
        if include_dss:
            report['dss_records'] = write_dss(result, staging/'boundary_conditions.dss', scenario, stage)
            report['dss_round_trip_verified'] = True
        (staging/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging)
        raise
    return output
