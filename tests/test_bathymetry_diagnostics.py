import copy
import json
from pathlib import Path
import threading

import h5py
import numpy as np
import pandas as pd
import pytest

from bathymetry_calibration.cache import ProfileCache, cache_key
from bathymetry_calibration.core import CalibrationError, compare_profiles, interpolate_profile
from bathymetry_calibration.demo import create_demo
from bathymetry_calibration.qaqc import datum_shift_review, review_survey
from bathymetry_calibration.sources import map_xyz_points, read_model_profiles, read_survey
from bathymetry_calibration.workflow import (export_survey_qaqc, export_time_series, load_config,
    run_comparison, run_survey_qaqc, run_time_series)


def profiles(changes, chainage=None, u=(0., 5., 10.)):
    chainage = np.arange(len(changes))*100. if chainage is None else np.asarray(chainage)
    rows, baseline, target = [], [], []
    for i, change in enumerate(changes):
        for station in u:
            rows.append(dict(xs_id=f'XS-{i}', model_column=i, chainage_m=chainage[i],
                             length_to_next_m=chainage[i+1]-chainage[i] if i+1 < len(changes) else np.nan,
                             u_m=station, x_m=station, y_m=chainage[i]))
            baseline.append(dict(xs_id=f'XS-{i}', u_m=station, z_m=0.))
            target.append(dict(xs_id=f'XS-{i}', u_m=station, z_m=float(change)))
    return pd.DataFrame(rows), pd.DataFrame(baseline), pd.DataFrame(target)


def test_amplitude_error_retains_spatial_pattern_and_zone_skill():
    transects, before, observed = profiles([-2, -1, 0, 1, 2])
    model = observed.assign(z_m=2*observed.z_m)
    result = compare_profiles(transects, before, model, before, observed)
    m = result.metrics
    assert m['mean_change_rmse_m'] > 0
    assert m['change_shape_correlation'] == pytest.approx(1)
    assert m['change_rank_correlation'] == pytest.approx(1)
    assert m['change_regression_gain'] == pytest.approx(2)
    assert m['change_amplitude_ratio'] == pytest.approx(2)
    assert m['zone_agreement_fraction'] == 1
    assert m['erosion_intersection_over_union'] == 1
    assert m['deposition_intersection_over_union'] == 1
    assert set(result.zones.zone) == {'erosion', 'within_threshold', 'deposition'}
    assert result.confusion.matched_length_m.sum() == 400


def test_longitudinal_slope_and_concavity_use_unequal_physical_spacing():
    x = np.array([0., .5, 1.5, 3.])
    z = 2*x*x+3*x+1
    transects, before, after = profiles(z, chainage=x*1000)
    result = compare_profiles(transects, before, after, before, after)
    np.testing.assert_allclose(result.sections.model_change_slope_m_per_km, 4*x+3)
    np.testing.assert_allclose(result.sections.model_change_concavity_m_per_km2, 4)
    assert result.metrics['change_concavity_sign_agreement_fraction'] == 1
    assert result.metrics['target_bed_slope_rmse_m_per_km'] == 0


def test_reversed_patterns_and_constant_series_are_not_perfect_skill():
    transects, before, observed = profiles([-2, -1, 1, 2])
    result = compare_profiles(transects, before, observed.assign(z_m=-observed.z_m), before, observed)
    assert result.metrics['change_shape_correlation'] == pytest.approx(-1)
    assert result.metrics['zone_agreement_fraction'] == 0
    assert result.metrics['erosion_intersection_over_union'] == 0
    transects, before, after = profiles([1, 1, 1])
    result = compare_profiles(transects, before, after, before, after)
    assert result.metrics['change_shape_correlation'] is None
    assert result.metrics['change_amplitude_ratio'] is None
    json.dumps(result.metrics, allow_nan=False)


def test_detection_threshold_changes_zones_but_keeps_volume():
    transects, before, after = profiles([.1, .2, -.1])
    result = compare_profiles(transects, before, after, before, after, diagnostics={'change_threshold_m': .5})
    assert set(result.sections.observed_zone) == {'within_threshold'}
    assert result.metrics['model_total_m3'] == pytest.approx(200)


def test_excluded_xs_do_not_bridge_volumes_derivatives_or_prefixes():
    transects, before, after = profiles([1, 1, 1, 1, 1])
    after.loc[after.xs_id == 'XS-2', 'z_m'] = np.nan
    result = compare_profiles(transects, before, after, before, after)
    assert result.metrics['model_total_m3'] == 2000
    assert result.metrics['integrated_reach_length_m'] == 200
    assert result.metrics['supported_segments'] == 2
    assert result.intervals[['upstream_xs', 'downstream_xs']].values.tolist() == [['XS-0', 'XS-1'], ['XS-3', 'XS-4']]
    assert result.sections.model_cumulative_m3.tolist() == [500, 1000, 500, 1000]
    assert result.sections.model_change_concavity_m_per_km2.isna().all()
    assert result.metrics['change_concavity_rmse_m_per_km2'] is None


def test_nan_and_large_gaps_survive_even_coarse_integration_grid():
    transects, before, after = profiles([1, 1, 1], u=(0., 5., 10., 15., 20.))
    after.loc[after.u_m == 10, 'z_m'] = np.nan
    result = compare_profiles(transects, before, after, before, after, min_coverage=.5, grid_spacing_m=100)
    assert result.metrics['model_total_m3'] == 2000
    assert result.sections.coverage.tolist() == [.5]*3
    profile = after[after.xs_id == 'XS-0']
    values = interpolate_profile(profile, 'XS-0', [0, 2.5, 7.5, 10, 12.5, 17.5, 20], 25)
    assert np.isnan(values[2:5]).all()
    np.testing.assert_array_equal(values[[0, 1, 5, 6]], 1)
    two = pd.DataFrame({'xs_id': ['x', 'x'], 'u_m': [0, 100], 'z_m': [2, 3]})
    np.testing.assert_allclose(interpolate_profile(two, 'x', [0, 50, 100], 10), [2, np.nan, 3], equal_nan=True)


def test_qaqc_flags_spike_bounds_missing_values_and_preserves_raw():
    frame = pd.DataFrame({'xs_id': ['x']*21, 'u_m': np.arange(21.), 'z_m': np.zeros(21)})
    frame.loc[10, 'z_m'] = 100
    frame.loc[0, 'z_m'] = np.inf
    original = frame.copy()
    review = review_survey(frame, {'elevation_max_m': 20})
    assert review.audit.loc[10, 'spike']
    assert review.audit.loc[10, 'outside_elevation_limits']
    assert review.audit.loc[0, 'missing_or_nonfinite']
    assert review.profile.z_m.max() == 100
    masked = review_survey(frame, {'elevation_max_m': 20, 'exclude_flagged': True})
    assert np.isnan(masked.profile.loc[10, 'z_m'])
    assert not masked.profile.u_m.isna().any()
    pd.testing.assert_frame_equal(frame, original)
    assert review_survey(frame).profile.z_m.max() == 100


def test_duplicates_require_explicit_policy_and_exclusions_are_not_resurrected():
    frame = pd.DataFrame({'xs_id': ['x', 'x', 'x'], 'u_m': [0, 0, 5], 'z_m': [1, 3, 2]})
    with pytest.raises(CalibrationError, match='Duplicate'):
        review_survey(frame)
    inspected = review_survey(frame, allow_unresolved_duplicates=True)
    assert inspected.summary['flag_counts']['duplicate_station'] == 2
    review = review_survey(frame, {'duplicate_policy': 'mean'})
    assert review.profile.z_m.tolist() == [2, 2]
    review = review_survey(frame, {'duplicate_policy': 'mean', 'excluded_points': [{'xs_id': 'x', 'u_m': 0, 'reason': 'bad tie point'}]})
    assert np.isnan(review.profile.z_m.iloc[0])


def test_datum_review_is_ambiguous_and_corrections_require_evidence():
    transects, before, after = profiles([1, 1, 1])
    result = compare_profiles(transects, before, after, before, after)
    report = datum_shift_review(result.profiles)
    assert report['uniform_shift_candidate']
    assert 'real spatially coherent bed change' in report['basis']
    with pytest.raises(CalibrationError, match='evidence'):
        review_survey(after, {'datum_correction_m': -1})
    review = review_survey(after, {'datum_correction_m': -1, 'datum_correction_evidence': 'Independent benchmark offset'})
    assert review.profile.z_m.eq(0).all()
    assert review.audit.original_z_m.eq(1).all()


def test_qaqc_raw_cache_survives_decision_changes_and_spatial_gdb_edits(tmp_path):
    frame = pd.DataFrame({'xs_id': ['x', 'x', 'x'], 'u_m': [0, 0, 5], 'z_m': [1, 3, 2]})
    cache = ProfileCache(tmp_path/'cache')
    cache.put('test-key', frame)
    pd.testing.assert_frame_equal(cache.get('test-key')[['xs_id', 'u_m', 'z_m']], frame.astype({'u_m': float, 'z_m': float}))
    gdb = tmp_path/'fake.gdb'
    gdb.mkdir()
    dataset = gdb/'data'
    dataset.write_text('1 3 2')
    geometry = tmp_path/'transects.csv'
    geometry.write_text('unchanged')
    source = {'path': str(gdb)}
    key = cache_key(source, geometry, {})
    assert cache_key({**source, 'qaqc': {'datum_correction_m': 3}}, geometry, {}) == key
    dataset.write_text('3 1 2')  # Same mean/count, different locations.
    assert cache_key(source, geometry, {}) != key


def test_xyz_mapping_uses_curved_polyline_stations_and_unique_nearest_xs():
    transects, _, _ = profiles([0, 0], u=(0., 5., 10.))
    transects.loc[transects.xs_id == 'XS-0', ['x_m', 'y_m']] = [[0, 0], [5, 0], [5, 5]]
    records = [dict(x_m=5, y_m=2, z_m=3), dict(x_m=2, y_m=1, z_m=4), dict(x_m=2, y_m=50, z_m=5)]
    mapped = map_xyz_points(records, transects, longitudinal_limit_m=60)
    first = mapped[mapped.source_point_id == 0].iloc[0]
    assert first.xs_id == 'XS-0' and first.u_m == 7
    assert mapped.source_point_id.nunique() == len(mapped)
    # Equal-distance points between straight XS are not assigned to both.
    straight, _, _ = profiles([0, 0])
    tied = map_xyz_points([dict(x_m=2, y_m=0, z_m=1), dict(x_m=2, y_m=50, z_m=5)], straight, longitudinal_limit_m=60)
    assert tied.attrs['mapping']['ambiguous_points'] == 1
    assert len(tied) == 1


def test_ragged_reader_slices_selected_xs_and_validates_info(tmp_path, monkeypatch):
    transects, _, _ = profiles([0, 0])
    path = tmp_path/'ragged.hdf'
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('dates', data=[b'01JAN2020 00:00:00', b'01JAN2020 24:00:00'])
        group = h5.create_group('SE')
        for stamp, offset in [('01JAN2020 00:00:00', 0), ('01JAN2020 24:00:00', 1)]:
            group.create_dataset(f'Station Elevation ({stamp}) info', data=[[0, 3], [3, 3]])
            group.create_dataset(f'Station Elevation ({stamp}) values', data=[[0, offset], [5, offset], [10, offset]]*2)
    mapping = dict(profile_mapping_verified=True, layout='ragged_se', time_dataset='dates', se_group='SE', u_scale_to_m=1, z_scale_to_m=1)
    reads = []
    original = h5py.Dataset.__getitem__
    def capture(dataset, key):
        if dataset.name.endswith('values'):
            reads.append(key)
        return original(dataset, key)
    monkeypatch.setattr(h5py.Dataset, '__getitem__', capture)
    before, after = read_model_profiles(path, mapping, transects, 0, 1)
    assert after.z_m.eq(1).all() and before.z_m.eq(0).all()
    assert len(reads) == 4 and all(key[0].stop-key[0].start == 3 for key in reads)
    from bathymetry_calibration.sources import model_times
    assert str(model_times(path, mapping)[1]) == '2020-01-02 00:00:00'
    with h5py.File(path, 'a') as h5:
        h5['SE/Station Elevation (01JAN2020 00:00:00) info'][0] = [0, 100]
    with pytest.raises(CalibrationError, match='start/count'):
        read_model_profiles(path, mapping, transects, 0, 1)


def test_native_audit_skips_partial_footprint_and_uncertainty_does_not_mask_volume(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    source = settings['surveys']['target']
    points = pd.read_csv(source['path']).query('u_m > 0')
    points.to_csv(source['path'], index=False)
    source['vertical_uncertainty_m'] = 1
    result, provenance = run_comparison(settings, demo/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    assert result.metrics['observed_total_m3'] == 1000
    assert 'native_local_m3' not in result.sections
    assert provenance['native_audit'].startswith('skipped')
    assert result.metrics['change_detection_threshold_m'] == pytest.approx(1.96)
    assert set(result.sections.observed_zone) == {'within_threshold'}


def test_survey_review_without_hdf_exports_all_original_records(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    reviews, provenance = run_survey_qaqc(settings)
    saved = export_survey_qaqc(reviews, provenance, tmp_path/'exports')
    audit = pd.read_csv(saved/'survey_qaqc.csv')
    assert len(audit) == 18 and set(audit.survey) == {'baseline', 'target'}
    assert not audit.excluded.any()
    json.loads((saved/'report.json').read_text())


def test_cancellation_prevents_result_publication(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CalibrationError, match='cancelled'):
        run_comparison(settings, demo/'synthetic.p01.hdf', 'baseline', 'target', 0, 1, cancel=cancel)


def series_demo(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    settings.pop('native_volume')
    hdf = demo/'synthetic.p01.hdf'
    with h5py.File(hdf, 'a') as h5:
        del h5['dates'], h5['profile_elevation']
        h5.create_dataset('dates', data=[b'2012-01-01', b'2018-01-01', b'2025-01-01'])
        h5.create_dataset('profile_elevation', data=[np.zeros((3, 3)), np.ones((3, 3)), np.full((3, 3), 3.)])
    middle = pd.read_csv(demo/'survey-after.csv')
    middle.to_csv(demo/'middle.csv', index=False)
    final = middle.assign(z_m=3).query('u_m >= 5')
    final.to_csv(demo/'final.csv', index=False)
    template = settings['surveys']['target']
    settings['surveys']['middle'] = dict(template, date='2018-01-01', path=str(demo/'middle.csv'))
    settings['surveys']['target'].update(path=str(demo/'final.csv'))
    return demo, settings, hdf


def test_time_series_fixed_support_and_rates_are_comparable_and_exported(tmp_path):
    _, settings, hdf = series_demo(tmp_path)
    series = run_time_series(settings, hdf)
    assert len(series.comparisons) == 2
    first, second = [result for result, _ in series.comparisons]
    assert first.metrics['observed_total_m3'] == 1000
    assert second.metrics['observed_total_m3'] == 2000
    assert first.sections.common_u_min_m.tolist() == second.sections.common_u_min_m.tolist() == [5]*3
    assert first.sections.effective_width_m.tolist() == second.sections.effective_width_m.tolist()
    assert first.metrics['observed_volume_change_m3_per_year'] == pytest.approx(1000/first.metrics['observed_duration_years'])
    saved = export_time_series(series, tmp_path/'exports')
    assert len(pd.read_csv(saved/'interval_skill.csv')) == 2
    assert len(pd.read_csv(saved/'section_time_series.csv')) == 6
    assert (saved/'time_series.png').stat().st_size > 1000
    assert len(list(saved.rglob('diagnostics.png'))) == 2


def test_time_series_rejects_bad_dates_or_repeated_model_output(tmp_path):
    _, settings, hdf = series_demo(tmp_path)
    settings['surveys']['middle']['date'] = '2012-01-02'
    settings['survey_alignment_tolerance_days'] = 10
    with pytest.raises(CalibrationError, match='distinct ordered'):
        run_time_series(settings, hdf)


def test_direct_geotiff_bilinear_nodata_and_xyz_csv(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    transects, _, _ = profiles([0, 0], chainage=[0, 10], u=(0, 5, 10))
    raster_path = tmp_path/'survey.tif'
    raster_values = np.arange(400, dtype='float64').reshape(20, 20)
    raster_values[10, 10] = -9999
    with rasterio.open(raster_path, 'w', driver='GTiff', width=20, height=20, count=1,
                       dtype='float64', crs='EPSG:26915', transform=from_origin(-5, 15, 1, 1), nodata=-9999) as raster:
        raster.write(raster_values, 1)
    settings = {'analysis_crs': 'EPSG:26915', 'integration': {'sample_spacing_m': 1}}
    source = dict(kind='raster', path=str(raster_path), sampling='bilinear', z_scale_to_m=1, z_offset_m=0)
    sampled = read_survey(source, transects, settings)
    # x=0,y=0 is halfway among raster cells row 14/15,col 4/5.
    value = sampled[(sampled.xs_id == 'XS-0') & (sampled.u_m == 0)].z_m.iloc[0]
    assert value == pytest.approx((284+285+304+305)/4)
    bad = transects.copy()
    bad['x_m'], bad['y_m'] = 5.5, 4.5  # Exact NoData cell center.
    assert read_survey(source, bad, settings).z_m.isna().all()
    xyz_path = tmp_path/'points.csv'
    pd.DataFrame({'East': [0, 5, 10], 'North': [0, 0, 0], 'Bed': [2, 3, 4]}).to_csv(xyz_path, index=False)
    source = dict(kind='xyz_csv', path=str(xyz_path), horizontal_mapping_verified=True,
                  fields={'x': 'East', 'y': 'North', 'z': 'Bed'}, z_scale_to_m=.3048)
    mapped = read_survey(source, transects, settings)
    assert mapped.xs_id.eq('XS-0').all()
    np.testing.assert_allclose(mapped.z_m, np.array([2, 3, 4])*.3048)


def test_arcpy_bilinear_failure_never_falls_back_to_nearest(monkeypatch):
    import sys
    from types import SimpleNamespace
    from bathymetry_calibration import arcpy_bridge
    sr = SimpleNamespace(name='known', GCS=SimpleNamespace(name='same'))
    arcpy = SimpleNamespace(env=SimpleNamespace(), Exists=lambda path: True,
                            SetLogHistory=lambda value: None,
                            Describe=lambda path: SimpleNamespace(spatialReference=sr))
    monkeypatch.setitem(sys.modules, 'arcpy', arcpy)
    monkeypatch.setattr(arcpy_bridge, 'spatial_reference', lambda *args: sr)
    def unavailable(*args):
        raise RuntimeError('no Spatial Analyst')
    monkeypatch.setattr(arcpy_bridge, 'sample_raster_batch', unavailable)
    source = dict(kind='gdb_raster', path='fake.gdb', layer='bathy', sampling='bilinear', z_scale_to_m=1, z_offset_m=0)
    with pytest.raises(ValueError, match='substitution is not permitted'):
        arcpy_bridge.execute(dict(operation='profiles', source=source, analysis_crs='EPSG:26915', knots=[]))


def test_gui_qaqc_without_model_reversible_exclusions_and_saved_config(tmp_path, qapp, monkeypatch):
    from bathymetry_calibration.gui import CalibrationWindow
    from tests.test_gui_workflows import wait
    from PySide6.QtWidgets import QFileDialog
    demo = create_demo(tmp_path/'demo')
    points = pd.read_csv(demo/'survey-after.csv')
    points.loc[0, 'z_m'] = 100
    points.to_csv(demo/'survey-after.csv', index=False)
    window = CalibrationWindow(demo/'config.json')
    window.show()
    wait(qapp, lambda: window.settings is not None)
    assert window.before_time.count() == 0
    window.review_surveys()
    wait(qapp, lambda: hasattr(window, 'qaqc_window') and window.workers.idle())
    review = window.qaqc_window
    review.survey.setCurrentText('target')
    review.high_enabled.setChecked(True)
    review.high.setValue(20)
    assert review.preview()
    assert review.reviews['target'].audit.outside_elevation_limits.sum() == 1
    review.exclude_flags.setChecked(True)
    review.apply()
    assert window.settings['surveys']['target']['qaqc']['exclude_flagged']
    assert np.isnan(review.reviews['target'].profile.z_m.iloc[0])
    saved = tmp_path/'reviewed.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(saved), 'JSON'))
    window.save_config()
    assert load_config(saved)['surveys']['target']['qaqc']['elevation_max_m'] == 20
    review.restore()
    review.apply()
    assert not window.settings['surveys']['target']['qaqc']['exclude_flagged']
    assert review.reviews['target'].profile.z_m.iloc[0] == 100
    assert pd.read_csv(demo/'survey-after.csv').z_m.iloc[0] == 100
    review.close()
    window.close()
    qapp.processEvents()


def test_gui_diagnostics_and_profiles_support_text_xs_ids(tmp_path, qapp):
    from bathymetry_calibration.gui import DiagnosticPlotsWindow, SectionProfilesWindow
    transects, before, after = profiles([-2, -1, 1, 2])
    result = compare_profiles(transects, before, after, before, after)
    diagnostic = DiagnosticPlotsWindow(result, {})
    diagnostic.show()
    assert len(diagnostic.figure.axes) == 6
    diagnostic.quantity.setCurrentIndex(1)
    assert diagnostic.figure.axes[4].get_title().startswith('Target bed')
    section = SectionProfilesWindow(result)
    section.show()
    assert len(section.figure.axes) == 2
    section.section.setCurrentText('XS-3')
    assert 'XS-3' in section.figure.axes[0].get_title()
    diagnostic.close()
    section.close()
    qapp.processEvents()


def test_geometry_extraction_uses_consistent_units_and_final_selected_xs(tmp_path):
    from bathymetry_calibration.extract_transects import extract_transects, US_FT_M
    path = tmp_path/'geometry.hdf'
    attributes = np.array([(b'R', b'LMR', b'100', 100.), (b'R', b'LMR', b'90', 100.),
                           (b'R', b'Other', b'80', 100.)],
                          dtype=[('River', 'S8'), ('Reach', 'S8'), ('RS', 'S8'), ('Len Channel', 'f8')])
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('Geometry/Cross Sections/Attributes', data=attributes)
        h5.create_dataset('Geometry/Cross Sections/Polyline Info', data=[[0, 2], [2, 2], [4, 2]])
        h5.create_dataset('Geometry/Cross Sections/Polyline Points', data=[[0, 0], [10, 0], [0, 100], [10, 100], [0, 200], [10, 200]])
    output = tmp_path/'transects.csv'
    extract_transects(path, output, river='R')
    transects = pd.read_csv(output)
    assert set(transects.xs_id) == {'R:LMR:100', 'R:LMR:90'}
    assert transects[transects.xs_id == 'R:LMR:90'].length_to_next_m.isna().all()
    assert transects.u_m.max() == pytest.approx(10*US_FT_M)
    assert transects.x_m.max() == pytest.approx(10*US_FT_M)
    with pytest.raises(ValueError, match='already exists'):
        extract_transects(path, output)


def test_geographic_analysis_crs_is_rejected_before_distance_operations(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    settings['analysis_crs'] = 'EPSG:4326'
    with pytest.raises(CalibrationError, match='projected metre'):
        run_survey_qaqc(settings)


def test_exports_cannot_write_inside_a_source_geodatabase(tmp_path):
    demo = create_demo(tmp_path/'demo')
    settings = load_config(demo/'config.json')
    reviews, provenance = run_survey_qaqc(settings)
    source = tmp_path/'source.gdb'
    source.mkdir()
    provenance = copy.deepcopy(provenance)
    provenance['settings']['surveys']['target']['path'] = str(source)
    with pytest.raises(CalibrationError, match='outside the source'):
        export_survey_qaqc(reviews, provenance, source/'exports')
    assert not list(source.iterdir())


def test_stable_controls_use_only_accepted_intervals_and_unique_points():
    transects, before, after = profiles([1, 1, 1], u=(0., 5., 10., 15., 20.))
    after.loc[after.u_m == 10, 'z_m'] = np.nan
    result = compare_profiles(transects, before, after, before, after, min_coverage=.5)
    controls = [{'xs_id': 'XS-0', 'u_m': 2.5}, {'xs_id': 'XS-0', 'u_m': 2.5},
                {'xs_id': 'XS-1', 'u_m': 7.5}]
    report = datum_shift_review(result.profiles, stable_controls=controls)
    assert report['samples'] == 1 and not report['uniform_shift_candidate']
