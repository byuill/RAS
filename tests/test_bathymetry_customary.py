"""Physical conversion, actual station locations, and workflow regression checks."""
import copy
import json

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from bathymetry_calibration.core import CalibrationError, compare_profiles, validate_transects
from bathymetry_calibration.demo import create_demo
from bathymetry_calibration.display_units import (FT_PER_M, M_PER_MILE, YD3_PER_M3,
    customary_frame, customary_mapping, longitudinal_x, select_river_mile_range,
    station_river_mile)
from bathymetry_calibration.plots import (draw_calculation_audit, draw_comparison,
    draw_diagnostics, draw_section, draw_variability, draw_time_series)
from bathymetry_calibration.workflow import (export_comparison, load_config,
    run_comparison, run_survey_qaqc, run_time_series)
from tests.test_bathymetry_diagnostics import profiles
from tests.test_gui_workflows import wait


def station_profiles():
    transects, before, after = profiles([1, 2, -1], chainage=[0, 100, 300])
    # RM separation intentionally differs enormously from channel length.
    ids = {'XS-0': 'River:Reach:236.7', 'XS-1': 'River:Reach:0.0', 'XS-2': 'River:Reach:-19.6'}
    for frame in (transects, before, after):
        frame['xs_id'] = frame.xs_id.map(ids)
    return transects, before, after


def station_demo(path):
    directory = create_demo(path)
    ids = {'A': '236.7', 'B': '0.0', 'C': '-19.6'}
    for filename in ('transects.csv', 'survey-before.csv', 'survey-after.csv'):
        frame = pd.read_csv(directory/filename)
        frame['xs_id'] = frame.xs_id.map(ids)
        frame.to_csv(directory/filename, index=False)
    return directory


@pytest.mark.parametrize('label,expected', [('236.7', 236.7), ('River:LMR:-19.6', -19.6),
    ('R:LMR:0.0*', 0), (' +1.5 ', 1.5), ('XS-19.6', None), ('RM 236.7', None), ('1**', None)])
def test_station_tokens_are_not_arbitrary_digits(label, expected):
    value = station_river_mile(label)
    assert np.isnan(value) if expected is None else value == expected


def test_exact_physical_conversions_and_dimensionless_values():
    source = pd.DataFrame({'height_m': [.3048], 'area_m2': [.3048**2],
        'volume_m3': [.9144**3], 'change_m_per_year': [.3048],
        'slope_m_per_km': [.3048/(M_PER_MILE/1000)],
        'concavity_m_per_km2': [.3048/(M_PER_MILE/1000)**2],
        'lateral_second_moment_m3': [.3048**3], 'slope_m_per_m': [.25],
        'chainage_m': [M_PER_MILE], 'fraction': [.25]})
    original = source.copy(deep=True)
    display = customary_frame(source)
    for column in ('height_ft', 'area_ft2', 'volume_yd3', 'change_ft_per_year',
                   'slope_ft_per_mi', 'concavity_ft_per_mi2', 'lateral_second_moment_ft3',
                   'downstream_distance_mi'):
        assert display[column].iloc[0] == pytest.approx(1)
    assert display.fraction.iloc[0] == .25
    assert display.slope_ft_per_ft.iloc[0] == .25
    pd.testing.assert_frame_equal(source, original)
    assert customary_mapping({'error_m': None, 'zone': True}) == {'error_ft': None, 'zone': True}


def test_actual_river_miles_never_replace_channel_lengths():
    transects, before, after = station_profiles()
    result = compare_profiles(transects, before, after, before, after)
    assert result.sections.river_mile.tolist() == [236.7, 0, -19.6]
    assert longitudinal_x(result.sections).tolist() == [236.7, 0, -19.6]
    assert result.intervals.mid_river_mile.tolist() == [118.35, -9.8]
    # Areas are 10,20,-10 m², channel lengths 100 and 200 m, so 2,500 m³.
    assert result.metrics['observed_total_m3'] == pytest.approx(2500)
    assert result.metrics['integrated_reach_length_m'] == 300
    assert result.calculation_inputs['transects'].river_mile.notna().all()
    display = customary_frame(result.intervals, result.sections)
    assert display.model_volume_change_yd3.sum() == pytest.approx(2500*YD3_PER_M3)
    assert display.upstream_river_mile.tolist() == [236.7, 0]


def test_text_ids_use_explicit_station_column_or_honest_distance_fallback():
    transects, before, after = profiles([1, 1, 1])
    result = compare_profiles(transects, before, after, before, after)
    assert longitudinal_x(result.sections) == pytest.approx([0, 100/M_PER_MILE, 200/M_PER_MILE])
    assert 'river_mile' not in customary_frame(result.sections)
    with pytest.raises(CalibrationError, match='station labels'):
        select_river_mile_range(transects, {'upstream': 236.7, 'downstream': -19.6})
    transects['river_mile'] = transects.model_column.map({0: 236.7, 1: 0, 2: -19.6})
    result = compare_profiles(transects, before, after, before, after)
    assert result.sections.river_mile.tolist() == [236.7, 0, -19.6]
    figure = Figure()
    draw_comparison(figure, result, {'survey_before': 'baseline', 'survey_after': 'target'})
    assert figure.axes[0].lines[0].get_xdata().tolist() == [236.7, 0, -19.6]


def test_range_selection_preserves_adjacency_columns_and_control_lengths():
    transects, before, after = station_profiles()
    original = transects.copy()
    selected = select_river_mile_range(transects, {'upstream': 236.7, 'downstream': 0})
    assert selected.model_column.drop_duplicates().tolist() == [0, 1]
    assert selected[selected.model_column == 1].length_to_next_m.isna().all()
    result = compare_profiles(selected, before, after, before, after)
    assert result.sections.control_length_m.tolist() == [50, 50]
    assert result.metrics['observed_total_m3'] == 1500
    pd.testing.assert_frame_equal(transects, original)
    # Non-exact bounds select existing XS, with no invented boundary sections.
    selected = select_river_mile_range(transects, {'upstream': 200, 'downstream': -19.6})
    assert selected.model_column.drop_duplicates().tolist() == [1, 2]
    with pytest.raises(CalibrationError, match='at least two'):
        select_river_mile_range(transects, {'upstream': 100, 'downstream': -5})
    with pytest.raises(CalibrationError, match='within the manifest'):
        select_river_mile_range(transects, {'upstream': 300, 'downstream': -19.6})
    with pytest.raises(CalibrationError, match='Upstream'):
        select_river_mile_range(transects, {'upstream': -19.6, 'downstream': 236.7})


def test_explicit_station_metadata_must_be_consistent_finite_and_monotonic():
    transects, _, _ = profiles([1, 1, 1])
    transects['river_mile'] = transects.model_column.map({0: 236.7, 1: 0, 2: -19.6})
    broken = transects.copy()
    broken.loc[0, 'river_mile'] = 200
    with pytest.raises(CalibrationError, match='inconsistent river_mile'):
        validate_transects(broken)
    broken = transects.assign(river_mile=np.inf)
    with pytest.raises(CalibrationError, match='finite'):
        validate_transects(broken)
    broken = transects.assign(river_mile=transects.model_column.map({0: 0, 1: 236.7, 2: -19.6}))
    with pytest.raises(CalibrationError, match='monotonic'):
        validate_transects(broken)


def test_plot_values_thresholds_and_locations_match_display_units():
    transects, before, after = station_profiles()
    result = compare_profiles(transects, before, after, before, after)
    original_sections = result.sections.copy(deep=True)
    original_profiles = result.profiles.copy(deep=True)
    original_metrics = copy.deepcopy(result.metrics)
    figure = Figure()
    draw_comparison(figure, result, {'survey_before': 'baseline', 'survey_after': 'target'})
    assert figure.axes[0].lines[0].get_ydata() == pytest.approx(result.sections.model_cumulative_m3*YD3_PER_M3)
    assert figure.axes[1].lines[0].get_ydata() == pytest.approx(result.sections.model_mean_change_m*FT_PER_M)
    assert figure.axes[1].patches[0].get_y() == pytest.approx(-result.metrics['change_detection_threshold_m']*FT_PER_M)
    assert figure.axes[0].get_xlim()[0] > figure.axes[0].get_xlim()[1]
    assert '-19.6' in [label.get_text() for label in figure.axes[0].get_xticklabels()]
    figure.axes[0].set_xlim(1, 2)
    assert len(figure.axes[0].get_xticks()) >= 3  # Zoom retains readable RM labels.
    draw_section(figure, result, 'River:Reach:236.7')
    np.testing.assert_allclose(figure.axes[1].collections[0].get_offsets()[:, 0], result.profiles.query("xs_id == 'River:Reach:236.7'").u_m*FT_PER_M)
    draw_calculation_audit(figure, result, 'River:Reach:236.7')
    np.testing.assert_allclose(figure.axes[1].collections[1].get_offsets()[:, 0], [118.35, -9.8])
    draw_diagnostics(figure, result)
    assert figure.axes[4].lines[0].get_ydata() == pytest.approx(result.sections.model_change_slope_m_per_km*FT_PER_M*M_PER_MILE/1000)
    draw_variability(figure, result)
    assert figure.axes[0].lines[0].get_xdata().tolist() == [236.7, 0, -19.6]
    pd.testing.assert_frame_equal(result.sections, original_sections)
    pd.testing.assert_frame_equal(result.profiles, original_profiles)
    assert result.metrics == original_metrics


def test_scenario_overlay_includes_reference_end_stations():
    transects, before, after = station_profiles()
    reference = compare_profiles(transects, before, after, before, after)
    selected = select_river_mile_range(transects, {'upstream': 236.7, 'downstream': 0})
    scenario = compare_profiles(selected, before, after, before, after)
    figure = Figure()
    draw_calculation_audit(figure, scenario, scenario.sections.xs_id.iloc[0], reference)
    upstream, downstream = figure.axes[0].get_xlim()
    assert upstream > 236.7 and downstream < -19.6


def test_scoped_workflow_caches_and_customary_exports(tmp_path):
    demo = station_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    full, provenance = run_comparison(settings, demo/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    assert full.metrics['model_total_m3'] == 2000
    settings['river_mile_range'] = {'upstream': 0, 'downstream': -19.6}
    subset, provenance = run_comparison(settings, demo/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    repeated, repeated_provenance = run_comparison(settings, demo/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    assert subset.sections.xs_id.tolist() == ['0.0', '-19.6']
    assert subset.metrics['model_total_m3'] == repeated.metrics['model_total_m3'] == 1000
    assert not any(item['hit'] for item in provenance['cache'])
    assert all(item['hit'] for item in repeated_provenance['cache'])
    reviews, _ = run_survey_qaqc(settings)
    assert set(reviews['target'].audit.xs_id) == {'0.0', '-19.6'}
    saved = export_comparison(subset, provenance, tmp_path/'exports')
    customary = pd.read_csv(saved/'sections_customary.csv')
    assert customary.river_mile.tolist() == [0, -19.6]
    assert customary.model_local_control_volume_yd3.sum() == pytest.approx(1000*YD3_PER_M3)
    assert 'model_local_control_volume_m3' in pd.read_csv(saved/'sections.csv')
    metrics = json.loads((saved/'metrics_customary.json').read_text())
    assert metrics['model_total_yd3'] == pytest.approx(1000*YD3_PER_M3)
    assert '/ 27' in (saved/'calculation_guide_customary.txt').read_text()
    series = run_time_series(settings, demo/'synthetic.p01.hdf')
    figure = Figure()
    draw_time_series(figure, series)
    np.testing.assert_allclose(figure.axes[0].images[0].get_array(), np.array([subset.sections.model_mean_change_m])*FT_PER_M/subset.metrics['model_duration_years'])
    assert [label.get_text() for label in figure.axes[0].get_xticklabels()] == ['0', '-19.6']


def test_gui_workflow_prerequisites_range_units_and_stale_review(tmp_path, qapp):
    from bathymetry_calibration.gui import CalibrationWindow
    demo = station_demo(tmp_path/'demo')
    window = CalibrationWindow()
    assert not window.compare_button.isEnabled()
    assert not window.qaqc_button.isEnabled()
    assert not window.export_button.isEnabled()
    window.config_path.setText(str(demo/'config.json'))
    assert window.load_button.isEnabled()
    window.load()
    assert window.qaqc_button.isEnabled()
    assert not window.compare_button.isEnabled()
    window.hdf_path.setText(str(demo/'synthetic.p01.hdf'))
    window.load()
    wait(qapp, lambda: window.workers.idle() and window.before_time.count() == 2)
    assert window.compare_button.isEnabled()
    window._busy(True)
    assert not window.compare_button.isEnabled() and window.cancel_button.isEnabled()
    window._busy(False)
    window.after_time.setCurrentIndex(0)
    assert not window.compare_button.isEnabled()
    window.after_time.setCurrentIndex(1)
    window.range_enabled.setChecked(True)
    window.upstream_rm.setValue(-10)
    assert not window.compare_button.isEnabled() and not window.qaqc_button.isEnabled()
    window.upstream_rm.setValue(0)
    assert window._settings_snapshot()['river_mile_range'] == {'upstream': 0, 'downstream': -19.6}
    window.compare()
    wait(qapp, lambda: window.result is not None and window.workers.idle())
    assert window.result.metrics['observed_total_m3'] == 1000
    assert 'yd³' in window.message.toPlainText() and 'ft' in window.message.toPlainText()
    assert window.audit_button.isEnabled() and window.export_button.isEnabled()
    window.review_surveys()
    wait(qapp, lambda: hasattr(window, 'qaqc_window') and window.workers.idle())
    review = window.qaqc_window
    review.survey.setCurrentText('target')
    review.offset.setValue(1)
    review.evidence.setText('Synthetic benchmark check')
    assert review.collect_options()['datum_correction_m'] == pytest.approx(.3048)
    window.upstream_rm.setValue(236.7)
    assert window.result is None and not window.export_button.isEnabled()
    review.apply()
    assert 'Reopen survey QA/QC' in review.message.toPlainText()
    assert 'qaqc' not in window.settings['surveys']['target']
    window.config_path.setText('another.json')
    assert not window.qaqc_button.isEnabled() and not window.compare_button.isEnabled()
    review.close()
    window.close()
    qapp.processEvents()


def test_gui_does_not_silently_clamp_configured_range(tmp_path, qapp):
    from bathymetry_calibration.gui import CalibrationWindow
    demo = station_demo(tmp_path/'demo')
    config = json.loads((demo/'config.json').read_text())
    config['river_mile_range'] = {'upstream': 1000, 'downstream': -19.6}
    (demo/'config.json').write_text(json.dumps(config))
    window = CalibrationWindow()
    window.config_path.setText(str(demo/'config.json'))
    window.load()
    assert 'within the manifest' in window.message.toPlainText()
    assert window.settings is None and not window.qaqc_button.isEnabled()
    window.close()


def test_gui_reference_assumptions_survive_rounded_feet_at_support_boundaries(qapp):
    from bathymetry_calibration.calculation_gui import CalculationAuditWindow
    transects, before, after = profiles([1, 1, 1], u=(0, 25, 50))
    reference = compare_profiles(transects, before, after, before, after,
                                 max_gap_m=25, min_common_width_m=50, min_coverage=.0005)
    window = CalculationAuditWindow(reference, {})
    overrides, _ = window.collect()
    assert overrides['max_gap_m'] == 25
    assert overrides['min_common_width_m'] == 50
    assert overrides['min_coverage'] == .0005
    assert window.controls['min_coverage'].value() == .0005
    window.calculate()
    wait(qapp, window.workers.idle)
    assert window.exploration.summary.status.tolist() == ['ok', 'ok']
    assert window.result.metrics['observed_total_m3'] == reference.metrics['observed_total_m3']
    window.controls['max_gap_m'].setValue(82)
    overrides, _ = window.collect()
    assert overrides['max_gap_m'] == pytest.approx(82*.3048)
    window.close()
    qapp.processEvents()
