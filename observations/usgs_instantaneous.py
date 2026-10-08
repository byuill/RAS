"""USGS subdaily discharge, requested only for missing-Q sample-day windows."""
from __future__ import annotations

import pandas as pd

from core.exceptions import ProviderError
from observations.providers import FetchResult, ObservationProvider, http_get
from sediment.units import convert

NWIS_IV = 'https://waterservices.usgs.gov/nwis/iv/'


class UsgsInstantaneousProvider(ObservationProvider):
    name = 'usgs_iv'
    parameters = {'usgs_iv_discharge': 'USGS instantaneous discharge (00060)'}

    def fetch(self, station, parameter, start, end):
        if not station.site_no: raise ProviderError('A USGS site number is required for subdaily discharge.')
        rows, endpoints = [], set()
        cursor = pd.Timestamp(start).normalize()
        end = pd.Timestamp(end).normalize()
        while cursor <= end:
            stop = min(cursor+pd.Timedelta(days=30), end)
            from observations.usgs_api import fetch_values
            try:
                modern = fetch_values(station, '00060', 'cfs', cursor, stop, daily=False)
                endpoints.add(modern.endpoint)
                rows.extend((str(row.DateTime), row.value, row.qualifier, row.agency) for row in modern.df.itertuples())
                cursor = stop+pd.Timedelta(days=1)
                continue
            except ProviderError:
                pass  # Legacy NWIS remains a fallback for deployments where it is available.
            response = http_get(NWIS_IV, {'format': 'json', 'sites': station.site_no, 'parameterCd': '00060',
                'startDT': str(cursor.date()), 'endDT': str(stop.date()), 'siteStatus': 'all'})
            endpoints.add(NWIS_IV)
            if response.status_code not in (204, 404):
                try: series = response.json()['value']['timeSeries']
                except (KeyError, ValueError) as exc: raise ProviderError('Unexpected USGS instantaneous response.') from exc
                for item in series:
                    variable = item.get('variable', {})
                    unit = variable.get('unit', {}).get('unitCode', 'cfs')
                    nodata = float(variable.get('noDataValue', -999999))
                    for block in item.get('values', []):
                        for point in block.get('value', []):
                            try: value = float(point['value'])
                            except (KeyError, ValueError, TypeError): continue
                            if value == nodata: continue
                            # Offset-bearing USGS timestamps already use the station's local clock.
                            rows.append((point.get('dateTime', '')[:19], float(convert(value, unit, 'cfs')),
                                         ','.join(point.get('qualifiers', [])), 'USGS'))
            cursor = stop+pd.Timedelta(days=1)
        frame = pd.DataFrame(rows, columns=['DateTime', 'value', 'qualifier', 'agency'])
        frame['DateTime'] = pd.to_datetime(frame.DateTime, errors='coerce', format='mixed')
        frame = frame.dropna(subset=['DateTime']).drop_duplicates('DateTime')
        return FetchResult(frame, {'value': 'cfs'}, '; '.join(sorted(endpoints)),
            ['USGS timestamps on the station-local clock; subdaily discharge is not a sediment measurement.',
             'Subdaily source endpoints: '+ '; '.join(sorted(endpoints))])
