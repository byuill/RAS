import numpy as np
import pandas as pd
import pytest
from analysis.calibration_metrics import interpolate_model_to_times, cumulative_load, periodic_loads
from sediment.aggregation import aggregate
from sediment.grain_classes import SedimentGroup
from sediment.rouse import RouseConfig
from observations.local_import import detect_mapping
from core.exceptions import UnitError
from core.cache import BoundedCache


@pytest.mark.parametrize('mode',['interpolate','nearest'])
def test_pairing_does_not_extrapolate_or_skip_missing_values(mode):
    times=pd.date_range('2004-01-01',periods=3,freq='h')
    model=pd.Series([1,np.nan,3],index=times)
    target=times[[0,1,2]].append(pd.DatetimeIndex([times[0]-pd.Timedelta(minutes=1),
        times[-1]+pd.Timedelta(minutes=1),times[0]+pd.Timedelta(minutes=30)]))
    result=interpolate_model_to_times(model,target,mode=mode)
    assert result.iloc[0]==1 and result.iloc[2]==3
    assert result.iloc[1:2].isna().all() and result.iloc[3:5].isna().all()
    if mode=='interpolate':assert np.isnan(result.iloc[-1])


def test_pairing_gap_duplicates_and_offset():
    times=pd.to_datetime(['2004-01-01','2004-01-03'])
    model=pd.Series([0,2],index=times)
    sample=pd.DatetimeIndex(['2004-01-02 06:00'])
    assert np.isnan(interpolate_model_to_times(model,sample,max_gap_hours=36).iloc[0])
    assert interpolate_model_to_times(model,sample,max_gap_hours=48,time_offset_hours=-6).iloc[0]==1
    with pytest.raises(ValueError,match='unique'):interpolate_model_to_times(pd.Series([1,2],index=[times[0]]*2),sample)


@pytest.mark.parametrize('by,dates,years',[
    ('calendar',['2003-12-31 12:00','2004-01-01 12:00'],[2003,2004]),
    ('water',['2004-09-30 12:00','2004-10-01 12:00'],[2004,2005])])
def test_load_intervals_split_at_year_boundary(by,dates,years):
    index=pd.to_datetime(dates)
    flux=pd.Series([0,2.0],index=index);dt=pd.Series([np.nan,1.0],index=index)
    loads=periodic_loads(flux,dt,by=by)
    assert list(loads.index)==years
    np.testing.assert_allclose(loads.load_kg,[86400,86400])
    assert loads.n_missing.sum()==0
    cumulative,missing=cumulative_load(flux,dt)
    assert cumulative.iloc[-1]==loads.load_kg.sum() and missing==0


def test_missing_loads_are_counted_and_never_reported_as_zero_year():
    index=pd.date_range('2004-01-01',periods=3,freq='D')
    flux=pd.Series([1,np.nan,np.nan],index=index);dt=pd.Series([np.nan,1,1],index=index)
    loads=periodic_loads(flux,dt)
    assert loads.n_missing.iloc[0]==2 and np.isnan(loads.load_kg.iloc[0])
    assert cumulative_load(flux,dt)[1]==2


def test_rouse_partition_invalid_missing_and_infinite():
    cfg=RouseConfig();group=SedimentGroup('bedload_est','Bed',(),'',kind='rouse')
    values=np.array([[3,4],[3,np.nan],[-3,4],[3,4]])
    rouse=np.array([[np.inf,.5],[3,3],[np.nan,.5],[-1,.5]])
    result=aggregate(values,[1,2],group,rouse,cfg)
    assert result[0]==3 and np.isnan(result[1:]).all()
    with pytest.raises(ValueError):RouseConfig(kappa=0)
    with pytest.raises(ValueError):RouseConfig(susp_max=3,bed_min=2)


def test_declared_import_units_are_checked():
    mapping=detect_mapping(pd.DataFrame(columns=['Date','Discharge (m\u00b3/s)','SSC (mg/L)']))
    assert mapping['discharge'].unit=='m3/s'
    with pytest.raises(UnitError):detect_mapping(pd.DataFrame(columns=['Date','Q (miles/hour)']))


def test_derived_cache_evicts_and_refuses_oversized_entry():
    cache=BoundedCache(.0001)
    a=np.arange(10,dtype=float);cache.put('a',a);cache.put('b',a.copy())
    assert cache.get('a') is None and cache.get('b') is not None
    cache.put('large',np.arange(10000,dtype=float))
    assert cache.get('large') is None and cache.bytes<=cache.limit


def test_pin_is_a_snapshot_even_if_source_data_changes():
    from plotting.styles import PinManager,SeriesData
    x=np.arange(3,dtype=float);y=x.copy();meta={'notes':['original']}
    pin=PinManager().pin('Run A','rating',[SeriesData(x,y,'discharge','mass_flux','curve')],meta)
    x[:]=99;y[:]=100;meta['notes'].append('changed')
    np.testing.assert_array_equal(pin.series[0].x,[0,1,2])
    np.testing.assert_array_equal(pin.series[0].y,[0,1,2])
    assert pin.meta['notes']==['original'] and not pin.series[0].y.flags.writeable


def test_contribution_plot_handles_all_reverse_flow():
    from matplotlib.figure import Figure
    from plotting.timeseries import draw_stacked_contribution
    from plotting.styles import DisplayUnits
    from config.settings import AppSettings
    frame=pd.DataFrame({'Silt':[-1,-2]},index=pd.date_range('2004-01-01',periods=2))
    result=draw_stacked_contribution(Figure(),frame,DisplayUnits(AppSettings()),False,'Test','Test')
    assert any('No positive' in note for note in result.notes)
