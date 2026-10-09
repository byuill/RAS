"""Standalone starter GUI. ArcPy and HDF work run outside the GUI thread."""
import copy
import json
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from gui.workers import WorkerManager
from tools.hdf_metadata import metadata_report
from .sources import arcpy_request, model_times
from .workflow import export_comparison, load_config, run_comparison


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
                                 (self.export_button, self.export)]:
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

    def _invalidate_result(self, *_):
        self.result = self.provenance = None
        self.export_button.setEnabled(False)
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
        sections, intervals = self.result.sections, self.result.intervals
        x = sections.chainage_m / 1000
        upper.plot(x, sections.model_cumulative_m3, label='Model: common profiles')
        upper.plot(x, sections.observed_cumulative_m3, label='Observed: common profiles')
        if 'native_cumulative_m3' in sections:
            upper.plot(x, sections.native_cumulative_m3, '--', label='Native RAS: verification audit')
        upper.set(xlabel='Downstream chainage (km)', ylabel='Cumulative bulk bed change (m³)',
                  title=f'{self.provenance["survey_before"]} → {self.provenance["survey_after"]}: '
                        f'{self.provenance["model_before_time"]} → {self.provenance["model_after_time"]}')
        upper.axhline(0, color='grey', linewidth=.5)
        upper.legend()
        mid = 0.5 * (x.to_numpy()[:-1]+x.to_numpy()[1:])
        lower.plot(mid, intervals.model_volume_change_m3/intervals.length_m, label='Model')
        lower.plot(mid, intervals.observed_volume_change_m3/intervals.length_m, label='Observed')
        lower.set(xlabel='Downstream chainage (km)', ylabel='Interval volume / length (m²)')
        lower.legend()
        self.canvas.draw_idle()
        self.message.setPlainText(json.dumps(self.result.metrics, indent=2) + '\nCache: ' +
                                  ', '.join(f'{c["survey"]}: {"hit" if c["hit"] else "processed"}' for c in self.provenance['cache']))
        self.compared.emit(self.result)

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
