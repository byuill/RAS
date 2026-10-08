import numpy as np
import pandas as pd

from observations.discharge_proxy import fill_discharge, flow_series, load_rules, select_lag
from observations.processing import ObservationSet, _blank
from observations.station_catalog import StationCatalog


def samples(times, q=None):
    frame = _blank(pd.DatetimeIndex(times))
    frame['kind'] = 'sample'; frame['ssc_mg_l'] = 100.
    frame['discharge_m3s'] = np.nan if q is None else q
    for field in ('ssl_kg_s','sand_mg_l','fines_mg_l'): frame[field] = np.nan
    return ObservationSet('target', 'Sediment station', frame)


def test_reported_q_preserved_and_all_branch_terms_required():
    times = pd.date_range('2004-01-01', periods=3, freq='D')
    obs = samples(times, [999., np.nan, np.nan])
    upstream = pd.Series([100., 200., 300.], index=times)
    tributary = pd.Series([10., 20., np.nan], index=times)
    recipe = {'name': 'upstream plus tributary', 'terms': [{'station': 'main'}, {'station': 'tributary'}]}
    result = fill_discharge(obs, recipes=[recipe], flows={'main': upstream, 'tributary': tributary})
    np.testing.assert_allclose(result.df.discharge_m3s, [999., 220., np.nan], equal_nan=True)
    assert result.df.q_is_proxy.tolist() == [False, True, False]
    assert result.df.q_original_m3s.iloc[0] == 999 and np.isnan(result.df.q_original_m3s.iloc[1])
    assert result.df.ssl_kg_s.iloc[1] == 22
    assert np.isnan(obs.df.discharge_m3s.iloc[1])
    missing = fill_discharge(obs, recipes=[recipe], flows={'main': upstream})
    assert missing.df.discharge_m3s.iloc[1:].isna().all()


def test_diversion_subtraction_routing_gaps_and_operation_guards():
    times = pd.date_range('2011-01-01', periods=4, freq='D')
    obs = samples(times)
    recipe = {'name': 'below diversion', 'terms': [{'station': 'main', 'lag_hours': 24},
              {'station': 'outlet', 'coefficient': -1, 'lag_hours': 24}]}
    flows = {'main': pd.Series([100,200,300,400], index=times), 'outlet': pd.Series([10,20,30,40], index=times)}
    result = fill_discharge(obs, recipes=[recipe], flows=flows)
    np.testing.assert_allclose(result.df.discharge_m3s, [np.nan,90,180,270], equal_nan=True)
    guarded = dict(recipe, blocked_years=[2011])
    assert fill_discharge(obs, recipes=[guarded], flows=flows).df.discharge_m3s.isna().all()
    guarded = dict(recipe, valid_through='2010-12-31')
    assert fill_discharge(obs, recipes=[guarded], flows=flows).df.discharge_m3s.isna().all()
    inverse = {'name': 'downstream inverse routing', 'terms': [{'station':'main','lag_hours':-24}]}
    routed = fill_discharge(obs, recipes=[inverse], flows=flows)
    np.testing.assert_allclose(routed.df.discharge_m3s, [200,300,400,np.nan], equal_nan=True)


def test_same_site_subdaily_precedes_daily_and_qaqc_exclusions_not_refilled():
    times = pd.date_range('2004-01-01 12:00', periods=3, freq='D')
    obs = samples(times)
    flow = _blank(pd.DatetimeIndex(['2004-01-01','2004-01-02','2004-01-03','2004-01-02 11:00','2004-01-02 13:00']))
    flow['kind'] = ['daily']*3 + ['instantaneous']*2
    flow['discharge_m3s'] = [100,200,300,245,255]
    local = ObservationSet('same', 'Same-site hydrograph', flow)
    result = fill_discharge(obs, local, local_station_id='same')
    np.testing.assert_allclose(result.df.discharge_m3s, [100,250,300])
    assert result.df.q_sources.eq('same').all()
    assert result.df.q_method.iloc[1] == 'same-station subdaily interpolation'
    obs.df['qaqc_excluded_fields'] = ['','discharge_m3s','']
    result = fill_discharge(obs, local)
    assert np.isnan(result.df.discharge_m3s.iloc[1])
    local.df['q_is_proxy'] = True
    assert flow_series(local).empty


def test_lag_selection_improves_chronological_holdout_without_scaling_flow():
    times = pd.date_range('2004-01-01 12:00', periods=45, freq='D')
    rng = np.random.default_rng(71)
    flow = pd.Series(100 + rng.uniform(0, 300, 45), index=times)
    obs = samples(times[3:-1], flow.to_numpy()[2:-2])
    recipe = {'name':'routed mainstem', 'terms':[{'station':'main','lag_hours':0}],
              'primary_lag_candidates_hours':[0,24,48]}
    lag, note, validation = select_lag(recipe, {'main':flow}, obs.df)
    assert lag == 24 and 'holdout' in note
    assert validation['selected_holdout_rmse_m3s'] == 0
    assert validation['default_holdout_rmse_m3s'] > 0
    lag, note, _ = select_lag(recipe, {'main':flow}, obs.df.iloc[:5])
    assert lag == 0 and 'too few' in note


def test_catalog_and_rules_do_not_cross_old_river_or_double_count_yazoo():
    catalog = StationCatalog.load(); rules = load_rules()
    assert len(catalog) >= 22
    for station_id, recipes in rules.items():
        assert catalog.get(station_id)
        for recipe in recipes:
            for term in recipe['terms']: assert catalog.get(term['station'])
    union = rules['USGS-07295025'][0]
    assert [term['station'] for term in union['terms']] == ['USGS-07289000','USGS-07290000']
    assert rules['USGS-07295100'][0]['blocked_years'] == [1973,2011]
    assert 'USGS-07374525' not in rules  # no uncorrected Baton Rouge -> Belle Chasse transfer
