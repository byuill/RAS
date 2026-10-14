"""Percentage references, shared-rating behavior, and actual readable diagrams."""
from dataclasses import replace
from itertools import combinations
from pathlib import Path
import time

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from create_BC import Parameters, calculate_budget
from create_BC.budget_view import LOWER_JUNCTIONS, junction_budget
from create_BC.plots import draw_network
from create_BC.ratings import draw_rating_curves, rating_notes
from create_BC.schemes import PASS_RATINGS, RATING_CHOICES, pass_input_flows, pass_outflow, spillway_outflows, terminal_fraction


BASE = Path(__file__).parents[1]/'create_BC'


def data(q=(900000,), orcc=200000):
    return pd.DataFrame(dict(date=pd.date_range('2000-01-01', periods=len(q)), discharge=q,
                             Red_River=20000., ORCC=float(orcc)))


def test_junctions_use_local_inflow_and_merged_flow_with_named_bases():
    row = calculate_budget(data()).flows.iloc[0]
    table = junction_budget(row).set_index('boundary')
    arriving = row.TarbertLanding
    for name in LOWER_JUNCTIONS:
        entry = table.loc[name]
        assert entry.reference_flow_cfs == pytest.approx(arriving)
        assert entry.percent == pytest.approx(-row[name]/arriving*100)
        arriving += row[name]
        assert entry.mainstem_after_cfs == pytest.approx(arriving)
    # Later outlets must not all use Tarbert or input-gauge flow as denominator.
    assert table.loc['CubitsGapWB', 'reference_flow_cfs'] < row.TarbertLanding
    before = row.Thebes+row.Ohio+row.BirdsPoint+row.NewMadrid
    assert table.loc['Hatchie', 'reference_flow_cfs'] == pytest.approx(before+row.Hatchie)
    assert table.loc['Hatchie', 'percent'] == pytest.approx(row.Hatchie/(before+row.Hatchie)*100)


def test_allocation_shares_sum_to_100_and_zero_flow_is_undefined():
    table = junction_budget(calculate_budget(data()).flows.iloc[0]).set_index('boundary')
    for columns in [['Thebes', 'Ohio'], ['ORCC_total', 'TarbertLanding'],
                    ['ORCC_HydroP', 'ORCC_LowSill', 'ORCC_Auxil', 'overBank'],
                    ['ORCC_to_Simmesport', 'Red_River'], ['SWP_Flow', 'SouthPass', 'PassALoutre']]:
        assert table.loc[columns, 'percent'].sum() == pytest.approx(100)
    frame = data(q=(0,), orcc=0)
    frame['Red_River'] = 0
    table = junction_budget(calculate_budget(frame).flows.iloc[0])
    assert table.percent.isna().all()


@pytest.mark.parametrize('p', [Parameters(), replace(Parameters(), mg_a=1e6, ost_a=2., swp_high_offset=.95),
                                replace(Parameters(), spill_style='ratio', bc_low_share=.6, bc_high_share=.2)])
def test_plotted_ratings_and_selected_operating_points_match_engine(p):
    r = calculate_budget(data(q=(150000, 300000, 900000, 2000000)), parameters=p)
    inputs = pass_input_flows(r.flows)
    for rating in PASS_RATINGS:
        _, amount = pass_outflow(inputs[rating.column], rating, p)
        np.testing.assert_allclose(amount, -r.flows[rating.column], atol=1e-8)
    _, fraction = terminal_fraction(r.flows.HeadOfPasses, p)
    np.testing.assert_allclose(fraction*r.flows.HeadOfPasses, -r.flows.SWP_Flow, atol=1e-8)
    morg, bc = spillway_outflows(r.flows.TarbertLanding, p)
    np.testing.assert_allclose(morg, -r.flows.Morganza, atol=1e-8)
    np.testing.assert_allclose(bc, -r.flows.BonnetCarre, atol=1e-8)


@pytest.mark.parametrize('view', ['all', 'regional', 'lower'])
@pytest.mark.parametrize('q', [0, 300000, 2600000])
def test_network_labels_fit_and_do_not_overlap_text_or_connectors(view, q):
    frame = data(q=(q,), orcc=min(q, 620000))
    if q == 0:
        frame['Red_River'] = 0
    r = calculate_budget(frame)
    figure = draw_network(Figure(figsize=(12 if view == 'all' else 6.5, 13.2)), r, view=view)
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    renderer = canvas.get_renderer()
    for ax in figure.axes:
        labels = [t for t in ax.texts if t.get_gid() == 'budget-label']
        boxes = [(t, t.get_window_extent(renderer)) for t in labels]
        for text, box in boxes:
            assert ax.bbox.x0 <= box.x0 and box.x1 <= ax.bbox.x1, text.get_text()
            assert ax.bbox.y0 <= box.y0 and box.y1 <= ax.bbox.y1, text.get_text()
        for (a, box_a), (b, box_b) in combinations(boxes, 2):
            assert not box_a.overlaps(box_b), (a.get_text(), b.get_text())
        connectors = [t.arrow_patch for t in ax.texts if getattr(t, 'arrow_patch', None) is not None]
        for text, box in boxes:
            for connector in connectors:
                assert not box.overlaps(connector.get_window_extent(renderer)), text.get_text()


def test_every_rating_family_renders_and_explains_its_actual_inputs():
    r = calculate_budget(data(q=(200000, 600000, 1800000)))
    for choice, _ in RATING_CHOICES:
        figure = draw_rating_curves(Figure(figsize=(11, 12 if choice == 'all_passes' else 5)), r, choice=choice)
        FigureCanvasAgg(figure).draw()
        assert figure.axes and rating_notes(r, choice)
    assert 'inactive' in rating_notes(r, 'orcc')
    assert 'not a rating of today' in rating_notes(r, 'birds')
    assert 'not a verified calibration range' in rating_notes(r, 'MGP')


def test_gui_preserves_selected_day_disables_inactive_parameters_and_updates_ratings(qapp, tmp_path):
    from create_BC.gui import BoundaryWindow
    path = tmp_path/'daily.csv'
    data(q=(300000, 600000, 900000)).to_csv(path, index=False)
    w = BoundaryWindow(path)
    w.resize(1200, 800)
    w.show()

    def wait():
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            qapp.processEvents()
            if w.result is not None and w.workers.idle():
                return
            time.sleep(.01)
        pytest.fail('GUI calculation did not finish')

    wait()
    assert not w.editors['orcc_ratio'].isEnabled()
    assert not w.editors['bc_switch'].isEnabled()
    w.slider.setValue(2)
    w._render_day()
    w.rating_choice.setCurrentIndex(w.rating_choice.findData('PALH'))
    assert 'Point à la Hache' in w.rating_explanation.toPlainText()
    w._edit_rating_parameters()
    assert w.group_combo.currentText() == 'Pass rating curves'
    w.network_view.setCurrentIndex(w.network_view.findData('lower'))
    assert len(w.network.figure.axes) == 1
    w.editors['orcc_mode'].setCurrentIndex(1)
    assert w.editors['orcc_ratio'].isEnabled()
    assert not w.export_button.isEnabled()
    w.calculate()
    wait()
    assert w.slider.value() == 2
    assert w.junction_ledger.rowCount() > 20
    w.rating_auto.setChecked(False)
    w.rating_max.setValue(750000)
    assert w.ratings.figure.axes[0].get_xlim()[1] == 750000
    w.rating_raw.setChecked(True)
    assert any(line.get_label() == 'Raw formula' for line in w.ratings.figure.axes[0].lines)
    w.close()
