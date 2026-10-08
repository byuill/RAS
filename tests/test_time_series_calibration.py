import numpy as np
import pandas as pd
import pytest

from analysis.time_series_calibration import (build_comparison, comparison_statistics,
    fit_transport_function, sediment_records)


@pytest.mark.parametrize('form,degree,expected', [
    ('linear', 2, lambda q: 3*q + 7),
    ('power', 2, lambda q: 2*q**1.4),
    ('logarithmic', 2, lambda q: 4*np.log(q) + 10),
    ('polynomial', 3, lambda q: .02*q**3 - .1*q**2 + 2*q + 10),
])
def test_transport_functions_recover_known_relations(form, degree, expected):
    q = np.linspace(1, 20, 30)
    fit = fit_transport_function(q, expected(q), form, degree)
    np.testing.assert_allclose(fit.predict(q), expected(q), rtol=1e-12)
    assert fit.r2 == pytest.approx(1)
    assert fit.summary()['degree'] == (degree if form == 'polynomial' else 1)
    assert np.isnan(fit.predict([0, -1, .5, 21, np.nan])).all()
    np.testing.assert_allclose(fit.predict([.5, 21], extrapolate=True), expected(np.array([.5, 21])), rtol=1e-12)


def test_fits_report_exclusions_degeneracy_smearing_and_negative_predictions():
    q = np.arange(1., 13.)
    residual = np.array([.4, -.4]*6)
    y = 2*q**1.3*np.exp(residual)
    fit = fit_transport_function(np.r_[q, 0, 1, np.nan], np.r_[y, 0, -1, 2])
    assert fit.n_used == 12 and fit.n_total == 15 and fit.smearing_factor > 1
    np.testing.assert_allclose(fit.predict(q, smear=True), fit.predict(q)*fit.smearing_factor)
    linear = fit_transport_function([1, 2, 3, 4], [0, 1, 2, 3], 'linear')
    assert np.isnan(linear.predict([.1], extrapolate=True)[0])
    for args in [(np.ones(5), np.arange(5), 'linear'), ([1, 2], [3, 4], 'power'),
                 ([1, 2, 3], [3, 4, 5], 'polynomial', 5), ([1, 2, 3], [3, 4, 5], 'unknown'),
                 ([1, 2, 3], [3, 4, 5], 'polynomial', 0)]:
        with pytest.raises(ValueError): fit_transport_function(*args)


def inputs():
    t = pd.date_range('2020-01-01', periods=6, freq='12h')
    q = np.arange(1., 7.)
    model = pd.DataFrame({'Q': q, 'Conc': 2*q + 1, 'Flux': (2*q + 1)*q/1000}, index=t)
    obs = pd.DataFrame({'kind': 'sample', 'discharge_m3s': q, 'ssc_mg_l': 2*q + 1,
        'sand_mg_l': q, 'fines_mg_l': q + 1, 'ssl_kg_s': np.nan}, index=t)
    return model, obs


def test_samples_loads_same_record_duplicates_and_partial_observations():
    model, obs = inputs()
    # Keep duplicate samples separate; avoid a Cartesian merge with Q-only rows.
    obs = pd.concat([obs, obs.iloc[[1]], pd.DataFrame({'kind': ['daily'], 'discharge_m3s': [2.]}, index=[obs.index[1]])])
    records = sediment_records(obs, 'Flux', 'total', ['sample', 'daily'])
    assert len(records) == 8 and np.isfinite(records.obs).sum() == 7
    np.testing.assert_allclose(records.obs.iloc[:6], model.Flux)
    obs.iloc[0, obs.columns.get_loc('ssl_kg_s')] = .123
    assert sediment_records(obs, 'Flux', 'total', ['sample']).obs.iloc[0] == .123
    result = build_comparison(model, obs, form='linear')
    assert result.fit.n_used == 7
    np.testing.assert_allclose(result.series.reference, model.Conc)
    assert any('duplicate discharge times' in note for note in result.notes)
    sand = build_comparison(model, obs, variable='Flux', group='sand', form='polynomial', degree=2)
    np.testing.assert_allclose(sand.samples.obs.iloc[:6], np.arange(1., 7.)**2/1000)


def test_clock_offset_pairing_observed_vs_model_driver_and_missing_steps():
    model, obs = inputs()
    obs.index -= pd.Timedelta(hours=6)
    result = build_comparison(model, obs, offset_hours=6, form='linear')
    np.testing.assert_allclose(result.samples['mod'], model.Conc)
    np.testing.assert_allclose(result.series.reference, model.Conc)
    changed = model.copy(); changed['Q'] *= 2
    conditional = build_comparison(changed, obs, offset_hours=6, form='linear', driver='model')
    assert conditional.series.reference.notna().sum() == 3  # Q outside the fitted domain stays unknown
    extrapolated = build_comparison(changed, obs, offset_hours=6, form='linear', driver='model', extrapolate=True)
    np.testing.assert_allclose(extrapolated.series.reference, 2*changed.Q + 1)
    assert any('conditional on model' in note for note in conditional.notes)
    assert any('3 times outside' in note for note in extrapolated.notes)
    shifted = obs.iloc[[0, 1, 2, 5]].copy()
    gap = build_comparison(model, shifted, offset_hours=6, form='linear', max_gap_hours=24)
    assert gap.series.reference.iloc[3:5].isna().all()
    assert gap.samples.index.min() == model.index.min()
    model.iloc[1, model.columns.get_loc('Conc')] = np.nan
    missing = build_comparison(model, obs, offset_hours=6, include_rating=False)
    assert missing.samples['mod'].isna().sum() == 1
    assert missing.fit is None and missing.series.reference.isna().all()


def test_unavailable_rating_preserves_measured_samples_and_date_selection():
    model, obs = inputs()
    obs['discharge_m3s'] = np.nan
    result = build_comparison(model, obs, start='2020-01-02', end='2020-01-02')
    assert len(result.samples) == 2 and result.fit is None
    assert any('Rating curve unavailable' in note for note in result.notes)
    assert comparison_statistics(result.samples.obs, result.samples['mod'])['n_pairs'] == 2
    _, obs = inputs()
    result = build_comparison(model, obs, kinds=['cwms'])
    assert result.samples.empty and result.fit is None


def test_concentration_from_reported_load_and_zero_flow():
    model, obs = inputs()
    obs['ssl_kg_s'] = model.Flux.to_numpy()
    obs['ssc_mg_l'] = np.nan
    records = sediment_records(obs, 'Conc', 'total', ['sample'])
    np.testing.assert_allclose(records.obs, model.Conc)
    obs.iloc[0, obs.columns.get_loc('discharge_m3s')] = 0
    records = sediment_records(obs, 'Conc', 'total', ['sample'])
    assert np.isnan(records.obs.iloc[0])
    # Direct concentration always wins over a contradictory load-derived value.
    obs.iloc[1, obs.columns.get_loc('ssc_mg_l')] = 100
    assert sediment_records(obs, 'Conc', 'total', ['sample']).obs.iloc[1] == 100


def test_metrics_known_bias_scale_kge_and_zero_reference():
    metrics = comparison_statistics([1, 2, 3, np.nan], [2, 4, 6, 5])
    assert metrics['n_pairs'] == 3 and metrics['bias'] == 2
    assert metrics['rmse'] == pytest.approx(np.sqrt(14/3))
    assert metrics['pbias_pct'] == 100
    assert metrics['scale_model_to_reference'] == .5
    assert metrics['kge'] == pytest.approx(1 - np.sqrt(2))
    perfect = comparison_statistics([1, 2, 3], [1, 2, 3])
    assert perfect['kge'] == 1 and perfect['nse'] == 1
    zero = comparison_statistics([0, 0, 0], [0, 0, 0])
    assert np.isnan(zero['nrmse_pct']) and np.isnan(zero['scale_model_to_reference'])
    assert 'kge' not in zero


def test_streamed_export_failure_keeps_previous_file_and_cleans_temporary(tmp_path):
    from core.io import atomic_writer
    target = tmp_path/'comparison.csv'
    target.write_text('previous complete result')
    with pytest.raises(OSError):
        with atomic_writer(target) as stream:
            stream.write('incomplete replacement')
            raise OSError('disk write failed')
    assert target.read_text() == 'previous complete result'
    assert list(tmp_path.iterdir()) == [target]


def test_time_series_calibration_gui_workflow_and_exports(make_hdf, tmp_path, qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from config.settings import AppSettings
    from gui.main_window import MainWindow
    from observations.processing import ObservationSet, _blank
    from tests.test_gui_workflows import wait
    import json
    settings = AppSettings(last_hdf_path='', observation_cache_dir=str(tmp_path/'cache'), drop_initial_step_sediment=False)
    monkeypatch.setattr(settings, 'save', lambda: None)
    window = MainWindow(settings)
    window._load_file(str(make_hdf()))
    wait(qapp, lambda: window.mds is not None and window.workers.idle())
    tab = window.tab_ts_cal
    assert window.tabs.tabText(window.tabs.indexOf(tab)) == 'Time Series Calibration'
    assert tab.combo_group.count() == 3
    model = window.mds.frame(0, 'total', window.mds.rouse_cfg).df
    data = _blank(model.index)
    data['kind'] = 'sample'; data['discharge_m3s'] = [10, 15, 20, 25, 30]
    data['ssc_mg_l'] = [200, 300, 400, 500, 600]
    data['sand_mg_l'] = [50, 60, 70, 80, 90]
    data['fines_mg_l'] = [150, 240, 330, 420, 510]
    # Exercise the actual observations signal rather than bypassing integration.
    window.tab_obs.obs_changed.emit(ObservationSet('test', 'Measured sediment', data))
    assert tab._result is not None and len(tab._paired) == 5
    assert tab._context['measured_statistics']['n_pairs'] == 5
    assert tab._context['rating_reference_statistics']['n_pairs'] == 5
    assert tab.table.columnCount() == 3
    for form in ('linear', 'power', 'logarithmic', 'polynomial'):
        tab.combo_function.setCurrentIndex(tab.combo_function.findData(form))
        assert tab._result.fit.form == form
    tab.chk_log.setChecked(True)
    tab.chk_extrapolate.setChecked(True)
    tab.combo_driver.setCurrentIndex(1)
    tab.combo_var.setCurrentText('Sediment Flux')
    assert 'tons/day' in tab.canvas.figure.axes[0].get_ylabel()
    assert tab._result.fit is not None
    assert np.isfinite(tab._result.samples.obs).all()
    target = tmp_path/'comparison.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(target), 'CSV'))
    tab.btn_export.click()
    assert len(pd.read_csv(target)) == 5
    samples = pd.read_csv(tmp_path/'comparison.samples.csv')
    assert len(samples) == 5 and 'ObservationDateTime' in samples
    context = json.loads((tmp_path/'comparison.meta.json').read_text())
    assert 'NaN' not in (tmp_path/'comparison.meta.json').read_text()
    assert context['rating_driver'] == 'model' and context['fit']['form'] == 'polynomial'
    assert context['metric_weighting'].startswith('Each finite pair')
    tab.combo_display.setCurrentIndex(tab.combo_display.findData('points'))
    assert tab._result.fit is None and not tab.combo_function.isEnabled()
    tab.combo_group.setCurrentIndex(tab.combo_group.findData('sand'))
    assert tab._context['group'] == 'sand'
    window.combo_xs.setCurrentIndex(1); wait(qapp, window.workers.idle)
    assert tab._xs_index == 1 and tab._result is not None
    for check in tab.kind_checks.values(): check.setChecked(False)
    assert tab._result is None and not tab.btn_export.isEnabled()
    for check in tab.kind_checks.values(): check.setChecked(True)
    # Removing observations and replacing the model must discard old exports.
    window.tab_obs.obs_changed.emit(None)
    assert tab._result is None and not tab.btn_export.isEnabled()
    window._load_file(str(make_hdf('replacement.hdf'))); wait(qapp, window.workers.idle)
    assert tab._result is None
    window.close(); qapp.processEvents()
