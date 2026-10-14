"""Incomplete gauge observations must not become fabricated ORCC flow."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from create_BC import Generate_dataFile_Input as download


def response(values, **extra):
    class Response:
        def raise_for_status(self): pass
        def json(self): return dict(units='cfs', values=values, **extra)
    return Response()


def test_paginated_flow_units_and_complete_short_gap_interpolation(monkeypatch):
    dates = pd.date_range('2000-01-01', periods=15)
    values = [[int(t.timestamp()*1000), float(i), 0] for i,t in enumerate(dates)]
    for i in [1, 2, 5, 6, 7, 8, 9, 10, 11, 12]: values[i][1] = None
    pages = [response(values[:7], **{'next-page': 'two'}), response(values[7:])]
    queries = []
    def get(*args, **kwargs):
        queries.append(kwargs['params'])
        return pages.pop(0)
    monkeypatch.setattr(download.requests, 'get', get)
    out = download.fetch_cwms_timeseries('Normal.Flow', dates[0], dates[-1])
    assert out.value.iloc[1:3].to_list() == [1., 2.]
    assert out.value.iloc[5:13].isna().all()
    assert queries[1]['page'] == 'two'
    monkeypatch.setattr(download.requests, 'get', lambda *a, **k: response(values))
    overbank = download.fetch_cwms_timeseries('ORCC-Overbank.Flow', dates[0], dates[-1])
    assert overbank.value.iloc[1:3].isna().all()


def test_orcc_total_requires_all_four_structures(monkeypatch):
    def fetch(name, start, end):
        return pd.DataFrame(dict(date=pd.date_range(start, periods=2), value=[100, np.nan if 'Overbank' in name else 100]))
    monkeypatch.setattr(download, 'fetch_cwms_timeseries', fetch)
    out = download.download_orcc_total(datetime(2000,1,1), datetime(2000,1,2))
    assert out.ORCC.iloc[0] == 400
    assert np.isnan(out.ORCC.iloc[1])


def test_incomplete_cwms_unit_metadata_is_rejected(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'values': [[0,100]]}
    monkeypatch.setattr(download.requests, 'get', lambda *a, **k: Response())
    with pytest.raises(RuntimeError, match='unexpected flow units'):
        download.fetch_cwms_timeseries('Normal.Flow', datetime(2000,1,1), datetime(2000,1,2))
