import h5py
import numpy as np
import pandas as pd
import pytest
from ras.hdf_reader import open_results, parse_time_stamps
from analysis.model_data import ModelDataService
from sediment.rouse import RouseConfig
from core.exceptions import HdfStructureError, UnitError
from tools.hdf_metadata import metadata_report

GROUP='Results/Sediment/Output Blocks/Sediment/Sediment Time Series/Cross Sections'


def test_us_customary_analysis_and_grain_groups(make_hdf):
    with open_results(make_hdf()) as res:
        service=ModelDataService(res,drop_initial_step=False)
        cfg=RouseConfig()
        frame=service.frame(1,'total',cfg)
        np.testing.assert_allclose(frame.df.Q,1000*.028316846592)
        np.testing.assert_allclose(frame.df.Conc,600)
        np.testing.assert_allclose(frame.df.Flux,600*1000*.028316846592/1000)
        assert frame.meta['integrity']['sum_classes_vs_reported_max_abs_rel']<1e-12
        np.testing.assert_allclose(service.frame(0,'sand',cfg).df.Conc,200)
        np.testing.assert_allclose(service.frame(0,'fines',cfg).df.Conc,100)
        np.testing.assert_allclose(service.frame(0,'coarse',cfg).df.Conc,300)
        np.testing.assert_allclose(service.frame(0,'suspended_est',cfg).df.Conc,300)
        np.testing.assert_allclose(service.frame(0,'bedload_est',cfg).df.Conc,300)


def test_class_only_datasets_are_recognized(make_hdf):
    with open_results(make_hdf(class_only=True)) as res:
        assert res.info.has_class_variable('Sediment Concentration')
        assert res.info.layout.variables['Sediment Concentration'].total_path is None
        frame=ModelDataService(res).frame(0,'total',RouseConfig())
        np.testing.assert_allclose(frame.df.Conc,600)


def test_large_sparse_matrix_uses_column_selection_and_bounded_cache(make_hdf,monkeypatch):
    path=make_hdf(n_xs=1)
    with h5py.File(path,'a') as h5:
        # Logical result size = 2 GB; sparse fill creates a tiny physical test file.
        for key in list(h5[GROUP]):del h5[GROUP][key]
        ds=h5[GROUP].create_dataset('Flow',shape=(5000,50000),dtype='f8',chunks=(100,100),fillvalue=123.4567890123)
        ds.attrs['Units']='cfs'
        parent=h5[GROUP].parent
        del parent['Time'];del parent['Time Date Stamp']
        parent.create_dataset('Time',data=np.arange(5000)/24)
        del h5['Results/Sediment/Geometry Info/Cross Section Attributes']
    original=h5py.Dataset.__getitem__
    reads=[]
    def guarded(ds,key):
        if ds.name.endswith('/Flow'):
            assert key is not Ellipsis,'Full large-matrix read attempted'
            reads.append(key)
        return original(ds,key)
    monkeypatch.setattr(h5py.Dataset,'__getitem__',guarded)
    with open_results(path,cache_mb=.05) as res:
        for xs in range(4):
            np.testing.assert_allclose(res.var_column('Flow',xs),123.4567890123,rtol=0,atol=1e-12)
            assert res.cache_info()['bytes']<=res.cache_info()['limit_bytes']
        assert all(key==(slice(None),i) for i,key in enumerate(reads))
        res.prefetch(['Flow'])
        assert len(reads)==4
        with pytest.raises(HdfStructureError,match='exceeds'):res.matrix(res.variable_path('Flow'))
    assert path.stat().st_size < 1_000_000


def test_full_matrix_precision_and_closed_reader(make_hdf):
    path=make_hdf()
    precise=123456789.01234567
    with h5py.File(path,'a') as h5:h5[f'{GROUP}/Flow'][...]=precise
    res=open_results(path)
    matrix=res.matrix(res.variable_path('Flow'))
    assert matrix.dtype==np.float64 and matrix[0,0]==precise
    assert not matrix.flags.writeable
    res.close()
    with pytest.raises(HdfStructureError,match='closed'):res.var_column('Flow',0)


@pytest.mark.parametrize('fault',['duplicate_time','stamp_length','xs_count','field_shape','grain_bounds'])
def test_invalid_layout_fails_clearly(make_hdf,fault):
    path=make_hdf()
    with h5py.File(path,'a') as h5:
        parent=h5[GROUP].parent
        if fault=='duplicate_time':parent['Time'][2]=parent['Time'][1]
        if fault=='stamp_length':
            del parent['Time Date Stamp'];parent.create_dataset('Time Date Stamp',data=[b'01JAN2004 00:00:00'])
        if fault=='xs_count':
            data=h5['Results/Sediment/Geometry Info/Cross Section Attributes'][...][:1]
            del h5['Results/Sediment/Geometry Info/Cross Section Attributes']
            h5.create_dataset('Results/Sediment/Geometry Info/Cross Section Attributes',data=data)
        if fault=='field_shape':
            del h5[f'{GROUP}/Sediment Concentration 1']
            ds=h5[GROUP].create_dataset('Sediment Concentration 1',data=np.ones((4,2)))
            ds.attrs['Grain Class']='1';ds.attrs['Units']='mg/L'
        if fault=='grain_bounds':
            del h5['Sediment/Grain Class Data/Grain Class Bounds']
            h5.create_dataset('Sediment/Grain Class Data/Grain Class Bounds',data=np.ones((1,3)))
    with pytest.raises(HdfStructureError):
        with open_results(path) as res:ModelDataService(res).frame(0,'total',RouseConfig())


def test_midnight_rollover_and_fractional_timestep(make_hdf):
    dates=parse_time_stamps(np.array([b'31DEC2003 24:00:00',b'01JAN2004 12:00:00']))
    assert dates[0]==pd.Timestamp('2004-01-01')
    with open_results(make_hdf()) as res:
        res.info.times=pd.DatetimeIndex(['2004-01-01','2004-01-01 00:00:00.500'])
        assert res.info.timestep_days()[0]==.5/86400


def test_signed_reversals_and_dimension_validation(make_hdf):
    path=make_hdf()
    with h5py.File(path,'a') as h5:
        h5[f'{GROUP}/Flow'][...]=-100000
        h5[f'{GROUP}/Velocity'][...]=-2
    with open_results(path) as res:
        frame=ModelDataService(res,negative_policy='zero').frame(0,'total',RouseConfig())
        assert (frame.df.Flux<0).all() and (frame.df.Velocity<0).all()
        np.testing.assert_allclose(frame.df.Conc,600)
    with h5py.File(path,'a') as h5:h5[f'{GROUP}/Flow'].attrs['Units']='ft'
    with open_results(path) as res:
        with pytest.raises(UnitError,match='expected discharge'):ModelDataService(res).hydraulics(0)


def test_partial_class_data_is_not_a_complete_load(make_hdf):
    path=make_hdf()
    with h5py.File(path,'a') as h5:h5[f'{GROUP}/Sediment Concentration 2'][2,0]=np.nan
    with open_results(path) as res:
        service=ModelDataService(res)
        frame=service.frame(0,'total',RouseConfig())
        assert np.isnan(frame.df.Conc.iloc[2]) and np.isnan(frame.df.Flux.iloc[2])
        assert frame.meta['integrity']['sum_classes_vs_reported_n']==4


def test_metadata_report_never_reads_dataset_values(make_hdf,monkeypatch):
    path=make_hdf()
    def forbidden(*args):raise AssertionError('Metadata inspection read an array')
    monkeypatch.setattr(h5py.Dataset,'__getitem__',forbidden)
    report=metadata_report(path)
    assert report['file_version']=='7.0.1' and report['units_system']=='English'
    assert any(ds['units']=='cfs' for ds in report['datasets'])
    assert metadata_report(path,limit=2)['truncated']


@pytest.mark.parametrize('with_projection',[False,True])
def test_gauge_coordinates_require_known_projection(make_hdf,with_projection):
    from ras.geo import DEFAULT_ALBERS_WKT,parse_albers_wkt
    projection=parse_albers_wkt(DEFAULT_ALBERS_WKT)
    x,y=projection.forward(-90,30)
    path=make_hdf(projection=DEFAULT_ALBERS_WKT if with_projection else None)
    with h5py.File(path,'a') as h5:
        attributes=h5['Results/Sediment/Geometry Info/Cross Section Attributes'][...]
        h5.create_dataset('Geometry/Cross Sections/Attributes',data=attributes)
        h5.create_dataset('Geometry/Cross Sections/Polyline Info',data=[[0,2],[2,0]])
        h5.create_dataset('Geometry/Cross Sections/Polyline Points',data=[[x-1,y],[x+1,y]])
    with open_results(path) as res:
        xs=res.info.xs[0]
        assert np.isclose(xs.x,x)
        if with_projection:
            assert np.isclose(xs.lon,-90) and np.isclose(xs.lat,30)
        else:
            assert np.isnan(xs.lon) and any('automatic gauge mapping is disabled' in w for w in res.info.warnings)
        assert np.isnan(res.info.xs[1].x)


def test_volume_out_fallback_and_irregular_interval_mass(make_hdf):
    path=make_hdf()
    with h5py.File(path,'a') as h5:
        for name in list(h5[GROUP]):
            if name.startswith('Sediment Concentration'):del h5[GROUP][name]
        for k in range(1,4):
            volume=np.array([0]+[k*.5*86400/(165.36*.45359237)]*4)
            ds=h5[GROUP].create_dataset(f'Vol Out {k}',data=np.broadcast_to(volume[:,None],(5,2)))
            ds.attrs['Units']='ft^3';ds.attrs['Grain Class']=str(k)
        h5[f'{GROUP}/Sediment Discharge'][...]=6*86400/907.18474
    with open_results(path) as res:
        frame=ModelDataService(res).frame(0,'total',RouseConfig())
        assert np.isnan(frame.df.Flux.iloc[0])
        np.testing.assert_allclose(frame.df.Flux.iloc[1:],6)
        np.testing.assert_allclose(frame.df.Conc.iloc[1:],6000/(1000*.028316846592))


def test_missing_units_infer_only_known_system(make_hdf):
    path=make_hdf()
    with h5py.File(path,'a') as h5:
        del h5[f'{GROUP}/Flow'].attrs['Units']
    with open_results(path) as res:
        hyd=ModelDataService(res).hydraulics(0)
        np.testing.assert_allclose(hyd.discharge,1000*.028316846592)
        assert any('has no Units attribute' in w for w in hyd.warnings)
    with h5py.File(path,'a') as h5:h5.attrs['Units System']='unknown'
    with open_results(path) as res:
        with pytest.raises(UnitError,match='unit system is unknown'):ModelDataService(res).hydraulics(0)
