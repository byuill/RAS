"""Synthetic limb examples must follow the production classifier and stay readable."""
from dataclasses import replace
from itertools import combinations
import time

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from create_BC.engine import calculate_budget
from create_BC.limb_delineation import draw_limb_delineation, synthetic_limb_delineation
from create_BC.parameters import Parameters


def test_default_example_has_spring_flood_and_fall_low_water():
    data = synthetic_limb_delineation(Parameters())
    assert len(data) == 365 and data.date.is_monotonic_increasing
    assert set(data.state) == {0, 1, 1.5, 2, 3}
    assert data.loc[data.discharge.idxmax(), 'date'].month in {4, 5}
    assert data.loc[data.discharge.idxmin(), 'date'].month == 10
    assert data.loc[data.date.dt.month.isin([10, 11]), 'state'].eq(3).sum() >= 45
    assert data.discharge.between(200000, 1500000).all()
    assert data[['rise_trigger', 'recent_mean']].notna().all().all()


@pytest.mark.parametrize('changes', [dict(), dict(input_reference='tarbert'),
                                    dict(crest_days=0, rise_window=7),
                                    dict(smooth_days=31, consider_head=True),
                                    dict(smooth_days=365, rise_window=365)])
def test_example_matches_full_budget_engine_with_trailing_history(changes):
    p = replace(Parameters(), **changes)
    illustrated = synthetic_limb_delineation(p)
    raw = synthetic_limb_delineation(replace(p, smooth_days=0))
    source = pd.DataFrame(dict(date=pd.date_range('2000-01-02', periods=730),
                               discharge=np.tile(raw.raw_discharge, 2),
                               Red_River=np.tile(raw.red_river, 2), ORCC=200000.))
    result = calculate_budget(source, parameters=p)
    np.testing.assert_array_equal(illustrated.state, result.flows.Rising_ID.iloc[365:])
    np.testing.assert_array_equal(illustrated.head_constraint, result.flows.head_constraint.iloc[365:])


def test_parameter_changes_reclassify_fixed_forcing_without_manufacturing_states():
    p = Parameters()
    original = synthetic_limb_delineation(p)
    low = synthetic_limb_delineation(replace(p, low_water=450000))
    crest = synthetic_limb_delineation(replace(p, crest_days=0))
    no_flood = synthetic_limb_delineation(replace(p, rise_min=2000000))
    for changed in [low, crest, no_flood]:
        np.testing.assert_array_equal(changed.discharge, original.discharge)
    assert low.state.eq(3).sum() > original.state.eq(3).sum()
    assert crest.state.eq(1.5).sum() > original.state.eq(1.5).sum()
    assert not no_flood.state.isin([1, 1.5, 2]).any()


@pytest.mark.parametrize('size', [(12, 9), (16, 11)])
@pytest.mark.parametrize('changes', [dict(), dict(use_input_state=True, consider_head=True),
                                    dict(rise_min=1e9, fall_min=1e9, low_water=1e9,
                                         rise_threshold=1e9, rise_window=365, crest_days=365)])
def test_plot_annotation_boxes_fit_without_overlapping_each_other_or_data(size, changes):
    figure = draw_limb_delineation(Figure(figsize=size), replace(Parameters(), **changes))
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    renderer = canvas.get_renderer()
    hydrograph, strip, rules = figure.axes
    boxes = [text.get_bbox_patch().get_window_extent(renderer) for text in rules.texts]
    assert len(boxes) == 4
    for box in boxes:
        assert figure.bbox.contains(box.x0, box.y0) and figure.bbox.contains(box.x1, box.y1)
        assert not box.overlaps(hydrograph.bbox) and not box.overlaps(strip.bbox)
    for first, second in combinations(boxes, 2):
        assert not first.overlaps(second)
    labels = list(figure.texts) + list(hydrograph.get_yticklabels()) + [hydrograph.yaxis.label]
    labels += list(strip.get_xticklabels()) + [strip.yaxis.label]
    labels += hydrograph.get_legend().get_texts() + figure.legends[0].get_texts()
    extents = [text.get_window_extent(renderer) for text in labels if text.get_text()]
    for box in extents:
        assert figure.bbox.contains(box.x0, box.y0) and figure.bbox.contains(box.x1, box.y1)
        assert not any(box.overlaps(rule) for rule in boxes)
    for first, second in combinations(extents, 2):
        assert not first.overlaps(second)


def test_gui_update_uses_unsaved_edits_and_preserves_budget_on_invalid_input(qapp, tmp_path):
    from create_BC.gui import BoundaryWindow

    path = tmp_path/'daily.csv'
    pd.DataFrame(dict(date=pd.date_range('2001-01-01', periods=3),
                      discharge=[400000, 450000, 500000], Red_River=20000., ORCC=150000.)).to_csv(path, index=False)
    window = BoundaryWindow(path)
    try:
        window.resize(1200, 800)
        window.show()
        index = next(i for i in range(window.tabs.count()) if window.tabs.tabText(i) == 'Limb delineation')
        window.tabs.setCurrentIndex(index)
        deadline = time.monotonic()+25
        while time.monotonic() < deadline and (window.result is None or not window.workers.idle()):
            qapp.processEvents()
            time.sleep(.01)
        assert window.result is not None and window.workers.idle()
        result = window.result
        original = window.limb_data.copy()
        window.editors['low_water'].setText('450000')
        assert 'click Update plot' in window.limb_status.text()
        pd.testing.assert_frame_equal(window.limb_data, original)
        window.limb_update_button.click()
        assert window.limb_data.state.eq(3).sum() > original.state.eq(3).sum()
        assert any('450,000' in t.get_text() for t in window.limb_plot.figure.axes[2].texts)
        assert window.result is result and window.dirty and not window.export_button.isEnabled()
        good = window.limb_data.copy()
        window.editors['low_water'].setText('invalid')
        window.limb_update_button.click()
        assert 'Plot unchanged: low_water' in window.limb_status.text()
        pd.testing.assert_frame_equal(window.limb_data, good)
        window.set_parameters(replace(Parameters(), crest_days=0))
        assert 'click Update plot' in window.limb_status.text()
        window.limb_update_button.click()
        assert window.limb_data.state.eq(1.5).sum() > original.state.eq(1.5).sum()
        assert window.result is result
    finally:
        window.close()
