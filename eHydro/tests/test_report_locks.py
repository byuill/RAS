"""Simulate Windows access/sharing locks without weakening file integrity checks."""
import errno
import json
from pathlib import Path

import pytest

from eHydro import download_ehydro as core
from eHydro.ehydro_gui import DownloadWindow
from eHydro.tests.test_download_ehydro import URL, Response, Session, args, survey
from eHydro.tests.test_gui import choose_year, wait


def access_denied(winerror=5):
    error = PermissionError(errno.EACCES, 'Access is denied')
    error.winerror = winerror
    return error


@pytest.mark.parametrize('winerror', [5, 32, 33])
def test_atomic_json_retries_windows_locks_preserving_old_file_until_success(tmp_path, monkeypatch, winerror):
    path = tmp_path/'manifest.json'
    path.write_text('{"old": true}')
    original = core.os.replace
    attempts = []

    def replace(source, destination):
        attempts.append((source, destination))
        # The temporary writer must be closed and its complete contents readable.
        assert json.loads(Path(source).read_text()) == {'new': True}
        assert json.loads(path.read_text()) == {'old': True}
        if len(attempts) < 3:
            raise access_denied(winerror)
        return original(source, destination)

    monkeypatch.setattr(core, 'REPLACE_RETRY_DELAYS', (0, 0))
    monkeypatch.setattr(core.os, 'replace', replace)
    core.atomic_json(path, {'new': True})
    assert len(attempts) == 3 and json.loads(path.read_text()) == {'new': True}
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('locked', [{'manifest.json'}, {'manifest.csv'}, {'manifest.json', 'manifest.csv'}])
def test_locked_reports_do_not_abort_packages_and_latest_snapshot_can_resume(tmp_path, monkeypatch, locked):
    other = 'https://data.example.test/zzz.zip'
    session = Session([survey(1), survey(2, url=other)], packages={URL: Response(), other: Response()})
    report = core.prepare_report(args(tmp_path), session)
    before = {name: (tmp_path/name).read_bytes() for name in locked}
    original = core.os.replace

    def replace(source, destination):
        if Path(destination).parent == tmp_path and Path(destination).name in locked:
            raise access_denied()
        return original(source, destination)

    monkeypatch.setattr(core, 'REPLACE_RETRY_DELAYS', (0,))
    monkeypatch.setattr(core.os, 'replace', replace)
    events = []
    core.download_selection(report, [URL, other], tmp_path, session, events.append)
    assert report['summary']['downloaded'] == 2 and report['outcome'] == 'completed'
    assert set(report['report_warnings']) == locked
    assert any(event['kind'] == 'report_warning' for event in events)
    for name, contents in before.items():
        assert (tmp_path/name).read_bytes() == contents
    if 'manifest.json' in locked:
        snapshot = core.load_previous_report(tmp_path)
        assert snapshot['summary']['downloaded'] == 2 and len(snapshot['downloads']) == 2
        assert (tmp_path/snapshot['recovery_manifest']).exists()
    # Prove restart recovery works through the saved report, not only receipts.
    for receipt in (tmp_path/'files').glob('*.download.json'):
        receipt.unlink()
    session.calls.clear()
    resumed = core.prepare_report(args(tmp_path), session)
    core.download_selection(resumed, [URL, other], tmp_path, session)
    assert resumed['summary']['skipped'] == 2 and resumed['summary']['downloaded'] == 0
    assert not any(url in {URL, other} for url, _ in session.calls)
    # Releasing the locks updates the main files and clears stale warning badges.
    monkeypatch.setattr(core.os, 'replace', original)
    core.save_report(tmp_path, resumed)
    assert not resumed['report_warnings'] and 'recovery_manifest' not in resumed
    assert core.load_previous_report(tmp_path)['summary']['skipped'] == 2


def test_csv_open_during_discovery_preserves_existing_export_and_reports_warning(tmp_path, monkeypatch):
    session = Session([survey(1)])
    core.prepare_report(args(tmp_path), session)
    path = tmp_path/'channels.csv'
    before = path.read_bytes()
    original = core.os.replace

    def replace(source, destination):
        if Path(destination) == path:
            raise access_denied(32)
        return original(source, destination)

    monkeypatch.setattr(core, 'REPLACE_RETRY_DELAYS', ())
    monkeypatch.setattr(core.os, 'replace', replace)
    report = core.prepare_report(args(tmp_path), session)
    assert path.read_bytes() == before
    assert 'channels.csv' in report['report_warnings']
    assert json.loads((tmp_path/'manifest.json').read_text())['report_warnings']['channels.csv']


def test_receipts_preserve_recovery_when_all_central_json_replacements_are_denied(tmp_path, monkeypatch):
    session = Session([survey(1)])
    report = core.prepare_report(args(tmp_path), session)
    original = core.os.replace

    def replace(source, destination):
        if Path(destination).parent == tmp_path and Path(destination).suffix == '.json':
            raise access_denied()
        return original(source, destination)

    monkeypatch.setattr(core, 'REPLACE_RETRY_DELAYS', ())
    monkeypatch.setattr(core.os, 'replace', replace)
    core.download_selection(report, [URL], tmp_path, session)
    assert report['summary']['downloaded'] == 1
    assert 'recovery snapshot also could not be saved' in report['report_warnings']['manifest.json']
    assert 'recovery_manifest' not in report
    assert list((tmp_path/'files').glob('*.download.json'))
    session.calls.clear()
    report = core.prepare_report(args(tmp_path), session)
    core.download_selection(report, [URL], tmp_path, session)
    assert report['summary']['skipped'] == 1
    assert not any(url == URL for url, _ in session.calls)


def test_disk_full_is_not_misclassified_as_a_file_lock(tmp_path, monkeypatch):
    session = Session([survey(1)])
    report = core.prepare_report(args(tmp_path), session)
    original = core.os.replace

    def replace(source, destination):
        if Path(destination).name == 'manifest.json':
            raise OSError(errno.ENOSPC, 'No space left on device')
        return original(source, destination)

    monkeypatch.setattr(core.os, 'replace', replace)
    with pytest.raises(OSError) as error:
        core.save_report(tmp_path, report)
    assert error.value.errno == errno.ENOSPC
    assert not list(tmp_path.glob('manifest-recovery-*.json'))


def test_invalid_recovery_snapshot_is_ignored_and_unrelated_primary_is_preserved(tmp_path):
    report = core.prepare_report(args(tmp_path), Session([survey(1)]))
    bad = tmp_path/'manifest-recovery-invalid.json'
    bad.write_text('{"tool": "ras-ehydro-downloader", "format_version": 1, "saved_at_utc": {}, "downloads": {}, "surveys": []}')
    assert core.load_previous_report(tmp_path)['checked_at_utc'] == report['checked_at_utc']
    primary = tmp_path/'manifest.json'
    primary.write_text('{"user": "keep"}')
    with pytest.raises(RuntimeError, match='unrelated manifest'):
        core.load_previous_report(tmp_path)
    assert primary.read_text() == '{"user": "keep"}'


def test_gui_continues_after_manifest_becomes_locked_mid_download(qapp, tmp_path, monkeypatch):
    other = 'https://data.example.test/zzz.zip'
    session = Session([survey(1), survey(2, url=other)], packages={URL: Response(), other: Response()})
    window = DownloadWindow(args(tmp_path), session_factory=lambda: session, auto_discover=False)
    try:
        window.show()
        choose_year(qapp, window)
        original = core.os.replace
        promoted = []

        def replace(source, destination):
            destination = Path(destination)
            if destination.name == 'manifest.json' and promoted:
                raise access_denied()
            result = original(source, destination)
            if destination.suffix == '.zip':
                promoted.append(destination)
            return result

        monkeypatch.setattr(core, 'REPLACE_RETRY_DELAYS', (0,))
        monkeypatch.setattr(core.os, 'replace', replace)
        window.download_button.click()
        wait(qapp, lambda: window.worker is None)
        assert len(promoted) == 2 and window.report['summary']['downloaded'] == 2
        assert 'Report saving needs attention' in window.status.text()
        assert 'Report warning:' in window.log.toPlainText()
        assert 'Operation failed' not in window.status.text()
        assert window.overall_progress.value() == 1000
    finally:
        if window.worker is not None:
            window.stop()
            wait(qapp, lambda: window.worker is None)
        window.close()
