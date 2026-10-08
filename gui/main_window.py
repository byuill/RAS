"""Main application window."""
from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QTabWidget, QPushButton, QFileDialog,
                               QStatusBar)
                               
from gui.time_series_tab import TimeSeriesTab
from gui.rating_curve_tab import RatingCurveTab
from gui.observations_tab import ObservationsTab
from gui.calibration_tab import CalibrationTab
from gui.diagnostics_tab import DiagnosticsTab
from gui.workers import WorkerManager
from gui.controls import SearchableComboBox

from ras.hdf_reader import open_results
from analysis.model_data import ModelDataService
from plotting.styles import DisplayUnits, PinManager
from sediment.rouse import RouseConfig

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("RAS Sediment Calibration Workbench")
        self.resize(1024, 768)
        
        self.workers = WorkerManager(self)
        self._closing = False
        self.mds = None
        self.display_units = DisplayUnits(settings)
        self.pins = PinManager()
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # Top bar
        top_bar = QHBoxLayout()
        self.btn_open = QPushButton("Open HEC-RAS HDF")
        self.btn_open.clicked.connect(self._open_hdf)
        self.lbl_file = QLabel("No file loaded")
        
        self.combo_xs = SearchableComboBox()
        self.combo_xs.setPlaceholderText("Select Cross Section...")
        self.combo_xs.setMinimumWidth(250)
        self.combo_xs.currentIndexChanged.connect(self._on_xs_changed)
        
        top_bar.addWidget(self.btn_open)
        top_bar.addWidget(self.lbl_file)
        top_bar.addStretch()
        top_bar.addWidget(QLabel("Cross Section:"))
        top_bar.addWidget(self.combo_xs)
        main_layout.addLayout(top_bar)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tab_ts = TimeSeriesTab()
        self.tab_rc = RatingCurveTab()
        self.tab_obs = ObservationsTab(self.workers, settings)
        self.tab_cal = CalibrationTab(settings)
        self.tab_obs.obs_changed.connect(self.tab_cal.set_observations)
        self.tab_obs.xs_requested.connect(self._select_xs_by_index)
        self.tab_diag = DiagnosticsTab()
        
        self.tabs.addTab(self.tab_ts, "Time Series")
        self.tabs.addTab(self.tab_rc, "Rating Curve")
        self.tabs.addTab(self.tab_cal, "Calibration")
        self.tabs.addTab(self.tab_obs, "Observations")
        self.tabs.addTab(self.tab_diag, "Diagnostics")
        
        main_layout.addWidget(self.tabs)
        
        # Status Bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")
        
        # Initial load from settings if any
        if self.settings.last_hdf_path:
            self._load_file(self.settings.last_hdf_path)
            
    def _open_hdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open HEC-RAS HDF", self.settings.default_model_dir, "HEC-RAS Results (*.hdf);;All Files (*)"
        )
        if path:
            self._load_file(path)
            
    def _load_file(self, path):
        if self._closing:
            return
        self.workers.invalidate('plot_data')
        self._set_busy(True)
        self.status.showMessage(f"Loading {path}...")
        settings = self.settings
        def load():
            res = open_results(path,cache_mb=settings.hdf_cache_mb)
            try:
                cfg = RouseConfig(kappa=settings.rouse_kappa,bed_min=settings.rouse_bed_min,
                                  susp_max=settings.rouse_susp_max,source=settings.rouse_source)
                mds = ModelDataService(res,sand_min_mm=settings.sand_min_diameter_mm,
                                       negative_policy=settings.negative_value_policy,
                                       drop_initial_step=settings.drop_initial_step_sediment,
                                       cache_mb=settings.analysis_cache_mb,rouse_cfg=cfg,analysis_settings=settings)
                mds.frame(0,'total',cfg)
                return mds
            except Exception:
                res.close()
                raise
        self.workers.submit('hdf',load,self._file_loaded,self._load_failed,on_discard=lambda mds:mds.close())

    def _set_busy(self,busy):
        self.btn_open.setEnabled(not busy)
        self.combo_xs.setEnabled(not busy)
        self.tabs.setEnabled(not busy)

    def _file_loaded(self,mds):
        if self.mds is not None:
            self.mds.close()
        self.mds = mds
        path = str(mds.res.path)
        self.lbl_file.setText(f'Loaded: {Path(path).name}')
        self.lbl_file.setToolTip(path)
        self.settings.last_hdf_path = path
        self.settings.default_model_dir = str(Path(path).parent)
        try:
            self.settings.save()
        except OSError as exc:
            logger.warning('Could not save settings: %s',exc)
        self.combo_xs.blockSignals(True)
        self.combo_xs.clear()
        for xs in mds.res.info.xs:
            self.combo_xs.addItem(xs.label,xs.index)
        self.combo_xs.setCurrentIndex(0)
        self.combo_xs.blockSignals(False)
        self.tab_obs.set_model(mds,0)
        self._set_busy(False)
        self._render_plots()
        self.status.showMessage(f'Loaded {path}. Review Diagnostics for warnings and provenance.')

    def _load_failed(self,exc):
        self._set_busy(False)
        self.status.showMessage(f'Could not load results: {exc}. The previous model is retained.')

    def _on_xs_changed(self):
        self._update_plots()

    def _select_xs_by_index(self, xs_index: int):
        i = self.combo_xs.findData(xs_index)
        if i >= 0:
            self.combo_xs.setCurrentIndex(i)

    def _update_plots(self):
        if not self.mds or self.combo_xs.currentIndex() < 0:
            return
            
        xs_index = self.combo_xs.currentData()
        mds = self.mds
        self._set_busy(True)
        self.status.showMessage(f'Reading cross section {mds.res.info.xs[xs_index].label}...')
        groups = {'total',self.tab_ts.combo_group.currentData(),self.tab_rc.combo_group.currentData(),
                  self.tab_cal.combo_group.currentData()}
        def prepare():
            for group in groups - {None}:
                mds.frame(xs_index,group,mds.rouse_cfg)
        self.workers.submit('plot_data',prepare,lambda _:self._plots_ready(),self._plot_failed)

    def _plot_failed(self,exc):
        self._set_busy(False)
        message = f'Cannot read this cross section: {exc}'
        self.status.showMessage(message)
        self.tab_ts._show_error(message)
        self.tab_rc._show_error(message)
        self.tab_cal._show_message(message)

    def _plots_ready(self):
        self._set_busy(False)
        self._render_plots()
        self.status.showMessage('Ready. Review Diagnostics for warnings and provenance.')

    def _render_plots(self):
        xs_index = self.combo_xs.currentData()
        self.tab_obs.set_current_xs(xs_index)
        self.tab_ts.refresh(self.mds, self.display_units, self.pins, xs_index)
        self.tab_rc.refresh(self.mds, self.display_units, self.pins, xs_index)
        self.tab_cal.refresh(self.mds, self.display_units, xs_index)
        self.tab_diag.refresh(self.mds, xs_index)

    def closeEvent(self,event):
        self._closing = True
        self.workers.invalidate('hdf')
        self.workers.invalidate('plot_data')
        self.workers.invalidate('obs')
        self.workers.invalidate('obs_all')
        if not self.workers.idle():
            event.ignore()
            self.status.showMessage('Waiting for current data requests to finish before closing...')
            QTimer.singleShot(100,self.close)
            return
        if self.mds is not None:
            self.mds.close()
        event.accept()
