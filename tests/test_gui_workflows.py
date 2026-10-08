import threading
import time
from pathlib import Path
from PySide6.QtCore import QThread
from config.settings import AppSettings
from gui.main_window import MainWindow
from gui.workers import WorkerManager


def wait(qapp,condition,seconds=15):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:
        qapp.processEvents();time.sleep(.005)
    qapp.processEvents()
    assert condition(),'GUI operation did not finish'


def test_worker_callbacks_are_on_gui_thread_and_stale_results_disposed(qapp):
    manager=WorkerManager();started=threading.Event();release=threading.Event();discard=[];results=[]
    def slow():started.set();release.wait(5);return 'old'
    def accepted(result):
        assert QThread.currentThread()==qapp.thread()
        results.append(result)
    manager.submit('load',slow,accepted,lambda error:results.append(error),on_discard=discard.append)
    assert started.wait(2)
    manager.submit('load',lambda:'new',accepted,lambda error:results.append(error))
    release.set();wait(qapp,manager.idle)
    assert results==['new'] and discard==['old']


def test_gui_opens_replaces_recovers_and_closes_results(make_hdf,tmp_path,qapp,monkeypatch):
    settings=AppSettings(last_hdf_path='',observation_cache_dir=str(tmp_path/'cache'),
        negative_value_policy='zero',drop_initial_step_sediment=False,rouse_source='computed',
        rouse_kappa=.3,sand_min_diameter_mm=.1,hdf_cache_mb=.01,analysis_cache_mb=.1,
        hysteresis_window_days=1,hysteresis_rise_threshold_cfs=2,hysteresis_min_q_cfs=10)
    saved=[];monkeypatch.setattr(settings,'save',lambda:saved.append(settings.last_hdf_path))
    window=MainWindow(settings)
    path=make_hdf();window._load_file(str(path))
    assert not window.btn_open.isEnabled()
    wait(qapp,lambda:window.mds is not None and window.workers.idle())
    original=window.mds
    assert original.negative_policy=='zero' and not original.drop_initial_step
    assert original.rouse_cfg.source=='computed' and original.rouse_cfg.kappa==.3
    assert saved==[str(path)]
    assert window.tab_ts._last_req is not None
    assert 'tons/day' in window.tab_ts.canvas.figure.axes[0].get_ylabel()
    assert 'cfs' in window.tab_ts.canvas.figure.axes[1].get_ylabel()
    assert 'DERIVED' in window.tab_diag.txt.toPlainText()
    import analysis.hysteresis
    original_limbs=analysis.hysteresis.classify_limbs;options=[]
    def limbs(q,**kwargs):options.append(kwargs);return original_limbs(q,**kwargs)
    monkeypatch.setattr(analysis.hysteresis,'classify_limbs',limbs)
    window.tab_rc.combo_color.setCurrentText('limb')
    assert options[-1]=={'window_days':1,'rise_thresh_cfs':2,'min_q_cfs':10}
    for view in ['Cumulative Load','Annual/Water-Year Loads','Class Contribution Stacked','Series']:
        window.tab_ts.combo_view.setCurrentText(view)
        assert window.tab_ts.canvas.figure.axes
    window.tab_ts._pin_current()
    assert len(window.pins.items('timeseries'))==1
    # Pair local observations and exercise displayed statistics and exported canonical frames.
    import pandas as pd
    from observations.processing import ObservationSet,_blank
    from export.csv_export import export_model_frame
    frame=original.frame(0,'total',original.rouse_cfg)
    data=_blank(frame.df.index)
    data['kind']='sample';data['ssc_mg_l']=frame.df.Conc.values
    data['discharge_m3s']=frame.df.Q.values
    obs=ObservationSet('test','Synthetic observations',data)
    window.tab_cal.set_observations(obs)
    window.tab_cal.combo_var.setCurrentText('Sediment Concentration')
    assert len(window.tab_cal._paired)==5 and window.tab_cal.btn_export.isEnabled()
    export_model_frame(frame,tmp_path/'model.csv',window.display_units)
    assert pd.read_csv(tmp_path/'model.csv').shape[0]==5
    assert (tmp_path/'model.meta.json').exists()
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(tmp_path/'gui-model.csv'),'CSV'))
    window.tab_ts.btn_export.click()
    exported=pd.read_csv(tmp_path/'gui-model.csv')
    assert len(exported)==5 and 'dt_days' in exported.columns
    window.combo_xs.setCurrentIndex(1);wait(qapp,window.workers.idle)
    assert window.tab_ts._xs_index==1
    window._load_file(str(tmp_path/'missing.hdf'));wait(qapp,window.workers.idle)
    assert window.mds is original and window.btn_open.isEnabled()
    assert saved==[str(path)]
    second=make_hdf('second.p02.hdf');window._load_file(str(second));wait(qapp,window.workers.idle)
    assert window.mds is not original and not original.res._h5.id.valid
    current=window.mds
    window.close();qapp.processEvents()
    assert not current.res._h5.id.valid


def test_close_during_pending_open_disposes_result(make_hdf,tmp_path,qapp,monkeypatch):
    import gui.main_window
    settings=AppSettings(last_hdf_path='',observation_cache_dir=str(tmp_path/'cache'))
    monkeypatch.setattr(settings,'save',lambda:None)
    gate=threading.Event();started=threading.Event();opened=[]
    real_open=gui.main_window.open_results
    def delayed(*args,**kwargs):
        result=real_open(*args,**kwargs);opened.append(result);started.set();gate.wait(5);return result
    monkeypatch.setattr(gui.main_window,'open_results',delayed)
    window=MainWindow(settings);window.show();window._load_file(str(make_hdf()))
    assert started.wait(2)
    window.close();gate.set()
    wait(qapp,lambda:window.workers.idle() and not window.isVisible())
    assert window.mds is None and not opened[0]._h5.id.valid
