import threading

import pytest
import requests

from eHydro import download_ehydro as core
from eHydro.transfer_progress import TransferMeter
from eHydro.tests.test_download_ehydro import LAYER, URL, Response, Session, args, survey


def test_receipt_recovers_completed_file_without_main_manifest(tmp_path):
    first = Session([])
    completed = core.download_package(first, URL, tmp_path)
    assert (tmp_path/(core.package_name(URL)+'.download.json')).exists()
    fresh = Session([])
    result = core.download_package(fresh, URL, tmp_path, previous={'status': 'failed'})
    assert result['sha256'] == completed['sha256'] and result['status'] == 'verified_existing'
    assert not fresh.calls


def test_complete_job_recovers_with_csv_reports_but_missing_main_manifest(tmp_path):
    session = Session([survey(1)])
    assert core.run(args(tmp_path), session) == 0
    (tmp_path/'manifest.json').unlink()
    session.calls.clear()
    assert core.run(args(tmp_path), session) == 0
    assert not any(url == URL for url, _ in session.calls)


def test_unknown_head_size_does_not_prevent_transfer(tmp_path):
    class NoHead(Session):
        def head(self, *a, **kw):
            return Response()
    session = NoHead([survey(1)])
    report = core.prepare_report(args(tmp_path), session)
    packages = core.inspect_packages(report, tmp_path, session)
    assert packages[0]['size_bytes'] is None
    result = core.download_selection(report, [URL], tmp_path, session)
    assert result['summary']['downloaded'] == 1


def test_retry_clears_previous_error_and_updates_local_inventory(tmp_path):
    session = Session([survey(1)], packages={URL: requests.ConnectionError('temporary outage')})
    report = core.prepare_report(args(tmp_path), session)
    core.download_selection(report, [URL], tmp_path, session)
    assert report['surveys'][0]['status'] == 'failed' and report['surveys'][0]['error']
    session.packages[URL] = Response()
    core.download_selection(report, [URL], tmp_path, session)
    assert report['surveys'][0]['status'] == 'downloaded' and 'error' not in report['surveys'][0]
    assert core.package_inventory(report)[0]['local_status'] == 'verified_existing'


def test_selection_preserves_unchecked_files_and_records_progress(tmp_path):
    other = 'https://data.example.test/other.zip'
    session = Session([survey(1), survey(2, url=other)],
                      packages={URL: Response(chunks=(b'ab', b'cdef'), headers={'Content-Length': '6'}),
                                other: Response()})
    report = core.prepare_report(args(tmp_path), session)
    events = []
    report = core.download_selection(report, [URL, URL], tmp_path, session, events.append)
    assert report['summary'] == dict(downloaded=1, skipped=0, failed=0, cancelled=False, selected=1, unfinished=0)
    assert report['surveys'][1]['status'] == 'not_selected'
    assert not any(url == other for url, _ in session.calls)
    updates = [e for e in events if e['phase'] == 'downloading']
    assert [e['file_bytes'] for e in updates] == [0, 2, 6]
    assert updates[-1]['file_total'] == 6 and events[-1]['fraction'] == 1
    with pytest.raises(ValueError, match='outside'):
        core.download_selection(report, ['https://other.test/unlisted.zip'], tmp_path, session)


def test_cancel_during_transfer_cleans_partial_file_and_saves_completed_receipt(tmp_path):
    stop = threading.Event()
    other = 'https://data.example.test/zzz.zip'
    session = Session([survey(1), survey(2, url=other)],
                      packages={URL: Response(), other: Response(chunks=(b'first', b'second'))})
    report = core.prepare_report(args(tmp_path), session)

    def notify(event):
        if event['url'] == other and event['file_bytes'] > 0:
            stop.set()

    result = core.download_selection(report, [URL, other], tmp_path, session, notify, stop.is_set)
    assert result['outcome'] == 'cancelled'
    assert result['summary']['downloaded'] == 1 and result['summary']['unfinished'] == 1
    assert not list((tmp_path/'files').glob('*.part'))
    assert not (tmp_path/'files'/core.package_name(other)).exists()
    session.calls.clear()
    resumed = core.download_selection(result, [URL, other], tmp_path, session)
    assert resumed['summary']['downloaded'] == 1 and resumed['summary']['skipped'] == 1
    assert not any(url == URL for url, _ in session.calls)


def test_estimates_account_for_skips_and_unknown_sizes_without_fabricated_eta():
    clock = [0.]
    meter = TransferMeter({'one': 100, 'two': 300}, clock=lambda: clock[0])
    clock[0] = 1.
    event = meter.update('one', 50, 100, 'downloading')
    assert event['rate'] == 50 and event['eta'] == 7
    event = meter.finish('two', dict(status='verified_existing', bytes=300))
    assert event['network_bytes'] == 50 and event['eta'] == 1
    assert event['fraction'] == pytest.approx(.875)
    event = meter.finish('one', dict(status='downloaded', bytes=100))
    assert event['eta'] == 0 and event['fraction'] == 1 and event['processed'] == 2

    unknown = TransferMeter({'one': None, 'two': 100}, clock=lambda: clock[0])
    clock[0] = 2.
    event = unknown.update('one', 10, None, 'downloading')
    assert event['eta'] is None and event['unknown_sizes'] == 1
    event = unknown.finish('one', dict(status='cancelled'))
    assert event['processed'] == 0 and event['fraction'] == 0


def test_default_gui_and_explicit_headless_can_use_same_arguments():
    assert core.parse_args([]).gui is False and core.parse_args([]).headless is False
    assert core.parse_args(['--headless']).headless
    with pytest.raises(SystemExit):
        core.parse_args(['--estimate-mbps', 'nan'])
