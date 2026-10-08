import numpy as np
import pandas as pd

from analysis.observed import observed_series
from analysis.time_series_calibration import sediment_records
from observations.processing import ObservationSet, _blank
from observations.qaqc import apply_exclusions, review_observations


def test_outlier_flags_censoring_and_physical_bounds_do_not_modify_raw_data():
    times = pd.date_range('2004-01-01', periods=31, freq='D')
    frame = _blank(times)
    values = np.exp(np.linspace(2, 3, 31)); values[-1] = 100000
    frame['ssc_mg_l'] = values; frame['pct_fines'] = 50.; frame['discharge_m3s'] = 500.
    frame.loc[times[1], 'pct_fines'] = 130
    frame.loc[times[2], 'censored_fields'] = 'ssc_mg_l'
    review = review_observations(frame, method='mad')
    assert review.flags.ssc_mg_l.iloc[-1] and review.flags.ssc_mg_l.iloc[2]
    assert review.flags.pct_fines.iloc[1]
    assert frame.ssc_mg_l.iloc[-1] == 100000
    constant = frame.copy(); constant['ssc_mg_l'] = 10
    review = review_observations(constant, method='mad')
    assert any('MAD is zero' in note for note in review.notes)


def test_exclusions_block_derived_loads_and_concentration_fallback_resurrection():
    frame = _blank(pd.date_range('2004-01-01', periods=3, freq='D'))
    frame['kind']='sample';frame['ssc_mg_l']=[100,200,300];frame['discharge_m3s']=1000.
    frame['ssl_kg_s']=[100,200,300];frame['sand_mg_l']=[50,100,150];frame['fines_mg_l']=[50,100,150]
    frame['qualifier']='ssl=derived(SSCxQ) fractions=derived'
    original=ObservationSet('test','Measurements',frame)
    masked=apply_exclusions(original,{'ssc_mg_l':[True,False,False], 'discharge_m3s':[False,True,False]})
    assert masked.df.ssl_kg_s.iloc[:2].isna().all()
    assert masked.df.sand_mg_l.iloc[0]!=masked.df.sand_mg_l.iloc[0]
    assert len(observed_series(masked.df,'Flux','total',['sample'])[0])==1
    assert np.isnan(sediment_records(masked.df,'Conc','total',['sample']).obs.iloc[0])
    assert original.df.ssc_mg_l.iloc[0]==100
    # A load explicitly rejected by the reviewer must not be rebuilt from retained SSC/Q.
    masked=apply_exclusions(original,{'ssl_kg_s':[True,False,False]})
    assert np.isnan(sediment_records(masked.df,'Flux','total',['sample']).obs.iloc[0])


def test_flow_conditioned_review_retains_real_high_flow_sediment_and_flags_residual():
    q=np.geomspace(10,10000,50);y=2*q**.8*np.exp(.1*np.sin(np.arange(50)))
    y[20]*=100
    frame=pd.DataFrame({'discharge_m3s':q,'ssc_mg_l':y},index=pd.date_range('2004-01-01',periods=50))
    review=review_observations(frame,method='rating_residual',threshold=6)
    assert review.flags.ssc_mg_l.iloc[20]
    assert not review.flags.ssc_mg_l.iloc[-1]


def test_signed_reverse_transport_is_distinct_from_negative_load_at_forward_flow():
    frame=pd.DataFrame({'discharge_m3s':[100.,-100.,np.nan], 'ssl_kg_s':[-10.,-10.,-10.]})
    review=review_observations(frame, variable='ssl_kg_s', method='none')
    assert review.flags.ssl_kg_s.tolist()==[True,False,False]
