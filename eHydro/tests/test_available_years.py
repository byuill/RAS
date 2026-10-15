from datetime import datetime, timezone

import pytest

from eHydro import download_ehydro as core
from eHydro.ehydro_gui import DownloadWindow
from eHydro.tests.test_download_ehydro import LAYER, URL, Response, Session, args, survey
from eHydro.tests.test_gui import wait


def dated(oid, year, **changes):
    return {**survey(oid, url=f'https://data.example.test/{oid}.zip'),
            'surveydatestart': datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()*1000, **changes}


def test_years_are_real_channel_matches_with_links_not_an_inferred_continuous_range():
    records = [dated(1, 2016), dated(2, 2025), dated(3, 2025, sourcedatalocation='https://data.example.test/2.zip'),
               dated(4, 2026, channelareaidfk='CEMVM_LM_1', usacedistrictcode='CEMVM'),
               dated(5, 2020, channelareaidfk='CEMVK_YAZOO_1'),
               dated(6, 2012, sourcedatalocation=None), dated(7, 2024, surveydatestart=None)]
    session = Session(records)
    result = core.discover_available_years(session, LAYER, ['MVK', 'MVM'], ['CEMVK_LM_*', 'CEMVM_LM_*'])
    assert [item['year'] for item in result['years']] == [2026, 2025, 2016]
    assert result['years'][0]['districts'] == {'MVM': 1}
    assert result['years'][1]['packages'] == 1 and result['years'][1]['surveys'] == 2
    assert result['missing_urls'] == 1 and result['missing_dates'] == 1
    assert 'TIMESTAMP' not in result['where']
    assert not session.head_calls and not any(url.startswith('https://data.example.test/') for url, _ in session.calls)


def test_year_uses_acquisition_start_in_utc_and_reports_invalid_dates():
    records = [dated(1, 2025, surveydatestart='2025-12-31T23:30:00-02:00'),
               dated(2, 2025, surveydatestart='2025-01-01T00:30:00+02:00'),
               dated(3, 2025, surveydatestart='invalid'), dated(4, 2025, surveydatestart=False)]
    result = core.discover_available_years(Session(records), LAYER, ['MVK'], ['CEMVK_LM_*'])
    assert [item['year'] for item in result['years']] == [2026, 2024]
    assert result['missing_dates'] == 2


def test_full_year_discovery_bounds_get_url_batches_and_preserves_every_record():
    class LargeLayer(Session):
        def get(self, url, **kw):
            response = super().get(url, **kw)
            if url == LAYER:
                response.payload['maxRecordCount'] = 2000
            return response
    session = LargeLayer([dated(oid, 2025) for oid in range(205)])
    result = core.discover_available_years(session, LAYER, ['MVK'], ['CEMVK_LM_*'])
    batches = [kw['params']['objectIds'].split(',') for _, kw in session.calls if 'objectIds' in kw.get('params', {})]
    assert [len(batch) for batch in batches] == [100, 100, 5]
    assert result['years'][0]['packages'] == 205
    assert result['matching_surveys'] == 205


def test_empty_and_cancelled_year_discovery_do_not_create_an_available_year():
    assert core.discover_available_years(Session([]), LAYER, ['MVK'], ['CEMVK_LM_*'])['years'] == []
    with pytest.raises(core.DownloadCancelled):
        core.discover_available_years(Session([dated(1, 2025)]), LAYER, ['MVK'], ['CEMVK_LM_*'], cancelled=lambda: True)


def test_list_years_cli_is_metadata_only(tmp_path, capsys):
    session = Session([dated(1, 2016), dated(2, 2025)])
    assert core.run(args(tmp_path, '--list-years'), session) == 0
    assert '2016: 1 packages (MVK: 1)' in capsys.readouterr().out
    assert not list(tmp_path.iterdir()) and not session.head_calls


def test_gui_requires_year_selection_and_filters_files_after_choice(qapp, tmp_path):
    records = [dated(1, 2016), dated(2, 2025), dated(3, 2026)]
    session = Session(records, packages={record['sourcedatalocation']: Response() for record in records})
    window = DownloadWindow(args(tmp_path), session_factory=lambda: session, auto_discover=False)
    try:
        window.show()
        window.refresh_years()
        wait(qapp, lambda: window.worker is None and window.available_years is not None)
        assert [window.year.itemData(i) for i in range(1, window.year.count())] == [2026, 2025, 2016]
        assert window.year.currentData() is None and window.table.rowCount() == 0
        assert not window.download_button.isEnabled() and not session.head_calls
        assert '2016 (1)' in window.years_label.text()
        window.year.setCurrentIndex(window.year.findData(2016))
        wait(qapp, lambda: window.worker is None and window.report is not None)
        assert window.report['year'] == 2016 and window.table.rowCount() == 1
        assert window.selected_urls() == {'https://data.example.test/1.zip'}
        assert window.destination.text() == str(tmp_path)
        window.year.setCurrentIndex(window.year.findData(2025))
        assert not window.download_button.isEnabled()
        wait(qapp, lambda: window.worker is None and window.report is not None)
        assert window.report['year'] == 2025
        assert window.selected_urls() == {'https://data.example.test/2.zip'}
        window.patterns.setText('CEMVK_OTHER_*')
        assert window.year.count() == 1 and window.year.currentData() is None
        assert not window.find_button.isEnabled() and not window.download_button.isEnabled()
        window.refresh_years()
        wait(qapp, lambda: window.worker is None and window.available_years is not None)
        assert not window.available_years['years'] and not window.year.isEnabled()
    finally:
        if window.worker is not None:
            window.stop()
            wait(qapp, lambda: window.worker is None)
        window.close()


def test_gui_default_destination_tracks_selected_year_but_manual_folder_is_preserved(qapp, tmp_path):
    options = core.parse_args([])
    window = DownloadWindow(options, auto_discover=False)
    try:
        window._show_years(dict(years=[dict(year=2016, packages=1, districts={'MVK': 1})], missing_dates=0, missing_urls=0))
        # Keep the test focused on destination changes; file lookup is exercised above.
        window.discover = lambda: None
        window.year.setCurrentIndex(window.year.findData(2016))
        assert window.destination.text().endswith('output/ehydro_lmr_2016')
        window.destination.setText(str(tmp_path))
        window.destination.textEdited.emit(str(tmp_path))
        window.year.setCurrentIndex(0)
        window.year.setCurrentIndex(window.year.findData(2016))
        assert window.destination.text() == str(tmp_path)
        qapp.processEvents()
    finally:
        window.close()
