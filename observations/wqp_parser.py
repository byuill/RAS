"""Unit-aware WQP sediment activities, retaining censoring and source clocks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.exceptions import ProviderError, UnitError
from sediment.units import convert

FIELDS = {'80154': ('ssc_mg_l', 'mg/L'), '80155': ('ssl_tons_day', 'tons/day'),
    '70331': ('pct_fines', '%'), '00061': ('discharge_cfs', 'cfs'), '00060': ('discharge_cfs', 'cfs'),
    '00065': ('gage_height_ft', 'ft'), '00010': ('water_temp_c', 'degC')}
TZ = {'CST': 'Etc/GMT+6', 'CDT': 'Etc/GMT+5', 'UTC': 'UTC', 'GMT': 'UTC'}


def parse_samples(raw, timezone='America/Chicago'):
    from observations.usgs import _empty_samples
    required = {'ActivityIdentifier','ActivityStartDate','USGSPCode','ResultMeasureValue'}
    if not required.issubset(raw): raise ProviderError('WQP response lacks required sediment activity columns.')
    data = raw.copy()
    data['code'] = data.USGSPCode.astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(5)
    data = data[data.code.isin(FIELDS)].copy()
    data['value'] = pd.to_numeric(data.ResultMeasureValue, errors='coerce')
    for name in ('OrganizationIdentifier', 'MonitoringLocationIdentifier'):
        if name not in data: data[name] = ''
    rows = []
    keys = ['OrganizationIdentifier','MonitoringLocationIdentifier','ActivityIdentifier','ActivityStartDate']
    for (_, _, activity, date), group in data.groupby(keys, sort=False, dropna=False):
        first = group.iloc[0]
        clock = first.get('ActivityStartTime/Time', '')
        has_time = isinstance(clock, str) and bool(clock.strip())
        stamp = pd.to_datetime(f'{date} {clock if has_time else "00:00:00"}', errors='coerce')
        if pd.isna(stamp): continue
        tz = first.get('ActivityStartTime/TimeZoneCode', '')
        if has_time and tz in TZ:
            stamp = stamp.tz_localize(TZ[tz]).tz_convert(timezone).tz_localize(None)
        row = {field: np.nan for field, _ in FIELDS.values()}
        qualifiers, censored = [], set()
        for code in FIELDS:
            field, target = FIELDS[code]
            if np.isfinite(row[field]): continue  # instantaneous 00061 precedes 00060
            values = []
            for _, result in group[group.code == code].iterrows():
                qualifier = str(result.get('MeasureQualifierCode', '') or '')
                detection = str(result.get('ResultDetectionConditionText', '') or '')
                qualifier = '' if qualifier == 'nan' else qualifier
                detection = '' if detection == 'nan' else detection
                if qualifier or detection: qualifiers.append(f'{field}: {qualifier} {detection}'.strip())
                if any(token in (qualifier+' '+detection).lower() for token in ('<', '>', 'below', 'less than', 'not detected', 'above detection')):
                    censored.add({'ssl_tons_day':'ssl_kg_s', 'discharge_cfs':'discharge_m3s',
                                  'gage_height_ft':'stage_gage_m'}.get(field, field))
                value = result.value
                if not np.isfinite(value): continue
                unit = result.get('ResultMeasure/MeasureUnitCode', target)
                unit = target if pd.isna(unit) or str(unit).strip() == '' else str(unit)
                try:
                    if target == '%':
                        if unit.lower() not in ('%', 'percent', 'pct'): raise UnitError('Percent fines needs percent units.')
                        converted = float(value)
                    else: converted = float(convert(value, unit, target))
                except UnitError as exc: raise ProviderError(f'WQP {activity}: incompatible {field} unit {unit}.') from exc
                values.append(converted)
            if values:
                if np.allclose(values, values[0], rtol=1e-10, atol=0): row[field] = values[0]
                else: qualifiers.append(f'{field}: conflicting replicate/results omitted; review source activity')
        row.update(DateTime=stamp, sample_id=str(activity), time_is_date_only=not has_time,
            tz=str(tz) if isinstance(tz, str) else '', qualifier='; '.join(qualifiers),
            censored_fields=';'.join(sorted(censored)), organization=str(first.OrganizationIdentifier), agency='USGS')
        rows.append(row)
    return pd.DataFrame(rows).sort_values('DateTime').reset_index(drop=True) if rows else _empty_samples()
