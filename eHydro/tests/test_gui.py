import json
import threading
import time

import pytest
from PySide6.QtCore import Qt

from eHydro import download_ehydro as core
from eHydro.ehydro_gui import DownloadWindow
from eHydro.tests.test_download_ehydro import URL, Response, Session, args, survey


def wait(qapp, condition, seconds=10):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return
        time.sleep(.005)
    pytest.fail('GUI operation did not finish')


def choose_year(qapp, window, year=2025):
    window.refresh_years()
    wait(qapp, lambda: window.worker is None and window.available_years is not None)
    index = window.year.findData(year)
    assert index >= 0
    window.year.setCurrentIndex(index)
    wait(qapp, lambda: window.worker is None and window.report is not None)


def test_gui_reports_contents_checks_all_and_only_transfers_checked_files(qapp, tmp_path):
    other = 'https://data.example.test/other.zip'
    records = [dict(survey(1), sourcedatacontent='first.xyz,metadata.xml'), survey(2, url=other), survey(3, url=None)]
    session = Session(records, packages={URL: Response(headers={'Content-Length': '11'}), other: Response()})
    window = DownloadWindow(args(tmp_path), session_factory=lambda: session, auto_discover=False)
    try:
        window.show()
        choose_year(qapp, window)
        assert window.table.rowCount() == 3 and len(window.selected_urls()) == 2
        assert not any(url == URL or url == other for url, _ in session.calls)
        window.table.selectRow(0)
        qapp.processEvents()
        assert 'first.xyz' in window.details.toPlainText() and 'metadata.xml' in window.details.toPlainText()
        assert 'estimated time' in window.estimate_label.text()
        for row in range(window.table.rowCount()):
            if window.table.item(row, 0).data(Qt.UserRole) == other:
                window.table.item(row, 0).setCheckState(Qt.Unchecked)
        window.download_button.click()
        wait(qapp, lambda: window.worker is None)
        assert window.report['summary']['downloaded'] == 1
        assert not any(url == other for url, _ in session.calls)
        assert window.overall_progress.value() == 1000
        assert window.selected_urls() == {URL}
        session.calls.clear()
        window.download_button.click()
        wait(qapp, lambda: window.worker is None)
        assert window.report['summary']['skipped'] == 1
        assert not session.calls
        assert '0 need transfer' in window.estimate_label.text()
        window.destination.setText(str(tmp_path/'different-folder'))
        assert not window.download_button.isEnabled() and window.report is None
    finally:
        window.close()


class GatedResponse(Response):
    def __init__(self):
        super().__init__(chunks=(b'first', b'last'), headers={'Content-Length': '9'})
        self.started = threading.Event()
        self.release = threading.Event()

    def iter_content(self, chunk_size):
        yield b'first'
        self.started.set()
        if not self.release.wait(10):
            raise RuntimeError('test did not release the transfer')
        yield b'last'


def test_gui_shows_byte_progress_and_cancel_restart_skips_completed_packages(qapp, tmp_path):
    other = 'https://data.example.test/zzz.zip'
    gated = GatedResponse()
    session = Session([survey(1), survey(2, url=other)], packages={URL: Response(), other: gated})
    window = DownloadWindow(args(tmp_path), session_factory=lambda: session, auto_discover=False)
    try:
        window.show()
        choose_year(qapp, window)
        window.download_button.click()
        wait(qapp, gated.started.is_set)
        wait(qapp, lambda: 0 < window.file_progress.value() < 1000)
        assert 0 < window.overall_progress.value() < 1000
        assert 'ETA' in window.transfer_label.text()
        assert not window.settings.isEnabled() and window.stop_button.isEnabled()
        window.stop_button.click()
        gated.release.set()
        wait(qapp, lambda: window.worker is None)
        assert window.report['outcome'] == 'cancelled'
        assert window.report['summary']['downloaded'] == 1
        saved = json.loads((tmp_path/'manifest.json').read_text())
        assert saved['summary']['unfinished'] == 1
        assert not list((tmp_path/'files').glob('*.part'))
        session.calls.clear()
        session.packages[other] = Response(chunks=(b'firstlast',), headers={'Content-Length': '9'})
        window.download_button.click()
        wait(qapp, lambda: window.worker is None)
        assert window.report['summary']['skipped'] == 1 and window.report['summary']['downloaded'] == 1
        assert not any(url == URL for url, _ in session.calls)
        assert window.overall_progress.value() == 1000
    finally:
        gated.release.set()
        if window.worker is not None:
            window.stop()
            wait(qapp, lambda: window.worker is None)
        window.close()


def test_closing_active_window_cancels_then_waits_for_worker(qapp, tmp_path):
    gated = GatedResponse()
    session = Session([survey(1)], packages={URL: gated})
    window = DownloadWindow(args(tmp_path), session_factory=lambda: session, auto_discover=False)
    window.show()
    try:
        choose_year(qapp, window)
        window.download_button.click()
        wait(qapp, gated.started.is_set)
        window.close()
        assert window.worker is not None and window.worker.cancel_event.is_set()
        gated.release.set()
        wait(qapp, lambda: window.worker is None and not window.isVisible())
        assert window.report['outcome'] == 'cancelled'
    finally:
        gated.release.set()
        if window.worker is not None:
            window.stop()
            wait(qapp, lambda: window.worker is None)
        window.close()
