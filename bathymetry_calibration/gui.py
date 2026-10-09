"""Standalone starter GUI. ArcPy and HDF work run outside the GUI thread."""
import copy
import json
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Signal, QRunnable, QThreadPool, QObject
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from .sources import arcpy_request, model_times
from .workflow import export_comparison, load_config, run_comparison


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(Exception)


class Worker(QRunnable):
    def __init__(self, func):
        super().__init__()
        self.func = func
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.func()
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(e)


class WorkerManager:
    def __init__(self, parent):
        self.pool = QThreadPool()

    def submit(self, name, func, success, error):
        worker = Worker(func)
        worker.signals.finished.connect(success)
        worker.signals.error.connect(error)
        self.pool.start(worker)

    def idle(self):
        return self.pool.activeThreadCount() == 0


import pandas as pd
import numpy as np

class DiagnosticPlotsWindow(QMainWindow):
    def __init__(self, result, provenance, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Diagnostic Plots")
        self.resize(1000, 1100)
        self.figure = Figure(figsize=(10, 12), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        self.setCentralWidget(central)
        
        axs = self.figure.subplots(5, 1, sharex=True)
        sections = result.sections.copy()
        
        m_to_ft = 3.280839895
        m3_to_cy = 1.307950619
        
        t1 = pd.to_datetime(provenance['model_before_time'])
        t2 = pd.to_datetime(provenance['model_after_time'])
        years = (t2 - t1).total_seconds() / (365.25 * 24 * 3600)
        if years <= 0:
            years = 1.0
        
        sections['RM'] = pd.to_numeric(sections['xs_id'], errors='coerce')
        sections = sections.dropna(subset=['RM']).sort_values('RM')
        rm = sections['RM']
        
        min_rm, max_rm = rm.min(), rm.max()
        bins = np.arange(np.floor(min_rm/10)*10, np.ceil(max_rm/10)*10 + 10, 10)
        sections['rm_bin'] = pd.cut(sections['RM'], bins=bins, right=False)
        
        if 'model_baseline_elev_m' in sections and 'model_target_elev_m' in sections:
            axs[0].plot(rm, sections['model_baseline_elev_m'] * m_to_ft, label='Baseline Bed Elev', color='blue')
            axs[0].plot(rm, sections['model_target_elev_m'] * m_to_ft, label='Target Bed Elev', color='orange', linestyle='--')
            axs[0].set_ylabel("Elevation (feet)")
            axs[0].set_title("Model Baseline vs Target Bed Elevation")
            axs[0].legend()
            
            sections['model_elev_change_ft_yr'] = ((sections['model_target_elev_m'] - sections['model_baseline_elev_m']) * m_to_ft) / years
            sections['obs_elev_change_ft_yr'] = ((sections['observed_target_elev_m'] - sections['observed_baseline_elev_m']) * m_to_ft) / years
            elev_binned = sections.groupby('rm_bin', observed=True)[['model_elev_change_ft_yr', 'obs_elev_change_ft_yr']].mean().reset_index()
            elev_binned['bin_center'] = elev_binned['rm_bin'].apply(lambda x: x.mid).astype(float)
            axs[4].plot(elev_binned['bin_center'], elev_binned['model_elev_change_ft_yr'], label='Model', color='blue', marker='o')
            axs[4].plot(elev_binned['bin_center'], elev_binned['obs_elev_change_ft_yr'], label='Observed', color='orange', marker='s', linestyle='--')
            axs[4].set_ylabel("Elev Change (ft/yr)")
            axs[4].set_title(f"Average Bed Elevation Change per Year ({years:.1f} years)")
            axs[4].axhline(0, color='black', linewidth=0.8)
            axs[4].set_xlabel("River Mile")
            axs[4].legend()
        else:
            axs[4].set_xlabel("River Mile")
            
        binned = sections.groupby('rm_bin', observed=True).agg({
            'model_local_control_volume_m3': 'sum',
            'observed_local_control_volume_m3': 'sum',
            'effective_width_m': 'mean'
        }).reset_index()
        
        binned['bin_center'] = binned['rm_bin'].apply(lambda x: x.mid).astype(float)
        width = 3.0
        
        axs[1].bar(binned['bin_center'] - width/2, binned['model_local_control_volume_m3'] * m3_to_cy, width=width, label='Model')
        axs[1].bar(binned['bin_center'] + width/2, binned['observed_local_control_volume_m3'] * m3_to_cy, width=width, label='Observed')
        axs[1].set_ylabel("Volume Change (cy)")
        axs[1].set_title("Volume of Bed Sediment Change (10 RM Bins)")
        axs[1].legend()
        axs[1].axhline(0, color='black', linewidth=0.8)
            
        axs[2].bar(binned['bin_center'] - width/2, (binned['model_local_control_volume_m3'] * m3_to_cy) / years, width=width, label='Model')
        axs[2].bar(binned['bin_center'] + width/2, (binned['observed_local_control_volume_m3'] * m3_to_cy) / years, width=width, label='Observed')
        axs[2].set_ylabel("Vol Change / Year (cy/yr)")
        axs[2].set_title(f"Annual Averaged Volume Change ({years:.1f} years)")
        axs[2].legend()
        axs[2].axhline(0, color='black', linewidth=0.8)
        
        axs[3].plot(binned['bin_center'], binned['effective_width_m'] * m_to_ft, label='Model Width', linewidth=4, color='blue')
        axs[3].plot(binned['bin_center'], binned['effective_width_m'] * m_to_ft, label='Observed Width', linestyle='--', linewidth=2, color='orange')
        axs[3].set_ylabel("Width (feet)")
        axs[3].set_title("Channel Width (10 RM Average)")
        axs[3].legend()
        
        self.canvas.draw_idle()



class CalibrationWindow(QMainWindow):
    compared = Signal(object)
    failed = Signal(str)

    def __init__(self, config_path='', hdf_path=''):
        super().__init__()
        self.setWindowTitle('Bed-volume calibration — initial implementation')
        self.resize(1150, 850)
        self.workers = WorkerManager(self)
        self.settings = None
        self.loaded_config_path = None
        self.loaded_hdf_path = None
        self.result = None
        self.provenance = None
        self.config_path = QLineEdit(str(config_path))
        self.hdf_path = QLineEdit(str(hdf_path))
        self.gdb_path = QLineEdit(r'E:\LMR Comp Phase 2\Calibration_2004_2025\sediment_calibration\Bathymetry_Files\LMR_Bathy.gdb')
        self.before_survey, self.after_survey = QComboBox(), QComboBox()
        self.before_time, self.after_time = QComboBox(), QComboBox()
        self.load_button = QPushButton('Load configuration and model times')
        self.inspect_button = QPushButton('Inspect HDF metadata')
        self.inventory_button = QPushButton('List geodatabase surveys with ArcPy')
        self.compare_button = QPushButton('Process / compare (reuse survey cache)')
        self.export_button = QPushButton('Export CSV, provenance, and plot')
        self.export_button.setEnabled(False)
        self.diagnostic_button = QPushButton('Diagnostic Plots')
        self.diagnostic_button.setEnabled(False)
        self.figure = Figure(figsize=(10, 6), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.message = QTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(145)
        central = QWidget()
        layout = QVBoxLayout(central)
        form = QFormLayout()
        for title, field, kind in [('Configuration JSON', self.config_path, 'config'),
                                    ('RAS plan results (.p##.hdf)', self.hdf_path, 'hdf'),
                                    ('Observed geodatabase', self.gdb_path, 'gdb')]:
            line = QHBoxLayout()
            line.addWidget(field)
            button = QPushButton('Browse')
            button.clicked.connect(lambda checked=False, f=field, k=kind: self._browse(f, k))
            line.addWidget(button)
            form.addRow(title, line)
        form.addRow('Baseline observed survey', self.before_survey)
        form.addRow('Target observed survey', self.after_survey)
        form.addRow('Baseline model output', self.before_time)
        form.addRow('Target model output', self.after_time)
        layout.addLayout(form)
        row = QHBoxLayout()
        for button, callback in [(self.load_button, self.load), (self.inspect_button, self.inspect),
                                 (self.inventory_button, self.inventory), (self.compare_button, self.compare),
                                 (self.diagnostic_button, self.show_diagnostics), (self.export_button, self.export)]:
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(QLabel('Positive = deposition; negative = erosion. Compare two surveys over matched model dates.'))
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        layout.addWidget(self.message)
        self.setCentralWidget(central)
        for field in (self.config_path, self.hdf_path, self.gdb_path):
            field.textChanged.connect(self._invalidate_result)
        for combo in (self.before_survey, self.after_survey, self.before_time, self.after_time):
            combo.currentIndexChanged.connect(self._invalidate_result)
        if config_path:
            QTimer.singleShot(0, self.load)

    def _browse(self, field, kind):
        if kind == 'gdb':
            value = QFileDialog.getExistingDirectory(self, 'Select LMR_Bathy.gdb', field.text())
        else:
            filters = 'JSON (*.json)' if kind == 'config' else 'HEC-RAS results (*.hdf)'
            value, _ = QFileDialog.getOpenFileName(self, 'Select file', field.text(), filters)
        if value:
            field.setText(value)

    def _busy(self, busy):
        for widget in (self.load_button, self.inspect_button, self.inventory_button, self.compare_button,
                       self.config_path, self.hdf_path, self.gdb_path, self.before_survey, self.after_survey,
                       self.before_time, self.after_time):
            widget.setEnabled(not busy)
        self.export_button.setEnabled(not busy and self.result is not None)
        self.diagnostic_button.setEnabled(not busy and self.result is not None)

    def _invalidate_result(self, *_):
        self.result = self.provenance = None
        self.export_button.setEnabled(False)
        self.diagnostic_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()

    def _error(self, error):
        self._busy(False)
        self.message.setPlainText(str(error))
        self.failed.emit(str(error))

    def load(self):
        try:
            self.settings = load_config(self.config_path.text())
            self.loaded_config_path = self.loaded_hdf_path = None
            self.result = self.provenance = None
            for combo in (self.before_survey, self.after_survey):
                combo.clear()
                for name, source in self.settings['surveys'].items():
                    combo.addItem(f'{name} — {source.get("date") or "actual date required"}', name)
            self.after_survey.setCurrentIndex(max(0, self.after_survey.count()-1))
            gdbs = [s['path'] for s in self.settings['surveys'].values() if s['kind'].startswith('gdb_')]
            if gdbs:
                self.gdb_path.setText(gdbs[0])
            self._busy(True)
            mapping = copy.deepcopy(self.settings['model'])
            path = self.hdf_path.text()
            self.workers.submit('load', lambda: model_times(path, mapping), self._loaded, self._error)
        except Exception as error:
            self._error(error)

    def _loaded(self, times):
        for combo in (self.before_time, self.after_time):
            combo.clear()
            for index, date in enumerate(times):
                combo.addItem(str(date), index)
        self.after_time.setCurrentIndex(len(times)-1)
        self.loaded_config_path = self.config_path.text()
        self.loaded_hdf_path = self.hdf_path.text()
        self._busy(False)
        self.message.setPlainText('Select the survey pair and matching model times. Local mapping/CRS/datum verification gates remain mandatory.')

    def inspect(self):
        self._busy(True)
        path = self.hdf_path.text()
        self.workers.submit('inspect', lambda: metadata_report(path), self._show_metadata, self._error)

    def _show_metadata(self, report):
        self._busy(False)
        dialog = QMessageBox(self)
        dialog.setWindowTitle('HDF metadata — no result arrays read')
        dialog.setText(f'{len(report["datasets"])} datasets; HEC version {report["file_version"]}.')
        dialog.setDetailedText(json.dumps(report, indent=2))
        dialog.exec()

    def inventory(self):
        if not self.settings:
            self._error('Load a configuration first; it supplies the ArcGIS Python executable.')
            return
        self._busy(True)
        request = {'operation': 'inventory', 'gdb': self.gdb_path.text()}
        python = self.settings.get('arcpy_python')
        self.workers.submit('inventory', lambda: arcpy_request(request, python), self._inventory_done, self._error)

    def _inventory_done(self, items):
        self._busy(False)
        self.message.setPlainText(json.dumps(items, indent=2) + '\nSelect configured surveys above. New layers need verified dates and field mappings in the JSON configuration.')

    def compare(self):
        if (not self.settings or self.before_time.currentData() is None or
            self.config_path.text() != self.loaded_config_path or self.hdf_path.text() != self.loaded_hdf_path):
            self._error('Load configuration and model output dates first.')
            return
        settings = copy.deepcopy(self.settings)
        for source in settings['surveys'].values():
            if source['kind'].startswith('gdb_'):
                source['path'] = self.gdb_path.text()
        path = self.hdf_path.text()
        names = self.before_survey.currentData(), self.after_survey.currentData()
        indices = self.before_time.currentData(), self.after_time.currentData()
        self._busy(True)
        self.message.setPlainText('Processing profiles and computing common support. Geodatabase hashing / raster sampling may take time.')
        self.workers.submit('compare', lambda: run_comparison(settings, path, *names, *indices), self._compared, self._error)

    def _compared(self, payload):
        self.result, self.provenance = payload
        self._busy(False)
        self.figure.clear()
        upper, lower = self.figure.subplots(2, 1)
        sections, intervals = self.result.sections.copy(), self.result.intervals.copy()
        
        m3_to_cy = 1.307950619
        m2_to_sqft = 10.7639104
        
        sections['RM'] = pd.to_numeric(sections['xs_id'], errors='coerce')
        x = sections['RM']
        
        upper.plot(x, sections.model_cumulative_m3 * m3_to_cy, label='Model: common profiles')
        upper.plot(x, sections.observed_cumulative_m3 * m3_to_cy, label='Observed: common profiles')
        if 'native_cumulative_m3' in sections:
            upper.plot(x, sections.native_cumulative_m3 * m3_to_cy, '--', label='Native RAS: verification audit')
        upper.set(xlabel='River Mile', ylabel='Cumulative bulk bed change (cubic yards)',
                  title=f'{self.provenance["survey_before"]} → {self.provenance["survey_after"]}: '
                        f'{self.provenance["model_before_time"]} → {self.provenance["model_after_time"]}')
        upper.axhline(0, color='grey', linewidth=.5)
        upper.invert_xaxis()
        upper.legend()
        
        mid = 0.5 * (x.to_numpy()[:-1]+x.to_numpy()[1:])
        lower.plot(mid, (intervals.model_volume_change_m3/intervals.length_m) * m2_to_sqft, label='Model')
        lower.plot(mid, (intervals.observed_volume_change_m3/intervals.length_m) * m2_to_sqft, label='Observed')
        lower.set(xlabel='River Mile', ylabel='Average Area Change (sq ft)')
        lower.invert_xaxis()
        lower.legend()
        self.canvas.draw_idle()
        self.message.setPlainText(json.dumps(self.result.metrics, indent=2) + '\nCache: ' +
                                  ', '.join(f'{c["survey"]}: {"hit" if c["hit"] else "processed"}' for c in self.provenance['cache']))
        self.compared.emit(self.result)

    def show_diagnostics(self):
        if self.result is not None and self.provenance is not None:
            self.diag_window = DiagnosticPlotsWindow(self.result, self.provenance, self)
            self.diag_window.show()

    def export(self):
        directory = QFileDialog.getExistingDirectory(self, 'Select export parent folder')
        if directory:
            try:
                saved = export_comparison(self.result, self.provenance, directory)
                self.figure.savefig(saved/'comparison.png', dpi=180)
                self.message.append(f'Exported to {saved}')
            except Exception as error:
                self._error(error)

    def closeEvent(self, event):
        if not self.workers.idle():
            event.ignore()
            self.message.setPlainText('Waiting for the current read-only operation to finish before closing.')
            QTimer.singleShot(100, self.close)
        else:
            event.accept()