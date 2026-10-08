import json

import numpy as np
import pandas as pd
import pytest

from observations.processing import ObservationSet, _blank


def test_service_enrichment_requires_complete_branches_and_preserves_cache(tmp_path):
    from observations.cache import ObservationCache
    from observations.providers import ObservationProvider, FetchResult
    from observations.service import ObservationService
    from observations.station_catalog import Station, StationCatalog
    from observations.usgs import _empty_samples
    class FixtureProvider(ObservationProvider):
        name='fixtures'
        parameters={'usgs_wqp_samples':'samples','usgs_dv_discharge':'flow'}
        def __init__(self):self.calls=[]
        def fetch(self,station,parameter,start,end):
            self.calls.append((station.id,parameter))
            if parameter=='usgs_wqp_samples':
                times=pd.date_range('2004-01-01 12:00',periods=3,freq='D')
                frame=pd.DataFrame({column:[np.nan]*3 for column in _empty_samples().columns})
                frame['DateTime']=times;frame['sample_id']=['1','2','3'];frame['ssc_mg_l']=100.
                frame['discharge_cfs']=[999.,np.nan,np.nan];frame['qualifier']='';frame['time_is_date_only']=False
                return FetchResult(frame,{})
            days=pd.date_range(start,end,freq='D')
            if station.id=='USGS-07290000':days=days[days<=pd.Timestamp('2004-01-02')]
            frame=pd.DataFrame({'DateTime':days,'value':1000. if station.id=='USGS-07289000' else 100.,'qualifier':'','agency':'USGS'})
            return FetchResult(frame,{'value':'cfs'})
    stations=[Station('USGS-07290880','Natchez','Natchez','USGS',parameters={'usgs_wqp_samples':[]})]
    stations += [Station(x,x,x,'USGS',parameters={'usgs_dv_discharge':[]}) for x in ('USGS-07289000','USGS-07290000')]
    provider=FixtureProvider();cache=ObservationCache(tmp_path)
    service=ObservationService(StationCatalog(stations),cache,[provider])
    obs,_=service.load(stations[0],'2004-01-01','2004-01-03')
    from sediment.units import M3_PER_CFS
    np.testing.assert_allclose(obs.df.discharge_m3s,[999*M3_PER_CFS,1100*M3_PER_CFS,np.nan],equal_nan=True)
    raw=cache.lookup('fixtures',stations[0].id,'usgs_wqp_samples','2004-01-01','2004-01-03').df
    assert raw.discharge_cfs.iloc[1:].isna().all()
    calls=len(provider.calls)
    again,_=service.load(stations[0],'2004-01-01','2004-01-03')
    assert len(provider.calls)==calls and again.df.q_is_proxy.iloc[1]


def test_gui_qaqc_low_q_filter_manual_curve_and_audit(make_hdf,tmp_path,qapp,monkeypatch):
    from config.settings import AppSettings
    from gui.main_window import MainWindow
    from tests.test_gui_workflows import wait
    from PySide6.QtWidgets import QFileDialog
    from matplotlib.backend_bases import MouseEvent
    from sediment.units import convert
    settings=AppSettings(last_hdf_path='',observation_cache_dir=str(tmp_path/'cache'),drop_initial_step_sediment=False)
    monkeypatch.setattr(settings,'save',lambda:None)
    window=MainWindow(settings);window.resize(1440,1000);window.show()
    window._load_file(str(make_hdf()));wait(qapp,lambda:window.mds is not None and window.workers.idle())
    data=_blank(window.mds.res.info.times)
    data['kind']='sample';data['discharge_m3s']=convert(np.array([100000,250000,400000,600000,800000]),'cfs','m3/s')
    data['ssc_mg_l']=[100.,-20.,200.,300.,400.]
    data['ssl_kg_s']=data.ssc_mg_l*data.discharge_m3s/1000
    data['qualifier']='ssl=derived(SSCxQ)'
    observations=window.tab_obs;tab=window.tab_ts_cal
    observations._set_obs(ObservationSet('local','Imported samples',data))
    assert observations._qaqc_review.flags.ssc_mg_l.sum()==1
    observations.btn_exclude_flags.click()
    assert np.isnan(observations.observations.df.ssc_mg_l.iloc[1])
    assert np.isnan(observations.observations.df.ssl_kg_s.iloc[1])
    assert len(tab._paired)==4 and tab._context['observation_qaqc']['excluded_records']==1
    audit=tmp_path/'qaqc.csv'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(audit),'CSV'))
    observations.btn_audit.click()
    exported=pd.read_csv(audit)
    assert exported.ssc_mg_l.iloc[1]==-20 and np.isnan(exported.used_ssc_mg_l.iloc[1])
    assert (tmp_path/'qaqc.meta.json').exists()
    observations.btn_restore.click()
    assert len(tab._paired)==5 and observations.observations.df.ssc_mg_l.iloc[1]==-20
    assert tab.spin_low_q.value()==300000 and not tab.btn_low_q.isChecked()
    tab.btn_low_q.click()
    assert len(tab._paired)==3 and tab._context['low_flow_filter_enabled']
    assert data.ssc_mg_l.iloc[1]==-20  # filtering does not edit raw observations
    tab.btn_low_q.click();assert len(tab._paired)==5
    window.tabs.setCurrentWidget(tab);qapp.processEvents()
    tab.combo_function.setCurrentIndex(tab.combo_function.findData('linear'))
    tab.btn_draw.click();assert tab.combo_fit_source.currentData()=='manual'
    # The click callback is connected to the actual Matplotlib event system.
    for q,y in [(250000.,150.),(600000.,350.),(400000.,240.)]:
        axis=tab.canvas.figure.axes[2]
        xpix,ypix=axis.transData.transform((q,y))
        event=MouseEvent('button_press_event',tab.canvas.canvas,xpix,ypix,button=1)
        tab.canvas.canvas.callbacks.process('button_press_event',event)
    assert len(tab._manual_points)==3 and tab._result.fit.n_used==3
    assert tab._context['rating_fit_source']=='manual' and len(tab._paired)==5
    assert 'MANUAL CONTROL-POINT' in tab.lbl_fit.text()
    tab.btn_undo_point.click();assert len(tab._manual_points)==2 and tab._result.fit is not None
    saved=tmp_path/'manual.csv'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(saved),'CSV'))
    tab.btn_export.click()
    context=json.loads((tmp_path/'manual.meta.json').read_text())
    assert context['rating_fit_source']=='manual' and len(context['manual_points_canonical'])==2
    tab.btn_clear_points.click();assert not tab._manual_points and tab._result.fit is None
    assert len(tab._paired)==5
    tab.combo_var.setCurrentText('Sediment Flux')
    assert tab.combo_fit_source.currentData()=='observed' and not tab.btn_draw.isChecked()
    window.close();qapp.processEvents()
