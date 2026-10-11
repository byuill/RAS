"""Known integrals and failure cases for accounting, sensitivity, and error assumptions."""
import json

import numpy as np
import pandas as pd
import pytest

from bathymetry_calibration.calculation_audit import (linear_positive_area, run_sensitivity,
    support_signature, volume_uncertainty)
from bathymetry_calibration.core import CalibrationError, compare_profiles
from bathymetry_calibration.demo import create_demo
from bathymetry_calibration.workflow import export_sensitivity, load_config, run_comparison
from tests.test_bathymetry_diagnostics import profiles


def test_opposing_lateral_changes_have_zero_net_and_large_gross_turnover():
    transects, before, after = profiles([0, 0, 0])
    after['z_m'] = after.u_m.map({0.: -3., 5.: 3., 10.: -3.})
    result = compare_profiles(transects, before, before, before, after,
                              diagnostics={'change_threshold_m': 1})
    m = result.metrics
    assert m['observed_total_m3'] == 0
    assert m['observed_gross_deposition_m3'] == pytest.approx(1500)
    assert m['observed_gross_erosion_m3'] == pytest.approx(1500)
    assert m['observed_cancellation_fraction'] == 1
    assert m['observed_spatial_std_change_m'] == pytest.approx(np.sqrt(3))
    assert m['observed_rms_change_m'] == pytest.approx(np.sqrt(3))
    assert m['observed_deposition_footprint_fraction'] == pytest.approx(1/3)
    assert m['observed_erosion_footprint_fraction'] == pytest.approx(1/3)
    assert m['observed_within_threshold_footprint_fraction'] == pytest.approx(1/3)
    assert m['model_cancellation_fraction'] is None
    for _, ledger in result.lateral_audit.groupby('xs_id'):
        assert ledger.observed_signed_area_m2.sum() == 0
        assert ledger.observed_deposition_area_m2.sum() == pytest.approx(7.5)
        assert ledger.observed_second_moment_m3.sum() == pytest.approx(30)
    assert result.intervals.observed_cancellation_fraction.eq(1).all()
    json.dumps(m, allow_nan=False)


def test_exact_zero_crossing_does_not_use_clipped_endpoint_trapezoid():
    assert linear_positive_area(-1, 3, 4) == 4.5
    np.testing.assert_allclose(linear_positive_area([-1, 1, -2, 0, 1], [3, -3, -1, 2, 3], 4),
                               [4.5, .5, 0, 4, 8])


def test_longitudinal_cancellation_exposes_opposing_section_changes():
    transects, before, after = profiles([-2, 2])
    r = compare_profiles(transects, before, after, before, after)
    assert r.metrics['observed_total_m3'] == 0
    assert r.metrics['observed_gross_turnover_m3'] == 2000
    assert r.sections.observed_cancellation_fraction.eq(0).all()
    assert r.intervals.observed_cancellation_fraction.eq(1).all()
    assert r.intervals.observed_spatial_std_change_m.iloc[0] == 2


def test_ledger_reconciles_interval_node_and_boundary_sums_for_unequal_lengths():
    transects, before, after = profiles([-1, -2, -3], chainage=[0, 100, 300])
    r = compare_profiles(transects, before, after, before, after)
    assert r.sections.model_cumulative_m3.tolist() == [-500, -3500, -6500]
    assert r.sections.model_interval_prefix_m3.tolist() == [0, -1500, -6500]
    grouped = r.lateral_audit.groupby('xs_id').model_signed_area_m2.sum()
    np.testing.assert_allclose(r.sections.xs_id.map(grouped), r.sections.model_area_change_m2)
    i = r.intervals
    np.testing.assert_allclose((i.model_upstream_area_m2+i.model_downstream_area_m2)*i.length_m/2,
                               i.model_volume_change_m3)
    assert r.sections.model_local_control_volume_m3.sum() == r.intervals.model_volume_change_m3.sum()


def test_grid_refinement_does_not_change_gross_moments_or_support():
    transects, before, after = profiles([0, 0, 0])
    after['z_m'] = after.u_m.map({0.: -1., 5.: 3., 10.: -2.})
    coarse = compare_profiles(transects, before, after, before, after, grid_spacing_m=100)
    fine = compare_profiles(transects, before, after, before, after, grid_spacing_m=.3)
    for key in ('observed_total_m3', 'observed_gross_turnover_m3', 'observed_spatial_std_change_m',
                'observed_deposition_footprint_fraction'):
        assert fine.metrics[key] == pytest.approx(coarse.metrics[key])
    assert support_signature(coarse) == support_signature(fine)


def test_scenarios_change_estimator_not_reference_and_report_different_footprints():
    transects, before, after = profiles([-1, -2, -3], chainage=[0, 100, 300])
    r = compare_profiles(transects, before, after, before, after)
    original = r.sections.copy(deep=True)
    report = run_sensitivity(r, [
        {'name': 'upstream', 'overrides': {'longitudinal_method': 'upstream'}},
        {'name': 'downstream', 'overrides': {'longitudinal_method': 'downstream'}},
        {'name': 'trim', 'overrides': {'lateral_trim_fraction': .1}},
        {'name': 'shift', 'overrides': {'observed_target_shift_m': .2}},
        {'name': 'threshold', 'overrides': {'change_threshold_m': 100}},
    ])
    table = report.summary.set_index('name')
    assert table.loc['upstream', 'observed_total_m3'] == -5000
    assert table.loc['downstream', 'observed_total_m3'] == -8000
    assert table.loc['trim', 'observed_total_m3'] == pytest.approx(-5200)
    assert table.loc['trim', 'support_changed']
    assert not table.loc['upstream', 'support_changed']
    assert table.loc['shift', 'observed_delta_m3'] == pytest.approx(600)
    assert table.loc['shift', 'bias_delta_m3'] == pytest.approx(-600)
    assert table.loc['threshold', 'observed_total_m3'] == -6500
    pd.testing.assert_frame_equal(r.sections, original)
    assert r.calculation_inputs['observed_after'].z_m.equals(after.z_m)
    for _, scenario, _ in report.scenarios:
        assert scenario.sections.observed_local_control_volume_m3.sum() == pytest.approx(scenario.metrics['observed_total_m3'])


def test_missing_data_ledgers_identify_source_and_scenarios_keep_failure_reasons():
    transects, before, after = profiles([1]*3, u=(0, 5, 10, 15, 20))
    after.loc[after.u_m == 10, 'z_m'] = np.nan
    r = compare_profiles(transects, before, before, before, after, min_coverage=.5)
    holes = r.lateral_audit[~r.lateral_audit.accepted]
    assert holes.reason.str.contains('obs_after').all()
    assert holes.observed_signed_area_m2.eq(0).all()
    assert r.metrics['observed_gross_turnover_m3'] == r.metrics['observed_total_m3']
    report = run_sensitivity(r, [{'name': 'strict', 'overrides': {'min_coverage': 1}},
                                 {'name': 'usable', 'overrides': {'grid_spacing_m': 100}}])
    assert report.scenarios[0][1] is None
    assert report.summary.status.tolist() == ['ok', 'unavailable', 'ok']
    assert 'coverage' in report.summary.error.iloc[1]
    with pytest.raises(CalibrationError, match='effective width'):
        compare_profiles(transects, before, before, before, after, min_coverage=.5, min_common_width_m=15)


def test_uncertainty_uses_section_coherence_and_explicit_temporal_spatial_correlation():
    transects, before, after = profiles([1]*3)
    r = compare_profiles(transects, before, before, before, after)
    coherent = volume_uncertainty(r, before_sigma_m=.3, after_sigma_m=.4)
    independent = volume_uncertainty(r, before_sigma_m=.3, after_sigma_m=.4, spatial_correlation=0)
    assert coherent['change_sigma_m'] == .5
    assert coherent['observed_volume_sigma_m3'] == 1000
    assert independent['observed_volume_sigma_m3'] == pytest.approx(.5*np.sqrt(500**2+1000**2+500**2))
    assert coherent['bias_lower_95_m3'] == -3960
    assert coherent['bias_upper_95_m3'] == -40
    assert coherent['bias_exceeds_survey_error_95']
    cancelled = volume_uncertainty(r, before_sigma_m=.3, after_sigma_m=.3, temporal_correlation=1)
    assert cancelled['observed_volume_sigma_m3'] == 0
    assert cancelled['bias_exceeds_survey_error_95'] is None
    assert volume_uncertainty(r)['bias_exceeds_survey_error_95'] is None
    for opts in [{'spatial_correlation': -1}, {'temporal_correlation': 2}, {'after_sigma_m': np.nan}]:
        with pytest.raises(CalibrationError, match='Uncertainty'):
            volume_uncertainty(r, **opts)


def test_coherent_volume_uncertainty_is_invariant_to_grid_refinement():
    transects, before, after = profiles([1]*3)
    for spacing in [100, .25]:
        r = compare_profiles(transects, before, after, before, after, grid_spacing_m=spacing)
        assert volume_uncertainty(r, after_sigma_m=.5)['observed_volume_sigma_m3'] == 1000


def test_segmented_audit_resets_and_does_not_count_missing_bed():
    transects, before, after = profiles([1]*5)
    after.loc[after.xs_id == 'XS-2', 'z_m'] = np.nan
    r = compare_profiles(transects, before, after, before, after)
    assert r.sections.observed_deposition_cumulative_m3.tolist() == [500, 1000, 500, 1000]
    assert r.metrics['observed_gross_turnover_m3'] == 2000
    assert 'XS-2' not in r.lateral_audit.xs_id.tolist()
    assert r.excluded.xs_id.tolist() == ['XS-2']


def test_workflow_and_sensitivity_exports_preserve_instructions_and_provenance(tmp_path):
    directory = create_demo(tmp_path/'demo')
    settings = load_config(directory/'config.json')
    settings['surveys']['baseline']['vertical_uncertainty_m'] = .3
    settings['surveys']['target']['vertical_uncertainty_m'] = .3
    settings['volume_uncertainty'] = {'temporal_correlation': 1, 'spatial_correlation': .5}
    r, p = run_comparison(settings, directory/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    assert r.metrics['survey_change_detection_limit_95_m'] == 0
    exploration = run_sensitivity(r, [{'name': 'shift', 'overrides': {'observed_target_shift_m': .2}}],
                                  uncertainty={'after_sigma_m': .5})
    saved = export_sensitivity(exploration, p, tmp_path/'exports')
    summary = pd.read_csv(saved/'sensitivity_summary.csv')
    assert summary.name.tolist() == ['Reference', 'shift']
    specifications = json.loads((saved/'scenarios.json').read_text())
    repeated = run_sensitivity(r, specifications['scenarios'], uncertainty=specifications['uncertainty'])
    assert repeated.summary.observed_total_m3.tolist() == exploration.summary.observed_total_m3.tolist()
    reference_report = json.loads(next((saved/'reference').glob('*/report.json')).read_text())
    assert reference_report['provenance']['volume_uncertainty']['observed_volume_sigma_m3'] == 1000
    comparison = next((saved/'scenario-000').glob('comparison-*'))
    assert (comparison/'lateral_audit.csv').exists()
    assert (comparison/'source_profiles.csv').exists()
    assert (comparison/'calculation_audit.png').stat().st_size > 10000
    assert (comparison/'variability.png').stat().st_size > 10000
    payload = json.loads((comparison/'report.json').read_text())
    assert payload['provenance']['sensitivity']['overrides']['observed_target_shift_m'] == .2
    assert 'datum_review' not in payload['provenance']
    assert 'not rerun' in payload['provenance']['native_audit']


def test_gui_scenario_knobs_recompute_and_reset_without_changing_main_result(tmp_path, qapp):
    from bathymetry_calibration.calculation_gui import CalculationAuditWindow
    from tests.test_gui_workflows import wait
    transects, before, after = profiles([1]*3)
    r = compare_profiles(transects, before, after, before, after)
    window = CalculationAuditWindow(r, {})
    window.show()
    assert len(window.figure.axes) == 4
    window.controls['observed_target_shift_m'].setValue(.2)
    window.calculate()
    wait(qapp, window.workers.idle)
    assert window.result.metrics['observed_total_m3'] == pytest.approx(2400)
    assert r.metrics['observed_total_m3'] == 2000
    assert window.summary_table.rowCount() == 2
    window.cumulative.setCurrentIndex(1)
    assert 'Completed-reach' in window.figure.axes[0].get_title()
    window.scenario.setCurrentText('Reference')
    assert window.result is r
    window.scenario.setCurrentText('Scenario 1')
    assert window.result.metrics['observed_total_m3'] == pytest.approx(2400)
    window.reset()
    assert window.result is r and window.scenarios == []
    assert not window.export_button.isEnabled()
    window.close()
    qapp.processEvents()


def test_invalid_and_duplicate_scenario_controls_are_rejected():
    transects, before, after = profiles([1]*3)
    r = compare_profiles(transects, before, after, before, after)
    for scenarios in [[], [{'name': 'bad', 'overrides': {'unsupported': 2}}],
                      [{'name': 'Reference'}], [{'name': 'same'}, {'name': 'same'}]]:
        with pytest.raises(CalibrationError):
            run_sensitivity(r, scenarios)
