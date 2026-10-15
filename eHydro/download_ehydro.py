"""Download eHydro survey data packages; defaults to MVK/MVM Lower Mississippi, 2025.

Run from any directory with Python 3.10+ and requests installed. See
eHydro/README.md for selection semantics, examples, and output details.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import unquote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LAYER = ('https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/'
         'eHydro_Survey_Data/FeatureServer/0')
TOOL = 'ras-ehydro-downloader'


def session_with_retries():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'], respect_retry_after_header=True)
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.headers['User-Agent'] = 'RAS-eHydro-downloader/1.0'
    return session


def api_json(session, url, **params):
    response = session.get(url, params={'f': 'json', **params}, timeout=(15, 90))
    response.raise_for_status()
    payload = response.json()
    if 'error' in payload:
        error = payload['error']
        raise RuntimeError(f'ArcGIS error {error.get("code")}: {error.get("message")} '
                           f'{error.get("details", [])}')
    return payload


def discover_surveys(session, layer, districts, year, channel_field):
    """Fetch all candidate IDs, then attributes in batches, avoiding page truncation."""
    schema = api_json(session, layer)
    fields = {field['name'].lower(): field['name'] for field in schema['fields']}
    for required in ['usacedistrictcode', 'surveydatestart', 'sourcedatalocation', channel_field.lower()]:
        if required not in fields:
            raise RuntimeError(f'Required field {required!r} is absent from the survey layer. '
                               f'Available fields: {", ".join(sorted(fields))}')
    district_field, date_field = fields['usacedistrictcode'], fields['surveydatestart']
    # eHydro stores the full USACE symbol (CEMVK), not the short district code (MVK).
    symbols = [code if len(code) == 5 else 'CE'+code for code in districts]
    codes = ', '.join("'" + code + "'" for code in symbols)
    where = (f"{district_field} IN ({codes}) AND "
             f"{date_field} >= TIMESTAMP '{year}-01-01 00:00:00' AND "
             f"{date_field} < TIMESTAMP '{year+1}-01-01 00:00:00'")
    selection = api_json(session, layer+'/query', where=where, returnIdsOnly='true')
    if 'objectIds' not in selection:
        raise RuntimeError('ArcGIS did not return objectIds; refusing to treat this as an empty selection.')
    ids = sorted(set(selection['objectIds'] or []))
    oid_field = selection.get('objectIdFieldName') or schema.get('objectIdField')
    if not oid_field:
        raise RuntimeError('Survey layer has no object ID field.')
    oid_field = oid_field.lower()
    size = max(1, min(500, int(schema.get('maxRecordCount', 500))))

    def fetch_batch(batch):
        page = api_json(session, layer+'/query', objectIds=','.join(map(str, batch)),
                        outFields='*', returnGeometry='false')
        if page.get('exceededTransferLimit'):
            if len(batch) == 1:
                raise RuntimeError(f'ArcGIS truncated object {batch[0]}.')
            middle = len(batch)//2
            return fetch_batch(batch[:middle]) + fetch_batch(batch[middle:])
        if 'features' not in page:
            raise RuntimeError('ArcGIS returned no features member for a record batch.')
        records = [{key.lower(): value for key, value in feature['attributes'].items()}
                   for feature in page['features']]
        returned = [record.get(oid_field) for record in records]
        if len(returned) != len(batch) or set(returned) != set(batch):
            raise RuntimeError('Survey records changed or a batch was incomplete; rerun catalog discovery.')
        return records

    records = []
    for offset in range(0, len(ids), size):
        records.extend(fetch_batch(ids[offset:offset+size]))
    return records, where


def matches_channel(record, patterns, field='channelareaidfk'):
    value = str(record.get(field.lower()) or '').strip().upper()
    return bool(value) and any(fnmatchcase(value, pattern.upper()) for pattern in patterns)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package_name(url):
    # URL hashes distinguish archives with identical names; no server-provided path is used.
    leaf = unquote(urlsplit(url).path.rsplit('/', 1)[-1]) or 'survey-data'
    leaf = re.sub(r'[^A-Za-z0-9._-]', '_', leaf)[-120:].strip('.') or 'survey-data'
    return hashlib.sha256(url.encode()).hexdigest()[:24] + '_' + leaf


def download_package(session, url, directory, previous=None):
    """Stream to a temporary file and promote only complete, nonempty downloads."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError('Expected a public HTTPS data-package URL without embedded credentials.')
    path = directory/package_name(url)
    if path.exists():
        if (previous and previous.get('status') in {'downloaded', 'verified_existing'}
                and path.stat().st_size == previous.get('bytes')
                and sha256_file(path) == previous.get('sha256')):
            return {**previous, 'status': 'verified_existing'}
        raise RuntimeError(f'Existing file is not verified by the manifest; preserving {path.name}. '
                           'Move it aside before retrying.')
    temporary = None
    try:
        with session.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', '').lower():
                raise RuntimeError('The package URL returned an HTML page instead of survey data.')
            digest, count = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=directory, prefix=path.name+'.', suffix='.part', delete=False) as target:
                temporary = Path(target.name)
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        if count == 0 and chunk.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                            raise RuntimeError('The package URL returned HTML instead of survey data.')
                        target.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
            if not count:
                raise RuntimeError('The package URL returned an empty file.')
            length = response.headers.get('Content-Length')
            if length is not None and response.headers.get('Content-Encoding', 'identity') == 'identity':
                if int(length) != count:
                    raise RuntimeError(f'Incomplete package: expected {length} bytes, received {count}.')
            os.replace(temporary, path)
            return dict(status='downloaded', file='files/'+path.name, bytes=count,
                        sha256=digest.hexdigest(), content_type=response.headers.get('Content-Type'))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as target:
            temporary = Path(target.name)
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def iso_date(value):
    if value is None or isinstance(value, str):
        return value
    return datetime.fromtimestamp(value/1000, timezone.utc).isoformat()


def save_report(output, report):
    atomic_json(output/'manifest.json', report)
    columns = ['surveyjobidpk', 'channel_id', 'usacedistrictcode', 'surveydatestart',
               'surveydateend', 'sdsfeaturename', 'sourceprojection', 'sourcedatalocation',
               'plotsheetlocation', 'status', 'file', 'bytes', 'sha256', 'error']
    with (output/'manifest.csv').open('w', newline='', encoding='utf-8') as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for survey in report['surveys']:
            writer.writerow({key: survey.get(key) for key in columns})


def run(args, session):
    output = args.output.expanduser().resolve()
    previous = {}
    if (output/'manifest.json').exists():
        previous = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if previous.get('tool') != TOOL or previous.get('format_version') != 1:
            raise RuntimeError('An unrelated manifest.json already exists in the output directory; preserving it.')
    elif any((output/name).exists() for name in ['manifest.csv', 'channels.csv']):
        raise RuntimeError('Report files already exist without this tool\'s manifest.json; use a dedicated output directory.')
    patterns = args.channel_pattern or [f'CE{code}_LM_*' for code in args.districts]
    candidates, where = discover_surveys(session, args.layer.rstrip('/'), args.districts,
                                        args.year, args.channel_field)
    counts = Counter(str(record.get(args.channel_field.lower()) or '(missing)') for record in candidates)
    selected = [record for record in candidates if matches_channel(record, patterns, args.channel_field)]
    output.mkdir(parents=True, exist_ok=True)
    with (output/'channels.csv').open('w', newline='', encoding='utf-8') as target:
        writer = csv.writer(target)
        writer.writerow(['channel_id', 'survey_count', 'matches_patterns'])
        for channel, count in sorted(counts.items()):
            matched = matches_channel({args.channel_field.lower(): channel}, patterns, args.channel_field)
            writer.writerow([channel, count, matched])
            if args.list_channels:
                print(f'{channel}: {count} surveys' + (' [matched]' if matched else ''))
    report = dict(tool=TOOL, format_version=1, checked_at_utc=datetime.now(timezone.utc).isoformat(),
                  layer=args.layer, year=args.year, districts=args.districts, where=where,
                  date_selection='survey start >= January 1 and < January 1 of the following year (UTC)',
                  channel_field=args.channel_field, channel_patterns=patterns,
                  candidate_count=len(candidates), matched_count=len(selected),
                  catalog_only=args.catalog_only or args.list_channels,
                  downloads=previous.get('downloads', {}), surveys=[])
    for record in selected:
        record = {**record, 'channel_id': record.get(args.channel_field.lower())}
        for field in ['surveydatestart', 'surveydateend']:
            record[field] = iso_date(record.get(field))
        record['sourcedatalocation'] = str(record.get('sourcedatalocation') or '').strip()
        record['status'] = ('catalog_only' if report['catalog_only'] else 'pending') if record['sourcedatalocation'] else 'missing_url'
        report['surveys'].append(record)
    save_report(output, report)
    print(f'{len(candidates)} district/year surveys; {len(selected)} match the channel patterns.')
    if not selected:
        print('No matching surveys. Inspect channels.csv or use --list-channels; '
              'confirm the channel field and identifiers before downloading.', file=sys.stderr)
        return 2
    urls = sorted({record['sourcedatalocation'] for record in report['surveys'] if record['sourcedatalocation']})
    missing = sum(record['status'] == 'missing_url' for record in report['surveys'])
    print(f'{len(urls)} distinct data-package URLs; {missing} surveys lack a data-package URL.')
    if report['catalog_only']:
        print(f'Catalog only; no package files downloaded. Reports: {output}')
        return 0
    files = output/'files'
    files.mkdir(exist_ok=True)
    failures = missing
    for number, url in enumerate(urls, 1):
        print(f'[{number}/{len(urls)}] {package_name(url)}', flush=True)
        try:
            result = download_package(session, url, files, report['downloads'].get(url))
        except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
            result = dict(status='failed', error=str(exc))
            failures += 1
            print(f'  Failed: {exc}', file=sys.stderr)
        report['downloads'][url] = result
        for record in report['surveys']:
            if record['sourcedatalocation'] == url:
                record.update(result)
        save_report(output, report)
    print(f'Finished: {len(urls)-(failures-missing)} verified packages; '
          f'{failures-missing} failed packages; {missing} missing URLs. Reports: {output}')
    return 1 if failures else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2025, help='Survey acquisition start year (default: 2025).')
    parser.add_argument('--districts', nargs='+', default=['MVK', 'MVM'], help='District codes (default: MVK MVM).')
    parser.add_argument('--channel-pattern', action='append', help='Repeatable shell-style channel pattern; '
                        'quote * to protect it from shell expansion. Defaults: CEMVK_LM_* and CEMVM_LM_*.')
    parser.add_argument('--channel-field', default='channelareaidfk', help='Channel ID field (default: channelareaidfk).')
    parser.add_argument('--output', type=Path, default=Path('output/ehydro_lmr_2025'), help='Directory for reports and packages.')
    parser.add_argument('--catalog-only', action='store_true', help='Write the selection and URLs without downloading packages.')
    parser.add_argument('--list-channels', action='store_true', help='List all district/year channel IDs; implies --catalog-only.')
    parser.add_argument('--layer', default=LAYER, help='Override the ArcGIS survey layer URL.')
    args = parser.parse_args(argv)
    if not 1900 <= args.year <= 9998:
        parser.error('--year must be between 1900 and 9998')
    args.districts = list(dict.fromkeys(code.upper() for code in args.districts))
    if not all(re.fullmatch(r'[A-Z]{3}', code) for code in args.districts):
        parser.error('--districts requires three-letter district codes')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', args.channel_field):
        parser.error('--channel-field must be a field name')
    if args.channel_pattern and any(not pattern.strip() for pattern in args.channel_pattern):
        parser.error('--channel-pattern must not be empty')
    if urlsplit(args.layer).scheme != 'https':
        parser.error('--layer must use HTTPS')
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        with session_with_retries() as session:
            return run(args, session)
    except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
        print(f'eHydro download failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
