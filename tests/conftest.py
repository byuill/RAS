"""Small generated HDF fixtures; no model results are distributed with tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import h5py
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def make_hdf(tmp_path):
    def make(name='model.p01.hdf', n_xs=2, class_only=False, projection=None):
        path=tmp_path/name
        times=pd.date_range('2004-01-01',periods=5,freq='12h')
        with h5py.File(path,'w') as h5:
            h5.attrs['File Version']=np.array([b'7.0.1'])
            h5.attrs['Units System']='English'
            if projection:h5.attrs['Projection']=projection
            plan=h5.create_group('Plan Data/Plan Information')
            plan.attrs['Simulation Start Time']=np.array([b'01JAN2004 00:00:00'])
            plan.attrs['Plan Name']='Synthetic validation'
            parent=h5.create_group('Results/Sediment/Output Blocks/Sediment/Sediment Time Series')
            parent.create_dataset('Time',data=np.arange(5)/2)
            parent.create_dataset('Time Date Stamp',data=np.array([t.strftime('%d%b%Y %H:%M:%S').upper().encode() for t in times]))
            group=parent.create_group('Cross Sections')
            def result(name,data,units,grain='All'):
                ds=group.create_dataset(name,data=np.broadcast_to(np.asarray(data,float)[:,None],(5,n_xs)),compression='gzip')
                ds.attrs['Units']=units;ds.attrs['Grain Class']=grain
            result('Flow',[1000]*5,'cfs')
            result('Water Surface',[10,11,12,13,14],'ft')
            result('Velocity',[2]*5,'ft/s')
            result('Shear Stress',[.1]*5,'lb/ft2')
            result('Temperature',[68]*5,'degF')
            for k,concentration in enumerate([100,200,300],1):
                result(f'Sediment Concentration {k}',[concentration]*5,'mg/L',str(k))
                result(f'Rouse # {k}',[.5 if k==1 else 2 if k==2 else 3]*5,'1',str(k))
            if not class_only:result('Sediment Concentration',[600]*5,'mg/L')
            result('Sediment Discharge',[600*1000*0.028316846592/1000*86400/907.18474]*5,'tons/day')
            attributes=np.array([(b'River',b'Reach',str(100-i).encode(),b'XS') for i in range(n_xs)],
                dtype=[('River','S16'),('Reach','S16'),('Station','S16'),('Name','S16')])
            h5.create_dataset('Results/Sediment/Geometry Info/Cross Section Attributes',data=attributes)
            grains=h5.create_group('Sediment/Grain Class Data')
            grains.create_dataset('Grain Class Names',data=np.array([b'Fine silt',b'Medium sand',b'Gravel']))
            d=np.array([.032,.25,4.0])
            grains.create_dataset('Grain Class Bounds',data=np.column_stack([d/2,d,d*2]))
            grains.create_dataset('Density Data',data=np.array([[2.65,.4,165.36]]*3))
        return path
    return make


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app
