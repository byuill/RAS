"""Background reads, reversible survey review, and matched bed-change diagnostics."""
import copy
import json
from pathlib import Path
import threading

import pandas as pd

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
    QCheckBox, QDoubleSpinBox, QGroupBox, QScrollArea, QSplitter)

from gui.workers import WorkerManager
from tools.hdf_metadata import metadata_report
from .plots import draw_comparison, draw_diagnostics, draw_section, draw_time_series
from .qaqc_gui import SurveyQaqcWindow
from .calculation_gui import CalculationAuditWindow
from .sources import arcpy_request, model_times
from .workflow import (export_comparison, export_time_series, load_config, match_survey_times,
                       run_comparison, run_survey_qaqc, run_time_series, _validate_alignment)
from .core import validate_transects
from .display_units import (customary_frame,
                            river_miles, uses_river_miles, select_river_mile_range)


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
        layout.addWidget(QLabel('River mile identifies model XS location. Derivatives use downstream distance within supported segments. Check footprint coverage and survey QA/QC before interpreting them.'))
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
        self.resize(1450, 960)
        self.workers = WorkerManager(self)
        self._closing = False
        self._cancel = threading.Event()
        self._is_busy = False
        self.settings = None
        self.loaded_config_path = self.loaded_hdf_path = None
        self.result = self.provenance = self.series = None
        self.config_path, self.hdf_path, self.gdb_path = QLineEdit(str(config_path)), QLineEdit(str(hdf_path)), QLineEdit()
        self.before_survey, self.after_survey, self.before_time, self.after_time = (QComboBox() for _ in range(4))
        self.load_button = QPushButton('Load data and dates')
        self.inspect_button = QPushButton('Inspect HDF metadata')
        self.inventory_button = QPushButton('List geodatabase surveys')
        self.qaqc_button = QPushButton('Review survey QA/QC…')
        self.compare_button = QPushButton('Calculate selected interval')
        self.series_button = QPushButton('Calculate all survey intervals')
        self.diagnostic_button = QPushButton('Pattern diagnostics')
        self.profile_button = QPushButton('Cross-section profiles')
        self.audit_button = QPushButton('Audit calculations / explore assumptions…')
        self.export_button = QPushButton('Export results and plots')
        self.save_config_button = QPushButton('Save configuration copy')
        self.cancel_button = QPushButton('Cancel operation')
        self.cancel_button.setEnabled(False)
        self.figure = Figure(figsize=(11, 6), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.message = QTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(170)
        self.range_enabled = QCheckBox('Limit to a river-mile range')
        self.upstream_rm, self.downstream_rm = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.upstream_rm, self.downstream_rm):
            spin.setRange(-100000, 100000)
            spin.setDecimals(3)
            spin.setSuffix(' RM')
            spin.setToolTip('Location from model cross-section station labels. Negative river miles are valid.')
        self.range_note = QLabel('Load a configuration to see the available model stations.')
        self.range_note.setWordWrap(True)
        self.range_available = False
        self.station_metadata = None
        self.status = QLabel('Start by loading a configuration and model result file.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('padding: 10px; background: #eaf1f7; color: #20384c; border-radius: 5px;')
        central, layout = QWidget(), QHBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)
        sidebar, workflow = QWidget(), QVBoxLayout()
        sidebar.setLayout(workflow)
        sidebar.setMinimumWidth(375)
        def group(title):
            box = QGroupBox(title)
            contents = QVBoxLayout(box)
            workflow.addWidget(box)
            return contents
        sources = group('1  Load data')
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.browse_buttons = []
        for title, field, kind in [('Configuration JSON', self.config_path, 'config'),
                                  ('RAS plan result HDF', self.hdf_path, 'hdf'),
                                  ('Geodatabase override (optional)', self.gdb_path, 'gdb')]:
            line = QHBoxLayout()
            line.addWidget(field)
            button = QPushButton('Browse…')
            button.clicked.connect(lambda checked=False, f=field, k=kind: self._browse(f, k))
            self.browse_buttons.append(button)
            line.addWidget(button)
            field.setToolTip('Full source path; configuration mappings and source units remain as configured.')
            form.addRow(title, line)
        sources.addLayout(form)
        sources.addWidget(self.load_button)
        details = QHBoxLayout()
        details.addWidget(self.inspect_button)
        details.addWidget(self.inventory_button)
        sources.addLayout(details)
        interval = group('2  Select dates and reach')
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        for label, control in [('Baseline survey → baseline model date', self.before_survey),
                               ('Baseline model output', self.before_time),
                               ('Target survey → target model date', self.after_survey),
                               ('Target model output', self.after_time)]:
            form.addRow(label, control)
        interval.addLayout(form)
        interval.addWidget(self.range_enabled)
        form = QFormLayout()
        form.addRow('Upstream river mile', self.upstream_rm)
        form.addRow('Downstream river mile', self.downstream_rm)
        interval.addLayout(form)
        interval.addWidget(self.range_note)
        calculate = group('3  Review and calculate')
        calculate.addWidget(self.qaqc_button)
        hint = QLabel('Review flags and datum evidence before comparing. Baseline precedes target; model dates must match the survey dates within the configured tolerance.')
        hint.setWordWrap(True)
        calculate.addWidget(hint)
        calculate.addWidget(self.compare_button)
        calculate.addWidget(self.series_button)
        calculate.addWidget(self.save_config_button)
        workflow.addStretch()
        workflow.addWidget(self.cancel_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(405)
        right, results = QWidget(), QVBoxLayout()
        right.setLayout(results)
        results.addWidget(self.status)
        review = QGroupBox('4  Inspect results and export')
        actions = QVBoxLayout(review)
        top = QHBoxLayout()
        top.addWidget(self.profile_button)
        top.addWidget(self.diagnostic_button)
        actions.addLayout(top)
        bottom = QHBoxLayout()
        bottom.addWidget(self.audit_button, 2)
        bottom.addWidget(self.export_button, 1)
        actions.addLayout(bottom)
        results.addWidget(review)
        results.addWidget(QLabel('ft • ft² • yd³ • model river miles     |     Positive = deposition; negative = erosion'))
        results.addWidget(NavigationToolbar2QT(self.canvas, self))
        results.addWidget(self.canvas, 1)
        results.addWidget(self.message)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(right)
        splitter.setSizes([420, 1010])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)
        for button in (self.load_button, self.compare_button, self.export_button):
            button.setMinimumHeight(36)
            button.setStyleSheet('QPushButton { font-weight: bold; padding: 6px; }')
        self.compare_button.setStyleSheet('QPushButton { background: #2166ac; color: white; font-weight: bold; padding: 8px; } QPushButton:disabled { background: #d9e0e6; color: #6b747c; }')
        for button, callback in [(self.load_button, self.load), (self.inspect_button, self.inspect),
            (self.inventory_button, self.inventory), (self.qaqc_button, self.review_surveys),
            (self.compare_button, self.compare), (self.series_button, self.compare_series),
            (self.save_config_button, self.save_config), (self.cancel_button, self.cancel),
            (self.diagnostic_button, self.show_diagnostics), (self.profile_button, self.show_profiles),
            (self.audit_button, self.show_calculation_audit), (self.export_button, self.export)]:
            button.clicked.connect(callback)
        for widget in (self.range_enabled, self.upstream_rm, self.downstream_rm):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._invalidate_result)
            else:
                widget.valueChanged.connect(self._invalidate_result)
        for field in (self.config_path, self.hdf_path, self.gdb_path):
            field.textChanged.connect(self._invalidate_result)
        for combo in (self.before_survey, self.after_survey):
            combo.currentIndexChanged.connect(self._survey_changed)
        for combo in (self.before_time, self.after_time):
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
        self._is_busy = busy
        configured = bool(self.settings and self.config_path.text() == getattr(self, 'settings_path', None))
        model_ready = (configured and self.loaded_config_path == self.config_path.text() and
                       self.loaded_hdf_path == self.hdf_path.text() and self.before_time.count() > 0)
        reason = 'Load data and dates to start.'
        valid_pair = False
        range_valid, range_error = True, ''
        if configured and self.range_available:
            rm = river_miles(self.station_metadata)
            selected = rm
            if self.range_enabled.isChecked():
                selected = rm[(rm <= self.upstream_rm.value()+1e-8) & (rm >= self.downstream_rm.value()-1e-8)]
                if self.upstream_rm.value() <= self.downstream_rm.value() or len(selected) < 2:
                    range_valid = False
                    range_error = 'Select at least two cross sections, with upstream RM greater than downstream RM.'
            selection = f'Selected: RM {selected[0]:g} → {selected[-1]:g} ({len(selected)} XS).' if range_valid else range_error
            self.range_note.setText(f'Manifest: RM {rm[0]:g} → {rm[-1]:g}.\n'+selection+' Bounds include existing XS only.')
        if model_ready:
            try:
                _validate_alignment(self.settings,
                    [self.before_survey.currentData(), self.after_survey.currentData()], self.times,
                    [self.before_time.currentData(), self.after_time.currentData()])
                if self.range_enabled.isChecked() and self.upstream_rm.value() <= self.downstream_rm.value():
                    raise ValueError('Upstream river mile must exceed downstream river mile.')
                valid_pair = True
                reason = 'Ready: review survey QA/QC, then calculate the selected interval.'
            except (ValueError, KeyError, TypeError) as error:
                reason = str(error)
        elif configured:
            reason = 'Surveys ready for QA/QC. Load an HDF with model dates to calculate bed change.'
        if not range_valid:
            reason = range_error
        for widget in (self.config_path, self.hdf_path, self.gdb_path, *self.browse_buttons):
            widget.setEnabled(not busy)
        self.load_button.setEnabled(not busy and bool(self.config_path.text().strip()))
        self.inspect_button.setEnabled(not busy and bool(self.hdf_path.text().strip()))
        self.inventory_button.setEnabled(not busy and configured and any(
            source['kind'].startswith('gdb_') for source in self.settings['surveys'].values()))
        for widget in (self.before_survey, self.after_survey, self.save_config_button):
            widget.setEnabled(not busy and configured)
        self.qaqc_button.setEnabled(not busy and configured and range_valid)
        for widget in (self.before_time, self.after_time):
            widget.setEnabled(not busy and model_ready)
        self.range_enabled.setEnabled(not busy and configured and self.range_available)
        for widget in (self.upstream_rm, self.downstream_rm):
            widget.setEnabled(not busy and configured and self.range_available and self.range_enabled.isChecked())
        self.compare_button.setEnabled(not busy and valid_pair and range_valid)
        self.compare_button.setToolTip(reason)
        series_ready = False
        if model_ready:
            try:
                names = sorted(self.settings['surveys'], key=lambda name: pd.Timestamp(self.settings['surveys'][name]['date']))
                match_survey_times(self.settings, self.times, names)
                series_ready = len(names) > 1
            except (ValueError, KeyError, TypeError):
                pass
        self.series_button.setEnabled(not busy and series_ready and range_valid)
        self.export_button.setEnabled(not busy and (self.result is not None or self.series is not None))
        for widget in (self.diagnostic_button, self.profile_button, self.audit_button):
            widget.setEnabled(not busy and self.result is not None)
        self.cancel_button.setEnabled(busy)
        if busy:
            reason = 'Working… You can cancel the current operation.'
        elif self.result is not None or self.series is not None:
            reason = 'Results ready. Inspect profiles, spatial patterns and calculation assumptions; then export.'
        self.status.setText(reason)

    def _survey_changed(self, *_):
        if self.loaded_hdf_path == self.hdf_path.text() and hasattr(self, 'times') and self.settings:
            for survey, output in ((self.before_survey, self.before_time), (self.after_survey, self.after_time)):
                source = self.settings['surveys'].get(survey.currentData(), {})
                try:
                    date = pd.Timestamp(source['date'])
                    if not pd.isna(date) and date.tz is None:
                        output.setCurrentIndex(int(abs(self.times-date).argmin()))
                except (ValueError, KeyError, TypeError):
                    pass
        self._invalidate_result()

    def _invalidate_result(self, *_):
        had_results = self.result is not None or self.series is not None
        self.result = self.provenance = self.series = None
        self.export_button.setEnabled(False)
        self.diagnostic_button.setEnabled(False)
        self.profile_button.setEnabled(False)
        self.audit_button.setEnabled(False)
        for attribute in ('diag_window', 'profile_window', 'audit_window'):
            window = getattr(self, attribute, None)
            if window:
                window.close()
        self.figure.clear()
        self.canvas.draw_idle()
        if had_results:
            self.message.setPlainText('Inputs changed. Calculate again to refresh results and plots.')
        self._busy(self._is_busy)

    def _error(self, error):
        self._busy(False)
        if self._closing:
            return
        self.status.setText('Operation stopped. Review the details below and the inputs before retrying.')
        self.message.setPlainText(str(error))
        self.failed.emit(str(error))

    def _submit(self, name, operation, success):
        self._cancel = threading.Event()
        cancel = self._cancel
        self._busy(True)
        self.status.setText(f'{name.capitalize()} in progress… Cancel is available below the workflow.')
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
        self.before_time.clear()
        self.after_time.clear()
        if getattr(self, 'qaqc_window', None):
            self.qaqc_window.close()
        try:
            self.settings = load_config(self.config_path.text())
            self.settings_path = self.config_path.text()
            transects, sections = validate_transects(pd.read_csv(self.settings['transects'], dtype={'xs_id': str}))
            self.station_metadata = sections
            self.range_available = bool(uses_river_miles(sections) and (pd.Series(river_miles(sections)).diff().dropna() < 0).all())
            bounds = self.settings.get('river_mile_range')
            select_river_mile_range(transects, bounds)
            self.range_enabled.setChecked(bool(bounds))
            if self.range_available:
                rm = river_miles(sections)
                for spin in (self.upstream_rm, self.downstream_rm):
                    spin.setRange(float(rm[-1]), float(rm[0]))
                self.upstream_rm.setValue(bounds['upstream'] if bounds else rm[0])
                self.downstream_rm.setValue(bounds['downstream'] if bounds else rm[-1])
                self.range_note.setText(f'Manifest: RM {rm[0]:g} → {rm[-1]:g}. Bounds include existing XS only; exact selected stations appear in results.')
            else:
                if bounds:
                    raise ValueError('This configuration requests river-mile selection but stationing is unavailable or not downstream-decreasing.')
                self.range_note.setText('Text XS IDs: supply a river_mile manifest column to locate sections by river mile. Distance fallback displays in miles.')
            if not self.hdf_path.text():
                self.hdf_path.setText(self.settings.get('model', {}).get('path', ''))
            for combo in (self.before_survey, self.after_survey):
                combo.clear()
                for name, source in self.settings['surveys'].items():
                    combo.addItem(f'{name} — {source.get("date") or "date required"}', name)
            self.after_survey.setCurrentIndex(max(0, self.after_survey.count()-1))
            # An empty override preserves distinct source geodatabases from config.
            if not self.hdf_path.text():
                self._busy(False)
                self.message.setPlainText('Surveys loaded. Survey QA/QC is available; select an HDF and reload for model comparison.')
                return
            mapping, path = copy.deepcopy(self.settings['model']), self.hdf_path.text()
            self._submit('load', lambda cancel: model_times(path, mapping), self._loaded)
        except Exception as error:
            self.settings = None
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
        if self.range_enabled.isChecked():
            rm = river_miles(self.station_metadata)
            selected = rm[(rm <= self.upstream_rm.value()+1e-8) & (rm >= self.downstream_rm.value()-1e-8)]
            if self.upstream_rm.value() <= self.downstream_rm.value() or len(selected) < 2:
                raise ValueError('Select at least two cross sections, with upstream RM greater than downstream RM.')
            settings['river_mile_range'] = {'upstream': self.upstream_rm.value(), 'downstream': self.downstream_rm.value()}
        else:
            settings.pop('river_mile_range', None)
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
        if getattr(self, 'qaqc_window', None):
            self.qaqc_window.close()
        review_settings = payload[1]['settings']
        self.qaqc_window = SurveyQaqcWindow(*payload, lambda options: self._apply_review(options, review_settings), self)
        self.qaqc_window.show()

    def _apply_review(self, options, review_settings):
        current = self._settings_snapshot()
        review_settings = copy.deepcopy(review_settings)
        for settings in (current, review_settings):
            for source in settings['surveys'].values():
                source.pop('qaqc', None)
        if current != review_settings:
            raise ValueError('Data sources or selected reach changed. Reopen survey QA/QC before applying decisions.')
        self._apply_qaqc(options)

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
        m = customary_frame(pd.DataFrame([self.result.metrics])).iloc[0]
        correlation = m['change_shape_correlation']
        shape = 'undefined (constant change)' if correlation is None else f'{correlation:.3f}'
        self.message.setPlainText(f'Model / observed volume: {m["model_total_yd3"]:,.1f} / {m["observed_total_yd3"]:,.1f} yd³; '
                                 f'bias {m["total_bias_yd3"]:,.1f} yd³\n'
                                 f'Mean change RMSE: {m["mean_change_rmse_ft"]:.3f} ft; shape correlation: {shape}; '
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
        self.message.setPlainText(customary_frame(series.summary[['survey_before', 'survey_after', 'mean_change_rmse_m',
                                                  'zone_agreement_fraction', 'change_shape_correlation']]).to_string(index=False)+
                                  '\nAll intervals use the same accepted sections and lateral support. Export includes each interval’s diagnostics and QA/QC.')

    def show_diagnostics(self):
        if self.result is not None:
            self.diag_window = DiagnosticPlotsWindow(self.result, self.provenance, self)
            self.diag_window.show()

    def show_profiles(self):
        if self.result is not None:
            self.profile_window = SectionProfilesWindow(self.result, self)
            self.profile_window.show()

    def show_calculation_audit(self):
        if self.result is not None:
            self.audit_window = CalculationAuditWindow(self.result, self.provenance, self)
            self.audit_window.show()

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
