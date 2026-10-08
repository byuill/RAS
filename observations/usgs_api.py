"""Modern USGS Water Data OGC daily/continuous adapter, with bounded pagination."""
from urllib.parse import urljoin

import numpy as np
import pandas as pd

from core.exceptions import ProviderError, UnitError
from observations.providers import FetchResult, http_get
from sediment.units import convert

API = 'https://api.waterdata.usgs.gov/ogcapi/v0/collections'


def fetch_values(station, code, unit, start, end, daily=True):
    collection = 'daily' if daily else 'continuous'
    endpoint = f'{API}/{collection}/items'
    clock = 'UTC' if daily else station.timezone
    begin = pd.Timestamp(start).tz_localize(clock).tz_convert('UTC')
    stop = (pd.Timestamp(end)+pd.Timedelta(days=1)).tz_localize(clock).tz_convert('UTC')
    params = {'monitoring_location_id': f'USGS-{station.site_no}', 'parameter_code': code,
              'datetime': f'{begin.isoformat()}/{stop.isoformat()}', 'limit': 10000, 'f': 'json'}
    if daily: params['statistic_id'] = '00003'
    url, visited, rows = endpoint, set(), []
    for _ in range(1000):
        if url in visited: raise ProviderError('USGS API returned a pagination loop; partial results not cached.')
        visited.add(url)
        response = http_get(url, params)
        if response.status_code == 404:
            raise ProviderError('USGS API collection unavailable (404); try the legacy adapter or verify current schema.')
        if response.status_code == 204: break
        try: payload = response.json(); features = payload['features']
        except (KeyError, ValueError) as exc: raise ProviderError('Unexpected USGS OGC API response.') from exc
        for feature in features:
            p = feature.get('properties', {})
            if 'value' not in p: raise ProviderError('USGS OGC features lack value properties; inspect current schema.')
            if str(p.get('parameter_code', code)) != code: continue
            if daily and str(p.get('statistic_id', '00003')) != '00003': continue
            location = p.get('monitoring_location_id', f'USGS-{station.site_no}')
            if location != f'USGS-{station.site_no}': continue
            timestamp = p.get('time', p.get('date'))
            try: value = float(p['value'])
            except (TypeError, ValueError): continue
            if not np.isfinite(value): continue
            actual_unit = p.get('unit_of_measure', p.get('unit'))
            if not actual_unit: raise ProviderError('USGS API omitted measurement units; refusing to guess.')
            try: value = float(convert(value, actual_unit, unit))
            except UnitError as exc: raise ProviderError(f'Unsupported USGS API units: {actual_unit}') from exc
            stamp = pd.Timestamp(timestamp)
            if pd.isna(stamp): continue
            if daily: stamp = pd.Timestamp(str(timestamp)[:10])
            elif stamp.tz is not None: stamp = stamp.tz_convert(station.timezone).tz_localize(None)
            qualifier = p.get('qualifier', p.get('qualifiers', ''))
            rows.append((stamp, value, str(qualifier or ''), '00003' if daily else '', 'USGS'))
        following = next((link['href'] for link in payload.get('links', []) if link.get('rel') == 'next'), None)
        if not following: break
        url, params = urljoin(url, following), None
    else: raise ProviderError('USGS pagination limit reached; partial results not cached.')
    frame = pd.DataFrame(rows, columns=['DateTime','value','qualifier','statistic','agency'])
    frame['DateTime'] = pd.to_datetime(frame.DateTime)
    frame = frame.drop_duplicates(['DateTime','statistic'])
    return FetchResult(frame, {'value': unit}, endpoint, ['USGS Water Data OGC API; daily means or station-local subdaily clocks.'])
