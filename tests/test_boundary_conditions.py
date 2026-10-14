"""Conservation, operating limits, and actual exports for the BC workbench."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from create_BC import Parameters, calculate_budget
from create_BC.engine import ORCC_COLUMNS, INFLOW_COLUMNS, EXTRACTION_COLUMNS
from create_BC.export import export_result, write_dss


BASE = Path(__file__).parents[1]/'create_BC'


def inputs(q, red=20000, orcc=50000, start='2000-01-01'):
    q = np.atleast_1d(q).astype(float)
    return pd.DataFrame(dict(date=pd.date_range(start, periods=len(q)), discharge=q,
                             Red_River=np.broadcast_to(red, q.shape), ORCC=np.broadcast_to(orcc, q.shape)))


def assert_budgets(r):
    f = r.flows
    assert np.isfinite(f.select_dtypes(include=np.number)).all().all()
    assert (f[INFLOW_COLUMNS] >= -1e-7).all().all()
    assert (f[EXTRACTION_COLUMNS] <= 1e-7).all().all()
    for col in ['orcc_residual_cfs', 'latitude_residual_cfs', 'lower_residual_cfs']:
        assert f[col].abs().max() < 1e-6
    assert np.allclose(f.whole_system_residual_cfs, -f.upstream_residual_cfs, atol=1e-6)


def test_complete_included_calibration():
    r = calculate_budget(BASE/'new_data_RF.csv')
    assert len(r.flows) == 9497
    assert r.summary['issue_counts']['orcc_adjusted'] == 37
    assert r.summary['max_abs_residual_cfs']['upstream_residual_cfs'] == pytest.approx(135929.352)
    assert_budgets(r)
    # Independent first-day accounting; retain the observed UP, Red, and ORCC values.
    first = r.flows.iloc[0]
    assert first.TarbertLanding == 223000
    assert first.Simmesport == 96000
    assert first.upstream_residual_cfs == pytest.approx(304000*(1-.352646-.432026-.156022))
    assert first.HeadOfPasses == pytest.approx(154692.97363003995)


def test_monthly_fraction_consistent_on_first_and_last_day_and_calendar_ratios():
    frame = inputs([500000, 500000])
    table = pd.DataFrame({str(m): [.25] for m in range(1, 13)})
    f = calculate_budget(frame, table).flows
    assert (f.Thebes/f[['Thebes', 'Ohio']].sum(axis=1)).to_list() == [.25, .25]
    ratio_table = table*4/3
    f = calculate_budget(frame, ratio_table, replace(Parameters(), split_semantics='ratio')).flows
    assert np.allclose(f.Thebes/f[['Thebes', 'Ohio']].sum(axis=1), .25)
    with pytest.raises(ValueError, match='choose ratio'):
        calculate_budget(frame, BASE/'ohio_split_cy.csv')
    assert_budgets(calculate_budget(frame, BASE/'ohio_split_cy.csv', replace(Parameters(), split_semantics='ratio')))


def test_infeasible_minimums_and_final_day_redistribution():
    r = calculate_budget(inputs([1000, 100000], orcc=0))
    assert r.summary['issue_counts']['headwater_min_unmet'] == 1
    assert r.flows.Thebes.iloc[-1] == 30000
    assert_budgets(r)


def test_overlapping_floodway_returns_and_end_of_run_tail():
    p = replace(Parameters(), bp_threshold=100, bp_lag=2, bp_efficiency=.8, upstream_balance='close_minor')
    r = calculate_budget(inputs([500000]*4), parameters=p)
    diverted = .784672*500000-100
    assert r.flows.NewMadrid.iloc[2] == pytest.approx(diverted*.5*.8)
    assert r.flows.NewMadrid.iloc[3] == pytest.approx(diverted*.75*.8)
    s = r.summary
    assert s['floodway_diverted_ft3'] == pytest.approx(s['floodway_returned_ft3']+s['floodway_loss_ft3']+s['floodway_tail_ft3'])
    assert s['floodway_final_storage_ft3'] == pytest.approx(s['floodway_tail_ft3'])
    assert r.flows.upstream_residual_cfs.abs().max() < 1e-6
    assert_budgets(r)


@pytest.mark.parametrize('mode', ['prescribed', 'calculated'])
@pytest.mark.parametrize('reference', ['union_point', 'tarbert'])
def test_operating_extremes_and_capacity_limits(mode, reference):
    q = [0, 1000, 50000, 299999, 300000, 1000000, 1600000, 2600000]
    frame = inputs(q, red=1000, orcc=[0, 10000, 3000, 200000, 620000, 8000, 680000, 1000000])
    p = replace(Parameters(), orcc_mode=mode, input_reference=reference, orcc_flux=.9,
                ls_cap=50000, overbank_cap=20000, aux_cap=25000, orcc_override=True)
    r = calculate_budget(frame, parameters=p)
    assert_budgets(r)
    f = r.flows
    assert (-f.ORCC_LowSill <= p.ls_cap).all()
    assert (-f.overBank <= p.overbank_cap).all()
    assert (-f.ORCC_Auxil <= p.aux_cap).all()
    assert (f.ORCC_total <= f.UnionPoint).all()
    assert (-f.ORCC_HydroP <= f.ORCC_total).all()


def test_high_mainstem_low_orcc_cannot_overallocate_hydropower():
    f = calculate_budget(inputs([1300000], orcc=8000)).flows.iloc[0]
    assert f.ORCC_HydroP == -8000
    assert f[ORCC_COLUMNS].sum() == -8000
    assert f.ORCC_LowSill == f.ORCC_Auxil == f.overBank == 0


def test_low_flow_reduced_auxiliary_capacity_preserves_operating_preference():
    r = calculate_budget(inputs([200000], orcc=200000), parameters=replace(Parameters(), aux_cap=25000))
    f = r.flows.iloc[0]
    assert f.ORCC_total == 175000
    assert f.ORCC_LowSill == f.overBank == 0
    assert f.ORCC_Auxil == -25000
    assert_budgets(r)


def test_negative_pass_ratings_do_not_create_water():
    f = calculate_budget(inputs([180000], orcc=50000)).flows.iloc[0]
    assert f.MGP == f.PALH == f.FSP == 0
    expected_ost = .1043*130000-8130
    assert f.OstNep == pytest.approx(-expected_ost)
    assert f.lower_residual_cfs == pytest.approx(0, abs=1e-7)


def test_independent_spill_threshold_does_not_make_morganza_inflow():
    p = replace(Parameters(), bc_switch=100, bc_limit=300000)
    r = calculate_budget(inputs([1500000], orcc=200000), parameters=p)
    assert r.flows.BonnetCarre.iloc[0] == -50000
    assert r.flows.Morganza.iloc[0] == 0
    assert_budgets(r)


def test_eflow_fallback_and_limited_target_are_reported():
    df = inputs([800000]*3, red=50000, orcc=150000)
    df['Eflows'] = [250000, 600000, 10000]
    r = calculate_budget(df, parameters=replace(Parameters(), eflows=True))
    assert r.flows.Simmesport.iloc[0] == 250000
    assert r.summary['issue_counts']['eflow_fallback'] == 1
    assert r.summary['eflow_unmet_days'] == 1
    assert_budgets(r)


def test_seeded_sampling_and_perturbations_are_repeatable():
    frame = inputs([600000]*400)
    p = replace(Parameters(), split_sampling='sample_year', annual_flux=.1, orcc_flux=.1)
    a, b = calculate_budget(frame, parameters=p), calculate_budget(frame, parameters=p)
    pd.testing.assert_frame_equal(a.flows, b.flows)
    c = calculate_budget(frame, parameters=replace(p, seed=43))
    assert not a.flows.Thebes.equals(c.flows.Thebes)
    assert a.flows.RandomFlux_A.iloc[-1] != 0
    assert_budgets(a)


@pytest.mark.parametrize('fault', ['gap', 'duplicate', 'nan', 'negative', 'reverse'])
def test_bad_inputs_are_rejected(fault):
    df = inputs([600000]*3)
    if fault == 'gap': df.loc[2, 'date'] += pd.Timedelta(days=1)
    if fault == 'duplicate': df.loc[1, 'date'] = df.date.iloc[0]
    if fault == 'nan': df.loc[1, 'ORCC'] = np.nan
    if fault == 'negative': df.loc[2, 'discharge'] = -1
    if fault == 'reverse': df = df.iloc[::-1]
    with pytest.raises(ValueError): calculate_budget(df)


def test_json_roundtrip_rejects_unknown_and_nonfinite(tmp_path):
    p = replace(Parameters(), swp_quad=9e-12, seed=17)
    p.save(tmp_path/'scenario.json')
    assert Parameters.load(tmp_path/'scenario.json') == p
    (tmp_path/'scenario.json').write_text('{"not_a_setting": 1}')
    with pytest.raises(ValueError, match='Unknown'): Parameters.load(tmp_path/'scenario.json')
    with pytest.raises(ValueError, match='finite'): replace(p, mg_a=float('nan')).validate()


def test_custom_return_kernel_and_closure_are_saved(tmp_path):
    p = replace(Parameters(), bp_threshold=100000, bp_lag=0, bp_return_weights=(.6, .4),
                upstream_balance='close_minor', bp_efficiency=.9)
    p.save(tmp_path/'custom.json')
    assert Parameters.load(tmp_path/'custom.json') == p
    r = calculate_budget(inputs([500000]*3), parameters=p)
    diverted = .784672*500000-100000
    assert r.flows.NewMadrid.iloc[0] == pytest.approx(diverted*.6*.9)
    assert r.flows.NewMadrid.iloc[1] == pytest.approx(diverted*.9)
    assert_budgets(r)
    with pytest.raises(ValueError, match='sum to one'):
        replace(p, bp_return_weights=(.6, .5)).validate()


def test_supplied_states_drive_ratio_and_structure_preferences():
    df = inputs([1000000]*5, orcc=200000)
    df['state'] = [0, 1, 1.5, 2, 3]
    p = replace(Parameters(), use_input_state=True, orcc_mode='calculated', rising_ratio=.6,
                falling_ratio=.8, low_ratio=.9)
    r = calculate_budget(df, parameters=p)
    assert r.flows.Rising_ID.to_list() == [0, 1, 1.5, 2, 3]
    assert r.flows.ORCC_total.to_list() == pytest.approx([286000, 388000, 388000, 184000, 82000])
    assert_budgets(r)


def test_smoothing_changes_forcing_but_preserves_source_and_allocation():
    df = inputs([300000, 800000, 1000000, 400000, 300000, 200000, 500000])
    r = calculate_budget(df, parameters=replace(Parameters(), smooth_days=5))
    pd.testing.assert_series_equal(r.input_data.discharge, df.discharge)
    assert not np.allclose(r.flows.forcing_flow, df.discharge)
    assert r.summary['issue_counts']['smoothed_forcing'] == len(df)
    assert_budgets(r)


def test_export_is_complete_reproducible_and_non_destructive(tmp_path):
    r = calculate_budget(inputs([600000]*3, start='2000-02-28'))
    out = export_result(r, tmp_path)
    assert {'flows.csv', 'parameters.json', 'report.json', 'qaqc_issues.csv', 'ForRon.xlsx',
            'river_budget.png', 'hydrographs.png', 'boundary_roles.csv'} <= {p.name for p in out.iterdir()}
    assert json.loads((out/'report.json').read_text())['days'] == 3
    assert export_result(r, tmp_path) != out
    assert len(pd.read_csv(out/'flows.csv')) == 3


def test_dss_values_dates_signs_and_stage_roundtrip(tmp_path):
    pytest.importorskip('pydsstools')
    from pydsstools.heclib.dss import HecDss
    r = calculate_budget(inputs([600000, 500000, 400000], start='2000-02-28'))
    stage = pd.DataFrame({'date': r.flows.date, 'stage_ft': [2., 2.5, -1.]})
    path = tmp_path/'flows.dss'
    records = write_dss(r, path, 'TEST', stage)
    assert len(records) == 34
    with HecDss.Open(str(path)) as f:
        ts = f.read_ts('/IRREGULAR/TL_UP/FLOW//1DAY/TEST/', window=('28FEB2000 0000', '01MAR2000 0000'))
        assert list(ts.values) == [600000, 500000, 400000]
        assert list(t.datetime() for t in ts.times) == list(r.flows.date)
    with pytest.raises(FileExistsError): write_dss(r, path)
    stage.loc[2, 'date'] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match='Stage dates'): write_dss(r, tmp_path/'bad.dss', stage=stage)
    assert not (tmp_path/'bad.dss').exists()


def test_gui_calculates_edits_refreshes_and_exports(tmp_path, qapp, monkeypatch):
    import time
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from create_BC.gui import BoundaryWindow
    source = tmp_path/'flows.csv'
    inputs([600000, 700000, 800000]).to_csv(source, index=False)
    window = BoundaryWindow(source)
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: errors.append(a[-1]))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)

    def wait():
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            qapp.processEvents()
            if window.result is not None and window.workers.idle():
                qapp.processEvents()
                return
            time.sleep(.005)
        pytest.fail('GUI did not complete')

    window.show()
    wait()
    assert window.result.flows.TarbertLanding.iloc[0] == 550000
    assert window.export_button.isEnabled()
    window.editors['orcc_mode'].setCurrentIndex(1)
    window.editors['orcc_ratio'].setText('0.8')
    assert window.dirty and not window.export_button.isEnabled()
    window.calculate()
    wait()
    assert window.result.flows.TarbertLanding.iloc[0] == pytest.approx((600000+20000)*.8)
    window.slider.setValue(2)
    window._render_day()
    assert window.date_edit.date().toPython() == window.result.flows.date.iloc[-1].date()
    assert window.network.figure.axes and window.ledger.rowCount() > 20
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a: str(tmp_path/'exports'))
    window.include_dss.setChecked(False)
    window._export()
    wait()
    assert len(list((tmp_path/'exports').glob('boundary-*/report.json'))) == 1
    assert not errors
    window.close()
