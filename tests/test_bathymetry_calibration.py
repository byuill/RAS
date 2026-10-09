import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bathymetry_calibration.cache import ProfileCache, cache_key
from bathymetry_calibration.core import CalibrationError, compare_profiles
from bathymetry_calibration.demo import create_demo
from bathymetry_calibration.workflow import export_comparison, load_config, run_comparison


def setup_demo(tmp_path):
    directory = create_demo(tmp_path/'demo')
    return directory, load_config(directory/'config.json')


def test_known_volume_temporal_difference_spatial_sum_and_cache(tmp_path):
    directory, settings = setup_demo(tmp_path)
    hdf = directory/'synthetic.p01.hdf'
    result, provenance = run_comparison(settings, hdf, 'baseline', 'target', 0, 1)
    assert result.metrics['model_total_m3'] == pytest.approx(2000)
    assert result.metrics['total_bias_m3'] == 0
    assert result.sections.model_local_control_volume_m3.tolist() == [500, 1000, 500]
    assert result.sections.model_cumulative_m3.tolist() == [500, 1500, 2000]
    assert result.sections.native_local_m3.tolist() == [500, 1000, 500]
    assert result.sections.native_cumulative_m3.tolist() == [500, 1500, 2000]
    assert not any(row['hit'] for row in provenance['cache'])
    repeated, provenance = run_comparison(settings, hdf, 'baseline', 'target', 0, 1)
    assert all(row['hit'] for row in provenance['cache'])
    pd.testing.assert_frame_equal(result.sections, repeated.sections)
    saved = export_comparison(result, provenance, tmp_path/'exports')
    assert len(pd.read_csv(saved/'intervals.csv')) == 2
    assert json.loads((saved/'report.json').read_text())['metrics']['observed_total_m3'] == 2000


def test_native_already_spatially_cumulative_is_not_double_summed(tmp_path):
    directory, settings = setup_demo(tmp_path)
    settings['native_volume'].update(dataset='native_spatial', semantics='spatial_temporally_cumulative',
                                     spatial_order_columns=[0, 1, 2])
    result, _ = run_comparison(settings, directory/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    assert result.sections.native_local_m3.tolist() == [500, 1000, 500]
    assert result.sections.native_cumulative_m3.tolist() == [500, 1500, 2000]
    assert result.metrics['native_minus_reconstructed_total_m3'] == 0


def test_native_unsigned_storage_preserves_erosion_sign(tmp_path):
    import h5py
    from bathymetry_calibration.sources import native_volume_audit
    directory, settings = setup_demo(tmp_path)
    with h5py.File(directory/'synthetic.p01.hdf', 'a') as h5:
        h5.create_dataset('unsigned_local', data=np.array([[1000, 2000, 1000], [500, 1000, 500]], dtype='uint64'))
    mapping = dict(settings['native_volume'], dataset='unsigned_local')
    sections = pd.DataFrame({'model_column': [0, 1, 2]})
    assert native_volume_audit(directory/'synthetic.p01.hdf', mapping, sections, 0, 1).tolist() == [-500, -1000, -500]


def test_no_nan_bridge_no_extrapolation_and_common_support(tmp_path):
    directory, _ = setup_demo(tmp_path)
    transects = pd.read_csv(directory/'transects.csv')
    before = pd.read_csv(directory/'survey-before.csv')
    after = pd.read_csv(directory/'survey-after.csv')
    after.loc[(after.xs_id == 'B') & (after.u_m == 5), 'z_m'] = np.nan
    with pytest.raises(CalibrationError, match='coverage'):
        compare_profiles(transects, before, before, before, after)
    cropped = pd.read_csv(directory/'survey-after.csv').query('u_m > 0')
    with pytest.raises(CalibrationError, match='coverage'):
        compare_profiles(transects, before, before, before, cropped)
    with pytest.raises(CalibrationError, match='coverage'):
        compare_profiles(transects, before, before, before, before, max_gap_m=4)


def test_erosion_sign_unequal_lengths_and_nonuniform_profiles(tmp_path):
    directory, _ = setup_demo(tmp_path)
    transects = pd.read_csv(directory/'transects.csv')
    transects.loc[transects.xs_id == 'B', 'length_to_next_m'] = 200
    before = pd.read_csv(directory/'survey-before.csv')
    after = before.copy()
    after['z_m'] = after.xs_id.map({'A': -1., 'B': -2., 'C': -3.})
    result = compare_profiles(transects, before, after, before, after)
    # Areas [-10,-20,-30], lengths [100,200]: -1500-5000 = -6500 m³.
    assert result.metrics['model_total_m3'] == -6500
    assert result.sections.model_local_control_volume_m3.tolist() == [-500, -3000, -3000]
    assert result.sections.model_cumulative_m3.tolist() == [-500, -3500, -6500]
    assert result.sections.model_interval_prefix_m3.tolist() == [0, -1500, -6500]


def test_verification_gates_dates_and_duplicate_stations(tmp_path):
    directory, settings = setup_demo(tmp_path)
    for key in ('spatial_mapping_verified', 'temporal_alignment_verified'):
        bad = copy.deepcopy(settings)
        bad[key] = False
        with pytest.raises(CalibrationError, match='verified'):
            run_comparison(bad, directory/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    bad = copy.deepcopy(settings)
    bad['surveys']['target']['date'] = '2025-01-02'
    with pytest.raises(CalibrationError, match='tolerance'):
        run_comparison(bad, directory/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)
    points = pd.read_csv(directory/'survey-before.csv')
    pd.concat([points, points.iloc[:1]]).to_csv(directory/'survey-before.csv', index=False)
    with pytest.raises(CalibrationError, match='Duplicate'):
        run_comparison(settings, directory/'synthetic.p01.hdf', 'baseline', 'target', 0, 1)


def test_cache_content_invalidation_and_corruption(tmp_path):
    directory, settings = setup_demo(tmp_path)
    source = settings['surveys']['target']
    key1 = cache_key(source, settings['transects'], {})
    points = pd.read_csv(source['path'])
    cache = ProfileCache(directory/'cache')
    cache.put(key1, points)
    assert cache.get(key1) is not None
    path = directory/'cache'/f'{key1}.json'
    payload = json.loads(path.read_text())
    payload['records'][0]['z_m'] = 123
    path.write_text(json.dumps(payload))
    assert cache.get(key1) is None
    points['z_m'] += 1
    points.to_csv(source['path'], index=False)
    assert cache_key(source, settings['transects'], {}) != key1


def test_gui_comparison_worker_and_plot(tmp_path, qapp):
    import time
    from bathymetry_calibration.gui import CalibrationWindow
    directory, _ = setup_demo(tmp_path)
    window = CalibrationWindow(directory/'config.json', directory/'synthetic.p01.hdf')
    errors = []
    window.failed.connect(errors.append)
    window.show()
    deadline = time.monotonic()+20
    while window.before_time.count() == 0 and not errors and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert not errors and window.before_time.count() == 2
    window.compare()
    while window.result is None and not errors and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert not errors and window.result is not None
    assert window.result.metrics['model_total_m3'] == 2000
    assert len(window.figure.axes) == 2
    assert window.export_button.isEnabled()
    window.after_survey.setCurrentIndex(0)
    assert window.result is None and not window.export_button.isEnabled()
    window.close()
    qapp.processEvents()
