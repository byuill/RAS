"""Background reads, reversible survey review, and matched bed-change diagnostics."""
import copy
import json
from pathlib import Path
import threading

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from gui.workers import WorkerManager
from tools.hdf_metadata import metadata_report
from .plots import draw_comparison, draw_diagnostics, draw_section, draw_time_series
from .qaqc_gui import SurveyQaqcWindow
from .sources import arcpy_request, model_times
from .workflow import (export_comparison, export_time_series, load_config, match_survey_times,
                       run_comparison, run_survey_qaqc, run_time_series)


class DiagnosticPlotsWindow(QMainWindow):
    def __init__(self, result, provenance, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bed-change performance and spatial patterns')
        self.resize(1200, 1000)
        self.result = result
        self.figure = Figure(figsize=(11, 10), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.quantity = QComboBox()
        for label, value in [('Shape of bed change', 'change'), ('Target bed shape', 'target_bed'), ('Baseline bed shape', 'baseline_bed')]:
            self.quantity.addItem(label, value)
        central, layout = QWidget(), QVBoxLayout()
        central.setLayout(layout)
        layout.addWidget(self.quantity)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        layout.addWidget(QLabel('Derivatives use downstream chainage within supported segments. Check footprint coverage and survey QA/QC before interpreting them.'))
        self.setCentralWidget(central)
        self.quantity.currentIndexChanged.connect(self.draw)
        self.draw()

    def draw(self, *_):
        draw_diagnostics(self.figure, self.result, self.quantity.currentData())
        self.canvas.draw_idle()


class SectionProfilesWindow(QMainWindow):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cross-section profiles and bed change')
        self.resize(1000, 800)
        self.result = result
        self.section = QComboBox()
        self.section.addItems(result.sections.xs_id.tolist())
        self.figure = Figure(figsize=(10, 7), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        central, layout = QWidget(), QVBoxLayout()
        central.setLayout(layout)
        layout.addWidget(self.section)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        self.setCentralWidget(central)
        self.section.currentTextChanged.connect(self.draw)
        self.draw()

    def draw(self, *_):
        draw_section(self.figure, self.result, self.section.currentText())
        self.canvas.draw_idle()


class CalibrationWindow(QMainWindow):
    compared = Signal(object)
    failed = Signal(str)

    def __init__(self, config_path='', hdf_path=''):
        super().__init__()
        self.setWindowTitle('HEC-RAS bathymetry and observed bed-change comparison')
        self.resize(1250, 900)
        self.workers = WorkerManager(self)
        self._closing = False
        self._cancel = threading.Event()
        self.settings = None
        self.loaded_config_path = self.loaded_hdf_path = None
        self.result = self.provenance = self.series = None
        self.config_path, self.hdf_path, self.gdb_path = QLineEdit(str(config_path)), QLineEdit(str(hdf_path)), QLineEdit()
        self.before_survey, self.after_survey, self.before_time, self.after_time = (QComboBox() for _ in range(4))
        self.load_button = QPushButton('Load configuration and model dates')
        self.inspect_button = QPushButton('Inspect HDF metadata')
        self.inventory_button = QPushButton('List geodatabase surveys')
        self.qaqc_button = QPushButton('Survey QA/QC')
        self.compare_button = QPushButton('Compare selected surveys')
        self.series_button = QPushButton('Compare all survey intervals')
        self.diagnostic_button = QPushButton('Pattern diagnostics')
        self.profile_button = QPushButton('Cross-section profiles')
        self.export_button = QPushButton('Export results and plots')
        self.save_config_button = QPushButton('Save configuration copy')
        self.cancel_button = QPushButton('Cancel operation')
        self.cancel_button.setEnabled(False)
        self.figure = Figure(figsize=(11, 6), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.message = QTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(170)
        central, layout = QWidget(), QVBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)
        form = QFormLayout()
        self.browse_buttons = []
        for title, field, kind in [('Configuration JSON', self.config_path, 'config'),
                                    ('RAS plan result HDF', self.hdf_path, 'hdf'),
                                    ('Geodatabase override (optional)', self.gdb_path, 'gdb')]:
            line = QHBoxLayout()
            line.addWidget(field)
            button = QPushButton('Browse')
            button.clicked.connect(lambda checked=False, f=field, k=kind: self._browse(f, k))
            self.browse_buttons.append(button)
            line.addWidget(button)
            form.addRow(title, line)
        for label, control in [('Baseline survey', self.before_survey), ('Target survey', self.after_survey),
                               ('Baseline model output', self.before_time), ('Target model output', self.after_time)]:
            form.addRow(label, control)
        layout.addLayout(form)
        for choices in [[(self.load_button, self.load), (self.inspect_button, self.inspect),
                         (self.inventory_button, self.inventory), (self.qaqc_button, self.review_surveys)],
                        [(self.compare_button, self.compare), (self.series_button, self.compare_series),
                         (self.diagnostic_button, self.show_diagnostics), (self.profile_button, self.show_profiles),
                         (self.export_button, self.export), (self.save_config_button, self.save_config),
                         (self.cancel_button, self.cancel)]]:
            actions = QHBoxLayout()
            for button, callback in choices:
                button.clicked.connect(callback)
                actions.addWidget(button)
            layout.addLayout(actions)
        layout.addWidget(QLabel('Positive = deposition; negative = erosion. Compare magnitude and spatial pattern on the same sampled bed footprint.'))
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        layout.addWidget(self.message)
        for field in (self.config_path, self.hdf_path, self.gdb_path):
            field.textChanged.connect(self._invalidate_result)
        for combo in (self.before_survey, self.after_survey, self.before_time, self.after_time):
            combo.currentIndexChanged.connect(self._invalidate_result)
        self._busy(False)
        if config_path:
            QTimer.singleShot(0, self.load)

    def _browse(self, field, kind):
        if kind == 'gdb':
            value = QFileDialog.getExistingDirectory(self, 'Select survey geodatabase', field.text())
        else:
            filters = 'JSON (*.json)' if kind == 'config' else 'HEC-RAS results (*.hdf)'
            value, _ = QFileDialog.getOpenFileName(self, 'Select file', field.text(), filters)
        if value:
            field.setText(value)

    def _busy(self, busy):
        for widget in [self.load_button, self.inspect_button, self.inventory_button, self.compare_button,
                       self.qaqc_button, self.series_button, self.save_config_button, self.config_path,
                       self.hdf_path, self.gdb_path, self.before_survey, self.after_survey,
                       self.before_time, self.after_time, *self.browse_buttons]:
            widget.setEnabled(not busy)
        self.export_button.setEnabled(not busy and (self.result is not None or self.series is not None))
        self.diagnostic_button.setEnabled(not busy and self.result is not None)
        self.profile_button.setEnabled(not busy and self.result is not None)
        self.cancel_button.setEnabled(busy)

    def _invalidate_result(self, *_):
        self.result = self.provenance = self.series = None
        self.export_button.setEnabled(False)
        self.diagnostic_button.setEnabled(False)
        self.profile_button.setEnabled(False)
        for attribute in ('diag_window', 'profile_window'):
            window = getattr(self, attribute, None)
            if window:
                window.close()
        self.figure.clear()
        self.canvas.draw_idle()

    def _error(self, error):
        self._busy(False)
        if self._closing:
            return
        self.message.setPlainText(str(error))
        self.failed.emit(str(error))

    def _submit(self, name, operation, success):
        self._cancel = threading.Event()
        cancel = self._cancel
        self._busy(True)
        def work():
            payload = operation(cancel)
            if cancel.is_set():
                raise ValueError('Operation cancelled. Source files are unchanged.')
            return payload
        def completed(payload):
            if not self._closing:
                success(payload)
        self.workers.submit(name, work, completed, self._error)

    def cancel(self):
        self._cancel.set()
        self.message.setPlainText('Cancellation requested. The current file/ArcPy read must finish before stopping safely.')

    def load(self):
        self._invalidate_result()
        self.loaded_config_path = self.loaded_hdf_path = None
        self.settings = None
        try:
            self.settings = load_config(self.config_path.text())
            self.settings_path = self.config_path.text()
            if not self.hdf_path.text():
                self.hdf_path.setText(self.settings.get('model', {}).get('path', ''))
            for combo in (self.before_survey, self.after_survey):
                combo.clear()
                for name, source in self.settings['surveys'].items():
                    combo.addItem(f'{name} — {source.get("date") or "date required"}', name)
            self.after_survey.setCurrentIndex(max(0, self.after_survey.count()-1))
            # An empty override preserves distinct source geodatabases from config.
            if not self.hdf_path.text():
                self.message.setPlainText('Surveys loaded. Survey QA/QC is available; select an HDF and reload for model comparison.')
                return
            mapping, path = copy.deepcopy(self.settings['model']), self.hdf_path.text()
            self._submit('load', lambda cancel: model_times(path, mapping), self._loaded)
        except Exception as error:
            self._error(error)

    def _loaded(self, times):
        self.times = times
        for combo in (self.before_time, self.after_time):
            combo.clear()
            for index, date in enumerate(times):
                combo.addItem(str(date), index)
        self.after_time.setCurrentIndex(len(times)-1)
        try:
            indices = match_survey_times(self.settings, times, [self.before_survey.currentData(), self.after_survey.currentData()])
            self.before_time.setCurrentIndex(indices[0])
            self.after_time.setCurrentIndex(indices[1])
        except ValueError:
            # Display all outputs for manual selection; alignment is still enforced on comparison.
            pass
        self.loaded_config_path, self.loaded_hdf_path = self.config_path.text(), self.hdf_path.text()
        self._busy(False)
        self.message.setPlainText('Survey/model dates loaded. Review survey QA/QC, then compare the selected interval or all configured surveys.')

    def _settings_snapshot(self):
        if not self.settings or self.config_path.text() != self.settings_path:
            raise ValueError('Load a configuration first.')
        settings = copy.deepcopy(self.settings)
        if self.gdb_path.text():
            for source in settings['surveys'].values():
                if source['kind'].startswith('gdb_'):
                    source['path'] = self.gdb_path.text()
        return settings

    def _comparison_inputs(self):
        if (self.before_time.currentData() is None or self.config_path.text() != self.loaded_config_path or
                self.hdf_path.text() != self.loaded_hdf_path):
            raise ValueError('Load configuration and model dates first.')
        return self._settings_snapshot(), self.hdf_path.text()

    def inspect(self):
        path = self.hdf_path.text()
        self._submit('inspect', lambda cancel: metadata_report(path), self._show_metadata)

    def _show_metadata(self, report):
        self._busy(False)
        dialog = QMessageBox(self)
        dialog.setWindowTitle('HDF metadata — no result arrays read')
        dialog.setText(f'{len(report["datasets"])} datasets; HEC version {report["file_version"]}.')
        dialog.setDetailedText(json.dumps(report, indent=2))
        dialog.exec()

    def inventory(self):
        try:
            settings = self._settings_snapshot()
            path = self.gdb_path.text() or next(s['path'] for s in settings['surveys'].values() if s['kind'].startswith('gdb_'))
            self._submit('inventory', lambda cancel: arcpy_request({'operation': 'inventory', 'gdb': path}, settings.get('arcpy_python')), self._inventory_done)
        except Exception as error:
            self._error(error)

    def _inventory_done(self, items):
        self._busy(False)
        self.message.setPlainText(json.dumps(items, indent=2)+'\nConfigure actual acquisition dates, units, and field mappings before comparing new layers.')

    def review_surveys(self):
        try:
            settings = self._settings_snapshot()
            names = list(dict.fromkeys([self.before_survey.currentData(), self.after_survey.currentData()]))
            self.message.setPlainText('Loading raw survey samples for QA/QC. Cached extraction is reused; no elevations are removed automatically.')
            self._submit('qaqc', lambda cancel: run_survey_qaqc(settings, names, cancel=cancel), self._review_ready)
        except Exception as error:
            self._error(error)

    def _review_ready(self, payload):
        self._busy(False)
        self.qaqc_window = SurveyQaqcWindow(*payload, self._apply_qaqc, self)
        self.qaqc_window.show()

    def _apply_qaqc(self, options):
        if not self.workers.idle():
            raise ValueError('Finish or cancel the current operation before applying QA/QC decisions.')
        for name, decisions in options.items():
            self.settings['surveys'][name]['qaqc'] = decisions
        self._invalidate_result()
        self.message.setPlainText('QA/QC decisions applied. Recompute comparisons; Save configuration copy preserves the decisions for future runs.')

    def compare(self):
        try:
            settings, path = self._comparison_inputs()
            names = self.before_survey.currentData(), self.after_survey.currentData()
            indices = self.before_time.currentData(), self.after_time.currentData()
            self._invalidate_result()
            self.message.setPlainText('Processing matched profiles, survey QA/QC, and bed-change pattern diagnostics…')
            self._submit('compare', lambda cancel: run_comparison(settings, path, *names, *indices, cancel=cancel), self._compared)
        except Exception as error:
            self._error(error)

    def _compared(self, payload):
        self.result, self.provenance = payload
        self._busy(False)
        draw_comparison(self.figure, self.result, self.provenance)
        self.canvas.draw_idle()
        m = self.result.metrics
        correlation = m['change_shape_correlation']
        shape = 'undefined (constant change)' if correlation is None else f'{correlation:.3f}'
        self.message.setPlainText(f'Model / observed volume: {m["model_total_m3"]:,.1f} / {m["observed_total_m3"]:,.1f} m³; '
                                 f'bias {m["total_bias_m3"]:,.1f} m³\n'
                                 f'Mean change RMSE: {m["mean_change_rmse_m"]:.3f} m; shape correlation: {shape}; '
                                 f'zone agreement: {m["zone_agreement_fraction"]:.1%}\n'
                                 f'XS used / excluded: {m["sections_used"]} / {m["sections_excluded"]}; '
                                 f'minimum transect footprint coverage: {m["minimum_footprint_coverage"]:.1%}\n'+
                                 '\n'.join(self.provenance['warnings']))
        self.compared.emit(self.result)

    def compare_series(self):
        try:
            settings, path = self._comparison_inputs()
            self._invalidate_result()
            self.message.setPlainText('Comparing consecutive survey intervals on fixed support across all dates…')
            self._submit('series', lambda cancel: run_time_series(settings, path, cancel=cancel), self._series_ready)
        except Exception as error:
            self._error(error)

    def _series_ready(self, series):
        self.series = series
        self._busy(False)
        draw_time_series(self.figure, series)
        self.canvas.draw_idle()
        self.message.setPlainText(series.summary[['survey_before', 'survey_after', 'mean_change_rmse_m',
                                                  'zone_agreement_fraction', 'change_shape_correlation']].to_string(index=False)+
                                  '\nAll intervals use the same accepted sections and lateral support. Export includes each interval’s diagnostics and QA/QC.')

    def show_diagnostics(self):
        if self.result is not None:
            self.diag_window = DiagnosticPlotsWindow(self.result, self.provenance, self)
            self.diag_window.show()

    def show_profiles(self):
        if self.result is not None:
            self.profile_window = SectionProfilesWindow(self.result, self)
            self.profile_window.show()

    def export(self):
        if self.result is None and self.series is None:
            return
        directory = QFileDialog.getExistingDirectory(self, 'Select export parent folder')
        if directory:
            result, provenance, series = self.result, self.provenance, self.series
            self._submit('export', lambda cancel: export_time_series(series, directory) if series is not None else
                         export_comparison(result, provenance, directory), self._exported)

    def _exported(self, saved):
        self._busy(False)
        self.message.append(f'Exported all results, plots, and audit data to {saved}')

    def save_config(self):
        try:
            settings = self._settings_snapshot()
            path, _ = QFileDialog.getSaveFileName(self, 'Save reviewed configuration copy', '', 'JSON (*.json)')
            if path:
                Path(path).write_text(json.dumps(settings, indent=2, allow_nan=False)+'\n', encoding='utf-8')
                self.message.append(f'Saved configuration with QA/QC decisions to {path}')
        except Exception as error:
            self._error(error)

    def closeEvent(self, event):
        self._closing = True
        self._cancel.set()
        if not self.workers.idle():
            event.ignore()
            self.message.setPlainText('Cancelling after the current read-only file operation finishes…')
            QTimer.singleShot(100, self.close)
        else:
            event.accept()
