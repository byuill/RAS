"""Write live USGS/CWMS source metadata for review, without downloading result series."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from observations.providers import http_get
from observations.station_catalog import StationCatalog
from observations.usace import CWMS_CATALOG
from observations.usgs_api import API


def verify(station):
    record = {'id': station.id, 'configured_name': station.name, 'checks': []}
    requests = []
    if station.site_no:
        requests += [(f'{API}/monitoring-locations/items', {'monitoring_location_id': station.id, 'f': 'json', 'limit': 10}),
            (f'{API}/time-series-metadata/items', {'monitoring_location_id': station.id, 'f': 'json', 'limit': 1000}),
            ('https://waterservices.usgs.gov/nwis/site/', {'format': 'rdb', 'sites': station.site_no,
                'seriesCatalogOutput': 'true', 'siteStatus': 'all'})]
    for key, pattern in station.cwms.items():
        if key.endswith('_pattern'):
            requests.append((CWMS_CATALOG, {'office': station.cwms['office'], 'like': pattern, 'page-size': 100}))
    for url, params in requests:
        item = {'endpoint': url, 'parameters': params}
        try:
            response = http_get(url, params, timeout=30, retries=0)
            item['http_status'] = response.status_code
            if response.status_code not in (204, 404):
                if params.get('format') == 'rdb':
                    lines = [line for line in response.text.splitlines() if line and not line.startswith('#')]
                    item['series'] = pd.read_csv(io.StringIO('\n'.join(lines)), sep='\t', dtype=str).iloc[1:].fillna('').to_dict('records') if len(lines)>2 else []
                else:
                    data = response.json()
                    item['metadata'] = data.get('entries', [feature.get('properties', {}) for feature in data.get('features', [])])
                    item['next_page_present'] = bool(data.get('next-page') or any(link.get('rel')=='next' for link in data.get('links', [])))
        except Exception as exc:
            item['error'] = str(exc)
        record['checks'].append(item)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', action='append', help='USGS site number or full catalog ID; repeat for multiple stations.')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    catalog = StationCatalog.load()
    stations = catalog.all() if not args.site else [catalog.get(x if '-' in x else 'USGS-'+x) for x in args.site]
    report = {'checked_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
              'note': 'Review station identity, parameters, extents and clock. Empty/error checks do not verify availability.',
              'stations': [verify(station) for station in stations]}
    Path(args.output).write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    failures = sum('error' in check or check.get('http_status', 200) >= 400
                   for station in report['stations'] for check in station['checks'])
    print(f'Wrote metadata for {len(stations)} stations; {failures} requests failed.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
