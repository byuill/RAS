"""Main application window."""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("RAS Sediment Calibration Workbench")
        self.resize(1024, 768)
        
        self.workers = WorkerManager()
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
        self.lbl_file.setText(f"Loaded: {path}")
        self.settings.last_hdf_path = path
        self.settings.save()
        self.status.showMessage(f"Loading {path}...")
        
        try:
            res = open_results(path)
            self.mds = ModelDataService(res)
            
            # populate combo_xs
            self.combo_xs.blockSignals(True)
            self.combo_xs.clear()
            for i, xs in enumerate(self.mds.res.info.xs):
                self.combo_xs.addItem(f"{xs.river} | {xs.reach} | {xs.station} ({xs.label})", i)
            self.combo_xs.blockSignals(False)
            
            self.status.showMessage(f"Loaded {path}")
            if self.combo_xs.count() > 0:
                self.combo_xs.setCurrentIndex(0)
                self.tab_obs.set_model(self.mds, self.combo_xs.currentData())
                self._update_plots()
        except Exception as e:
            logger.exception("Failed to load file")
            self.status.showMessage(f"Error loading {path}: {e}")

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
        self.tab_obs.set_current_xs(xs_index)
        self.tab_ts.refresh(self.mds, self.display_units, self.pins, xs_index)
        self.tab_rc.refresh(self.mds, self.display_units, self.pins, xs_index)
        self.tab_cal.refresh(self.mds, self.display_units, xs_index)
        self.tab_diag.refresh(self.mds, xs_index)
