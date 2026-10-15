"""Download eHydro packages; GUI discovers years, headless defaults to MVK/MVM, 2025.

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
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LAYER = ('https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/'
         'eHydro_Survey_Data/FeatureServer/0')
TOOL = 'ras-ehydro-downloader'


class DownloadCancelled(RuntimeError):
    """Cooperative cancellation; completed packages remain usable."""


def check_cancel(cancelled):
    if cancelled and cancelled():
        raise DownloadCancelled('Download stopped by the user.')


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


def discover_surveys(session, layer, districts, year, channel_field, cancelled=None):
    """Fetch all candidate IDs, then attributes in batches, avoiding page truncation."""
    check_cancel(cancelled)
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
    where = f'{district_field} IN ({codes})'
    if year is not None:
        where += (f" AND {date_field} >= TIMESTAMP '{year}-01-01 00:00:00' AND "
                  f"{date_field} < TIMESTAMP '{year+1}-01-01 00:00:00'")
    check_cancel(cancelled)
    selection = api_json(session, layer+'/query', where=where, returnIdsOnly='true')
    if 'objectIds' not in selection:
        raise RuntimeError('ArcGIS did not return objectIds; refusing to treat this as an empty selection.')
    ids = sorted(set(selection['objectIds'] or []))
    oid_field = selection.get('objectIdFieldName') or schema.get('objectIdField')
    if not oid_field:
        raise RuntimeError('Survey layer has no object ID field.')
    oid_field = oid_field.lower()
    # Keep GET URLs below common proxy/server length limits as well as the
    # ArcGIS record limit; 500 encoded object IDs can otherwise return HTTP 404.
    size = max(1, min(100, int(schema.get('maxRecordCount', 100))))

    def fetch_batch(batch):
        check_cancel(cancelled)
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


def discover_available_years(session, layer, districts, patterns, channel_field='channelareaidfk', cancelled=None):
    """Find actual acquisition years for matching channels with data-package links.

    Fetch the complete district index in checked batches rather than extrapolating
    a continuous year range from the earliest/latest date. No archives or size
    probes are needed until the user chooses a year.
    """
    records, where = discover_surveys(session, layer.rstrip('/'), districts, None, channel_field, cancelled)
    years = {}
    missing_dates = missing_urls = matched = 0
    for record in records:
        check_cancel(cancelled)
        if not matches_channel(record, patterns, channel_field):
            continue
        matched += 1
        url = str(record.get('sourcedatalocation') or '').strip()
        if not url:
            missing_urls += 1
            continue
        value = record.get('surveydatestart')
        try:
            if value is None or isinstance(value, bool):
                raise ValueError('Missing survey acquisition start date')
            if isinstance(value, (int, float)):
                date = datetime.fromtimestamp(value/1000, timezone.utc)
            else:
                date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                date = date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError, OSError):
            missing_dates += 1
            continue
        year = years.setdefault(date.year, {'urls': set(), 'districts': {}, 'surveys': 0})
        year['urls'].add(url)
        year['surveys'] += 1
        district = str(record.get('usacedistrictcode') or '').upper().removeprefix('CE')
        year['districts'].setdefault(district, set()).add(url)
    return dict(years=[dict(year=year, packages=len(info['urls']), surveys=info['surveys'],
                            districts={district: len(urls) for district, urls in sorted(info['districts'].items())})
                       for year, info in sorted(years.items(), reverse=True)],
                where=where, matching_surveys=matched, missing_dates=missing_dates, missing_urls=missing_urls)


def sha256_file(path, cancelled=None):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            check_cancel(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def package_name(url):
    # URL hashes distinguish archives with identical names; no server-provided path is used.
    leaf = unquote(urlsplit(url).path.rsplit('/', 1)[-1]) or 'survey-data'
    leaf = re.sub(r'[^A-Za-z0-9._-]', '_', leaf)[-120:].strip('.') or 'survey-data'
    return hashlib.sha256(url.encode()).hexdigest()[:24] + '_' + leaf


def existing_package(url, directory, previous=None, cancelled=None):
    """Verify a completed file using the manifest or an independent durable receipt."""
    path = directory/package_name(url)
    if not path.exists():
        return None
    candidates = [previous] if previous else []
    receipt = path.with_name(path.name+'.download.json')
    if receipt.exists():
        try:
            saved = json.loads(receipt.read_text(encoding='utf-8'))
            if saved.get('tool') == TOOL and saved.get('url') == url:
                candidates.append(saved['result'])
        except (ValueError, KeyError):
            pass
    digest = None
    for saved in candidates:
        if (saved.get('status') in {'downloaded', 'verified_existing'}
                and path.stat().st_size == saved.get('bytes')):
            digest = digest or sha256_file(path, cancelled)
            if digest == saved.get('sha256'):
                return {**saved, 'status': 'verified_existing', 'file': 'files/'+path.name}
    raise RuntimeError(f'Existing file is not verified by the manifest or receipt; preserving {path.name}. '
                       'Move it aside before retrying.')


def download_package(session, url, directory, previous=None, progress=None, cancelled=None):
    """Stream to a temporary file and promote only complete, nonempty downloads."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError('Expected a public HTTPS data-package URL without embedded credentials.')
    path = directory/package_name(url)
    check_cancel(cancelled)
    if progress:
        progress(0, None, 'verifying')
    existing = existing_package(url, directory, previous, cancelled)
    if existing:
        return existing
    temporary = None
    try:
        with session.get(url, stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            if 'text/html' in response.headers.get('Content-Type', '').lower():
                raise RuntimeError('The package URL returned an HTML page instead of survey data.')
            digest, count = hashlib.sha256(), 0
            length = response.headers.get('Content-Length')
            # iter_content returns decompressed bytes; encoded lengths are not comparable.
            total = int(length) if length and response.headers.get('Content-Encoding', 'identity') == 'identity' else None
            if progress:
                progress(0, total, 'downloading')
            with tempfile.NamedTemporaryFile(dir=directory, prefix=path.name+'.', suffix='.part', delete=False) as target:
                temporary = Path(target.name)
                for chunk in response.iter_content(chunk_size=1024*1024):
                    check_cancel(cancelled)
                    if chunk:
                        if count == 0 and chunk.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                            raise RuntimeError('The package URL returned HTML instead of survey data.')
                        target.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                        if progress:
                            progress(count, total, 'downloading')
            if not count:
                raise RuntimeError('The package URL returned an empty file.')
            if total is not None and total != count:
                raise RuntimeError(f'Incomplete package: expected {total} bytes, received {count}.')
            check_cancel(cancelled)
            result = dict(status='downloaded', file='files/'+path.name, bytes=count,
                          sha256=digest.hexdigest(), content_type=response.headers.get('Content-Type'))
            # Write the receipt BEFORE promoting the file: a hard stop between promotion
            # and the main manifest update can then recover without a second transfer.
            atomic_json(path.with_name(path.name+'.download.json'), dict(tool=TOOL, url=url, result=result))
            os.replace(temporary, path)
            return result
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
               'sourcedatacontent', 'plotsheetlocation', 'size_bytes', 'status', 'file', 'bytes', 'sha256', 'error']
    with (output/'manifest.csv').open('w', newline='', encoding='utf-8') as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for survey in report['surveys']:
            row = {**survey, 'size_bytes': report.get('package_info', {}).get(survey.get('sourcedatalocation'), {}).get('size_bytes')}
            writer.writerow({key: row.get(key) for key in columns})


def prepare_report(args, session, cancelled=None):
    output = args.output.expanduser().resolve()
    previous = {}
    if (output/'manifest.json').exists():
        previous = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        if previous.get('tool') != TOOL or previous.get('format_version') != 1:
            raise RuntimeError('An unrelated manifest.json already exists in the output directory; preserving it.')
    elif any((output/name).exists() for name in ['manifest.csv', 'channels.csv']):
        # Receipts also establish that these reports belong to an earlier run,
        # allowing recovery if the main manifest was lost after files completed.
        owned = False
        for receipt in (output/'files').glob('*.download.json'):
            try:
                saved = json.loads(receipt.read_text(encoding='utf-8'))
                if isinstance(saved, dict) and saved.get('tool') == TOOL and saved.get('url') and saved.get('result'):
                    owned = True
                    break
            except (ValueError, OSError):
                continue
        if not owned:
            raise RuntimeError('Report files already exist without this tool\'s manifest.json or receipts; use a dedicated output directory.')
    patterns = args.channel_pattern or [f'CE{code}_LM_*' for code in args.districts]
    candidates, where = discover_surveys(session, args.layer.rstrip('/'), args.districts,
                                        args.year, args.channel_field, cancelled)
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
    return report


def package_inventory(report):
    """One row per distinct archive URL, retaining every survey's file list."""
    packages = {}
    for survey in report['surveys']:
        url = survey.get('sourcedatalocation')
        key = url or 'missing:'+str(survey.get('objectid', survey.get('surveyjobidpk')))
        if key not in packages:
            packages[key] = dict(url=url, filename=unquote(urlsplit(url).path.rsplit('/', 1)[-1]) if url else 'No data-package URL',
                                 surveys=[], **report.get('package_info', {}).get(url, {}))
        packages[key]['surveys'].append(survey)
    return list(packages.values())


def inspect_packages(report, output, session, notify=None, cancelled=None):
    """Inspect sizes and existing files without downloading survey payloads."""
    packages = package_inventory(report)
    info = report.setdefault('package_info', {})
    for index, package in enumerate(packages, 1):
        check_cancel(cancelled)
        url = package['url']
        if notify:
            notify(dict(kind='inventory', index=index, count=len(packages), filename=package['filename']))
        if not url:
            continue
        result = dict(size_bytes=None, local_status='ready')
        try:
            existing = existing_package(url, output/'files', report['downloads'].get(url), cancelled)
            if existing:
                result.update(size_bytes=existing['bytes'], local_status='verified_existing')
                report['downloads'][url] = existing
            else:
                response = session.head(url, timeout=(15, 30), allow_redirects=True)
                try:
                    response.raise_for_status()
                    length = response.headers.get('Content-Length')
                    if length is not None and response.headers.get('Content-Encoding', 'identity') == 'identity':
                        result['size_bytes'] = int(length)
                finally:
                    response.close()
        except DownloadCancelled:
            raise
        except (requests.RequestException, RuntimeError, OSError, ValueError) as exc:
            result['inspection_error'] = str(exc)
            result['local_status'] = 'needs_review' if (output/'files'/package_name(url)).exists() else 'size_unknown'
        info[url] = result
    save_report(output, report)
    return package_inventory(report)


def download_selection(report, urls, output, session, notify=None, cancelled=None):
    try:
        from .transfer_progress import TransferMeter
    except ImportError:
        from transfer_progress import TransferMeter
    urls = sorted(set(urls))
    available = {record['sourcedatalocation'] for record in report['surveys'] if record['sourcedatalocation']}
    if not set(urls) <= available:
        raise ValueError('Selection contains a URL outside the discovered catalog.')
    files = output/'files'
    files.mkdir(exist_ok=True)
    report.update(selected_urls=urls, catalog_only=False, outcome='downloading')
    for record in report['surveys']:
        if record['sourcedatalocation'] and record['sourcedatalocation'] not in urls:
            record['status'] = 'not_selected'
    sizes = {url: report.get('package_info', {}).get(url, {}).get('size_bytes') for url in urls}
    meter = TransferMeter(sizes)
    completed = skipped = failures = 0
    was_cancelled = False
    save_report(output, report)
    for number, url in enumerate(urls, 1):
        def progress(received, total, phase):
            event = meter.update(url, received, total, phase)
            if notify:
                notify(event)
        try:
            check_cancel(cancelled)
            result = download_package(session, url, files, report['downloads'].get(url), progress, cancelled)
            skipped += result['status'] == 'verified_existing'
            completed += result['status'] == 'downloaded'
        except DownloadCancelled:
            was_cancelled = True
            result = dict(status='cancelled')
        except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
            result = dict(status='failed', error=str(exc))
            failures += 1
        if result['status'] != 'cancelled':
            report['downloads'][url] = result
        if result['status'] in {'downloaded', 'verified_existing'}:
            report.setdefault('package_info', {}).setdefault(url, {}).update(
                size_bytes=result['bytes'], local_status='verified_existing')
        for record in report['surveys']:
            if record['sourcedatalocation'] == url:
                for field in ['error', 'file', 'bytes', 'sha256', 'content_type']:
                    record.pop(field, None)
                record.update(result)
        save_report(output, report)
        event = meter.finish(url, result)
        if notify:
            notify({**event, 'index': number, 'count': len(urls), 'result': result})
        if was_cancelled:
            break
    report['outcome'] = 'cancelled' if was_cancelled else 'completed_with_errors' if failures else 'completed'
    report['summary'] = dict(downloaded=completed, skipped=skipped, failed=failures, cancelled=was_cancelled,
                             selected=len(urls), unfinished=len(urls)-completed-skipped-failures)
    save_report(output, report)
    return report


def run(args, session):
    if args.list_years:
        patterns = args.channel_pattern or [f'CE{code}_LM_*' for code in args.districts]
        available = discover_available_years(session, args.layer, args.districts, patterns, args.channel_field)
        print('Available survey acquisition years (distinct data packages):')
        for item in available['years']:
            counts = ', '.join(f'{district}: {count}' for district, count in item['districts'].items())
            print(f'{item["year"]}: {item["packages"]} packages ({counts})')
        print(f'{available["missing_urls"]} matching surveys lack package links; '
              f'{available["missing_dates"]} linked surveys lack usable acquisition dates.')
        return 0 if available['years'] else 2
    report = prepare_report(args, session)
    output = args.output.expanduser().resolve()
    print(f'{report["candidate_count"]} district/year surveys; {report["matched_count"]} match the channel patterns.')
    packages = package_inventory(report)
    # Report every matching package and its contents before starting any transfers.
    for package in packages:
        print(package['filename'])
        print('  URL:', package['url'] or '(missing)')
        for survey in package['surveys']:
            print('  Includes:', survey.get('sourcedatacontent') or '(contents not listed by USACE)')
    if not report['surveys']:
        print('No matching surveys. Inspect channels.csv or use --list-channels; '
              'confirm the channel field and identifiers before downloading.', file=sys.stderr)
        return 2
    missing = sum(not package['url'] for package in packages)
    if report['catalog_only']:
        print(f'Catalog only; no package files downloaded. Reports: {output}')
        return 0
    inspected = inspect_packages(report, output, session, notify=console_progress)
    pending = [p for p in inspected if p['url'] and p.get('local_status') != 'verified_existing']
    size = sum(p.get('size_bytes') or 0 for p in pending)
    unknown = sum(p.get('size_bytes') is None for p in pending)
    try:
        from .transfer_progress import format_duration, format_size
    except ImportError:
        from transfer_progress import format_duration, format_size
    print(f'{format_size(size)} known bytes remain; {unknown} sizes unknown. '
          f'Planning time {format_duration(size/(args.estimate_mbps*1e6/8))} '
          f'at assumed {args.estimate_mbps:g} Mbps' + (' (lower bound).' if unknown else '.'))
    report = download_selection(report, [p['url'] for p in packages if p['url']], output, session,
                                notify=console_progress)
    print(f'Finished: {report["summary"]}; {missing} missing URLs. Reports: {output}')
    return 1 if missing or report['summary']['failed'] else 0


def console_progress(event):
    try:
        from .transfer_progress import format_duration, format_size
    except ImportError:
        from transfer_progress import format_duration, format_size
    if event['kind'] == 'inventory':
        if event['index'] == 1 or event['index'] % 25 == 0 or event['index'] == event['count']:
            print(f'Checking sizes/local files: {event["index"]}/{event["count"]}', file=sys.stderr)
    elif event['kind'] == 'result':
        print(f'{event["result"]["status"]}: {package_name(event["url"])}', flush=True)
    elif event['phase'] == 'downloading':
        now = time.monotonic()
        if now-console_progress.last_update >= 1:
            print(f'{event["processed"]}/{event["count"]} packages processed; '
                  f'{format_size(event["network_bytes"])} transferred; ETA {format_duration(event["eta"])}',
                  file=sys.stderr, flush=True)
            console_progress.last_update = now


console_progress.last_update = 0.


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
    parser.add_argument('--list-years', action='store_true', help='Report all acquisition years with package links for the district/channel filters, without downloading.')
    parser.add_argument('--layer', default=LAYER, help='Override the ArcGIS survey layer URL.')
    parser.add_argument('--estimate-mbps', type=float, default=50., help='Assumed connection speed in megabits/s for the initial estimate (default: 50).')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gui', action='store_true', help='Open the selection/progress GUI (default unless catalog-only or headless).')
    mode.add_argument('--headless', action='store_true', help='Download every match without opening the GUI.')
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
    if not math.isfinite(args.estimate_mbps) or args.estimate_mbps <= 0:
        parser.error('--estimate-mbps must be positive and finite')
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.gui or not (args.headless or args.catalog_only or args.list_channels or args.list_years):
        try:
            if __package__:
                from .ehydro_gui import launch
            else:
                from ehydro_gui import launch
            return launch(args)
        except ImportError as exc:
            print(f'GUI dependencies unavailable: {exc}. Install PySide6 or use --headless.', file=sys.stderr)
            return 1
    try:
        with session_with_retries() as session:
            return run(args, session)
    except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
        print(f'eHydro download failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
