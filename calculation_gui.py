"""Interactive accounting ledger and reversible assumption experiments."""
import copy
import threading

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

try:
    from .workers import WorkerManager
except ImportError:
    from workers import WorkerManager
from .calculation_audit import CALCULATION_GUIDE, run_sensitivity, volume_uncertainty
from .plots import draw_calculation_audit, draw_variability, draw_sensitivity
from .workflow import export_sensitivity


class CalculationAuditWindow(QMainWindow):
    def __init__(self, reference, provenance, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Volume calculation audit and assumption explorer')
        self.resize(1450, 1000)
        self.reference, self.provenance = reference, provenance
        self.result = reference
        self.scenarios = []
        self.exploration = None
        self._closing = False
        self._cancel = threading.Event()
        self.workers = WorkerManager(self)
        self.controls = {}
        self.section, self.cumulative, self.scenario = QComboBox(), QComboBox(), QComboBox()
        self.scenario.addItem('Reference')
        self.section.addItems(reference.sections.xs_id.tolist())
        self.cumulative.addItem('Node control-volume sum (current curve)', 'node')
        self.cumulative.addItem('Completed-reach prefix (boundary curve)', 'boundary')
        self.figure = Figure(figsize=(11, 8), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.variability_figure = Figure(figsize=(11, 8), constrained_layout=True)
        self.variability_canvas = FigureCanvasQTAgg(self.variability_figure)
        self.sensitivity_figure = Figure(figsize=(11, 8), constrained_layout=True)
        self.sensitivity_canvas = FigureCanvasQTAgg(self.sensitivity_figure)
        self.lateral_table, self.reach_table, self.summary_table, self.section_table = (QTableWidget() for _ in range(4))
        self.message = QTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(145)
        self.run_button = QPushButton('Calculate and keep scenario')
        self.reset_button = QPushButton('Reset to reference')
        self.export_button = QPushButton('Export scenario comparison and audits')
        self.export_button.setEnabled(False)
        self.export_specs_button = QPushButton('Save scenario instructions')
        self.export_specs_button.setEnabled(False)

        central, layout = QWidget(), QHBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)
        left, controls_layout = QWidget(), QVBoxLayout()
        left.setLayout(controls_layout)
        label = QLabel('Explore assumptions on the original reviewed profiles. Source files and the main comparison remain unchanged.')
        label.setWordWrap(True)
        controls_layout.addWidget(label)
        form = QFormLayout()
        method = QComboBox()
        for text, value in [('Average end area (default)', 'average_end_area'),
                            ('Upstream area held through reach', 'upstream'),
                            ('Downstream area held through reach', 'downstream')]:
            method.addItem(text, value)
        self.controls['longitudinal_method'] = method
        form.addRow('Longitudinal estimator', method)
        domain = QComboBox()
        domain.addItems(['intersection', 'transect'])
        self.controls['domain_mode'] = domain
        form.addRow('Lateral domain', domain)
        for key, text, low, high, tip in [
            ('max_gap_m', 'Maximum source gap (m)', .001, 1e6, 'NoData barriers are always retained, even at a large gap limit.'),
            ('min_coverage', 'Minimum domain coverage', .001, 1, 'Sections below this coverage disconnect the reach; gaps are never filled.'),
            ('min_common_width_m', 'Minimum accepted width (m)', 0, 1e6, 'Required effective width after removing unsupported lateral intervals.'),
            ('grid_spacing_m', 'Integration grid spacing (m)', .001, 1e6, 'All source knots remain; exact linear integration should be invariant to this spacing.'),
            ('lateral_trim_fraction', 'Trim fraction per bank', 0, .49, 'Symmetric fraction of the original manifest width; changes the sampled footprint.'),
            ('change_threshold_m', 'Classification threshold (m)', 0, 1000, 'Changes class fractions and zones, while retaining all signed volume.'),
            ('observed_target_shift_m', 'Hypothetical target shift (m)', -100, 100, 'Sensitivity experiment only. Not a verified datum correction; sign is added to target survey.'),
            ('before_sigma_m', 'Baseline survey error σ (m)', 0, 100, 'One-sigma error coherent across each section; supply evidence-based uncertainty.'),
            ('after_sigma_m', 'Target survey error σ (m)', 0, 100, 'One-sigma error coherent across each section; model treated as exact.'),
            ('temporal_correlation', 'Before/after error correlation', -1, 1, '0 independent epochs; 1 shared error that can cancel when survey sigmas match.'),
            ('spatial_correlation', 'Between-XS error correlation', 0, 1, '0 independent sections; 1 fully coherent reach error (conservative default).'),
        ]:
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(low, high)
            spin.setToolTip(tip)
            self.controls[key] = spin
            form.addRow(text, spin)
        controls_layout.addLayout(form)
        for button in (self.run_button, self.reset_button, self.export_button, self.export_specs_button):
            controls_layout.addWidget(button)
        controls_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(410)
        layout.addWidget(scroll)
        right, right_layout = QWidget(), QVBoxLayout()
        right.setLayout(right_layout)
        selectors = QHBoxLayout()
        selectors.addWidget(self.scenario)
        selectors.addWidget(QLabel('Audited XS'))
        selectors.addWidget(self.section)
        selectors.addWidget(self.cumulative)
        right_layout.addLayout(selectors)
        self.tabs = QTabWidget()
        plot, plot_layout = QWidget(), QVBoxLayout()
        plot.setLayout(plot_layout)
        plot_layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        plot_layout.addWidget(self.canvas)
        self.tabs.addTab(plot, 'Calculation stages')
        variability, variability_layout = QWidget(), QVBoxLayout()
        variability.setLayout(variability_layout)
        variability_layout.addWidget(NavigationToolbar2QT(self.variability_canvas, self))
        variability_layout.addWidget(self.variability_canvas)
        self.tabs.addTab(variability, 'Variability / cancellation')
        sensitivity, sensitivity_layout = QWidget(), QVBoxLayout()
        sensitivity.setLayout(sensitivity_layout)
        sensitivity_layout.addWidget(NavigationToolbar2QT(self.sensitivity_canvas, self))
        sensitivity_layout.addWidget(self.sensitivity_canvas)
        self.tabs.addTab(sensitivity, 'Assumption sensitivity')
        for table, text in [(self.lateral_table, 'Lateral ledger'), (self.reach_table, 'Reach ledger'),
                            (self.section_table, 'Section accounting'), (self.summary_table, 'Scenario summary')]:
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.tabs.addTab(table, text)
        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setPlainText(CALCULATION_GUIDE+'\n'+volume_uncertainty(reference)['interpretation'])
        self.tabs.addTab(guide, 'How it works')
        right_layout.addWidget(self.tabs)
        self.calculation_text = QLabel()
        self.calculation_text.setWordWrap(True)
        right_layout.addWidget(self.calculation_text)
        right_layout.addWidget(self.message)
        layout.addWidget(right, 1)
        self.run_button.clicked.connect(self.calculate)
        self.reset_button.clicked.connect(self.reset)
        self.export_button.clicked.connect(self.export)
        self.export_specs_button.clicked.connect(self.export_specs)
        self.section.currentTextChanged.connect(self.draw)
        self.scenario.currentTextChanged.connect(self.select_scenario)
        self.cumulative.currentIndexChanged.connect(self.draw)
        self.reset()

    def reset(self):
        self.scenarios = []
        self.exploration = None
        self.result = self.reference
        self.scenario.blockSignals(True)
        self.scenario.clear()
        self.scenario.addItem('Reference')
        self.scenario.blockSignals(False)
        defaults = dict(self.reference.calculation_options)
        defaults['change_threshold_m'] = self.reference.metrics['change_detection_threshold_m']
        defaults['observed_target_shift_m'] = 0.
        error = self.provenance.get('volume_uncertainty', {})
        defaults.update({k: error.get(k, 1. if k == 'spatial_correlation' else 0.) for k in
                         ('before_sigma_m', 'after_sigma_m', 'temporal_correlation', 'spatial_correlation')})
        for key, widget in self.controls.items():
            if isinstance(widget, QComboBox):
                index = widget.findData(defaults[key]) if key == 'longitudinal_method' else widget.findText(defaults[key])
                widget.setCurrentIndex(index)
            else:
                widget.setValue(defaults[key])
        self.export_button.setEnabled(False)
        self.export_specs_button.setEnabled(False)
        self.populate(self.summary_table, pd.DataFrame())
        self.sensitivity_figure.clear()
        self.sensitivity_canvas.draw_idle()
        self.draw()
        self.describe('Reference')

    def collect(self):
        controls = {key: (widget.currentData() if key == 'longitudinal_method' else widget.currentText())
                    if isinstance(widget, QComboBox) else widget.value() for key, widget in self.controls.items()}
        uncertainty = {key: controls.pop(key) for key in
                       ('before_sigma_m', 'after_sigma_m', 'temporal_correlation', 'spatial_correlation')}
        return controls, uncertainty

    def busy(self, value):
        for widget in (*self.controls.values(), self.run_button, self.reset_button, self.scenario):
            widget.setEnabled(not value)
        self.export_button.setEnabled(not value and self.exploration is not None)
        self.export_specs_button.setEnabled(not value and self.exploration is not None)

    def calculate(self):
        overrides, uncertainty = self.collect()
        scenarios = copy.deepcopy(self.scenarios)+[{'name': f'Scenario {len(self.scenarios)+1}', 'overrides': overrides}]
        self.busy(True)
        self.message.setPlainText('Recomputing all retained scenarios on original reviewed profiles…')
        self.workers.submit('calculate', lambda: run_sensitivity(self.reference, scenarios,
            uncertainty=uncertainty, cancel=self._cancel), lambda report: self.completed(report, scenarios), self.error)

    def completed(self, report, scenarios):
        if self._closing:
            return
        self.exploration, self.scenarios = report, scenarios
        self.busy(False)
        columns = ['name', 'status', 'support_changed', 'observed_total_m3', 'model_total_m3',
            'total_bias_m3', 'observed_delta_m3', 'bias_delta_m3', 'observed_gross_turnover_m3',
            'observed_cancellation_fraction', 'observed_spatial_std_change_m',
            'bias_lower_95_m3', 'bias_upper_95_m3', 'bias_exceeds_survey_error_95']
        self.populate(self.summary_table, report.summary.reindex(columns=columns))
        draw_sensitivity(self.sensitivity_figure, report)
        self.sensitivity_canvas.draw_idle()
        self.scenario.blockSignals(True)
        self.scenario.clear()
        self.scenario.addItems(report.summary.name.tolist())
        self.scenario.setCurrentIndex(self.scenario.count()-1)
        self.scenario.blockSignals(False)
        self.select_scenario(self.scenario.currentText())

    def select_scenario(self, name):
        if self.exploration is None:
            return
        if name == 'Reference':
            self.result = self.reference
            self.draw()
            self.describe(name, self.exploration.summary.iloc[0])
            return
        _, result, _ = next(row for row in self.exploration.scenarios if row[0] == name)
        if result is None:
            self.result = self.reference
            self.draw()
            reason = self.exploration.summary.loc[self.exploration.summary.name == name, 'error'].iloc[0]
            self.message.setPlainText(f'{name} unavailable: {reason}\nDisplaying the reference. Failed scenarios remain in the exported audit.')
        else:
            self.result = result
            self.draw()
            self.describe(name, self.exploration.summary.loc[self.exploration.summary.name == name].iloc[0])

    def error(self, error):
        self.busy(False)
        self.message.setPlainText(str(error))

    @staticmethod
    def populate(table, frame):
        visible = frame.head(2000)
        table.setRowCount(len(visible))
        table.setColumnCount(len(frame.columns))
        table.setHorizontalHeaderLabels(list(frame.columns))
        for i, values in enumerate(visible.itertuples(index=False, name=None)):
            for j, value in enumerate(values):
                text = 'undefined' if pd.isna(value) else f'{value:.6g}' if isinstance(value, float) else str(value)
                table.setItem(i, j, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        table.setToolTip(f'Showing {len(visible)} / {len(frame)} rows. Exports contain every row.')

    def draw(self, *_):
        xs = self.section.currentText()
        available = self.result.sections.xs_id.tolist()
        if [self.section.itemText(i) for i in range(self.section.count())] != available:
            self.section.blockSignals(True)
            self.section.clear()
            self.section.addItems(available)
            if xs in available:
                self.section.setCurrentText(xs)
            self.section.blockSignals(False)
            xs = self.section.currentText()
        draw_calculation_audit(self.figure, self.result, xs,
            self.reference if self.result is not self.reference else None, self.cumulative.currentData())
        draw_variability(self.variability_figure, self.result)
        self.canvas.draw_idle()
        self.variability_canvas.draw_idle()
        self.populate(self.lateral_table, self.result.lateral_audit[self.result.lateral_audit.xs_id == xs])
        self.populate(self.reach_table, self.result.intervals)
        self.populate(self.section_table, self.result.sections)
        row = self.result.sections.set_index('xs_id').loc[xs]
        self.calculation_text.setText(
            f'XS {xs} • accepted width {row.effective_width_m:,.3f} m • control length {row.control_length_m:,.3f} m\n'
            f'Model ΔA {row.model_area_change_m2:,.3f} m² × {row.control_length_m:,.3f} m = '
            f'{row.model_local_control_volume_m3:,.3f} m³; '
            f'observed ΔA {row.observed_area_change_m2:,.3f} m² × {row.control_length_m:,.3f} m = '
            f'{row.observed_local_control_volume_m3:,.3f} m³.\n'
            f'Observed node sum {row.observed_cumulative_m3:,.3f} m³; completed-reach prefix '
            f'{row.observed_interval_prefix_m3:,.3f} m³ (segment {int(row.segment_id)}).')

    def describe(self, name, row=None):
        m = self.result.metrics
        text = (f'Displaying {name}. Model / observed net: {m["model_total_m3"]:,.1f} / {m["observed_total_m3"]:,.1f} m³; '
                f'bias {m["total_bias_m3"]:,.1f} m³.\n'
                f'Observed gross erosion / deposition: {m["observed_gross_erosion_m3"]:,.1f} / '
                f'{m["observed_gross_deposition_m3"]:,.1f} m³; '
                f'spatial change std {m["observed_spatial_std_change_m"]:.3f} m.\n')
        if row is not None:
            if row.support_changed:
                text += 'Footprint changed: total differences combine estimator effects and changed coverage.\n'
            if pd.notna(row.bias_lower_95_m3):
                text += f'Conditional bias interval: [{row.bias_lower_95_m3:,.1f}, {row.bias_upper_95_m3:,.1f}] m³ (survey error only; model treated as exact).\n'
            else:
                text += 'No survey uncertainty supplied; statistical significance is undetermined.\n'
        text += 'Knobs describe the next experiment; uncertainty assumptions apply to all summary rows. Tables show up to 2,000 rows; exports contain all rows.'
        self.message.setPlainText(text)

    def export_specs(self):
        import json
        path, _ = QFileDialog.getSaveFileName(self, 'Save reproducible sensitivity scenarios', '', 'JSON (*.json)')
        if path:
            from pathlib import Path
            try:
                Path(path).write_text(json.dumps({'scenarios': self.scenarios, 'uncertainty': self.exploration.uncertainty},
                    indent=2, allow_nan=False)+'\n', encoding='utf-8')
            except (OSError, ValueError) as exc:
                self.error(exc)

    def export(self):
        directory = QFileDialog.getExistingDirectory(self, 'Export sensitivity and calculation audits')
        if directory:
            self.busy(True)
            report = self.exploration
            self.workers.submit('export', lambda: export_sensitivity(report, self.provenance, directory),
                                self.exported, self.error)

    def exported(self, path):
        self.busy(False)
        self.message.append(f'Exported complete calculation ledgers and scenarios to {path}')

    def closeEvent(self, event):
        self._closing = True
        self._cancel.set()
        if not self.workers.idle():
            event.ignore()
            QTimer.singleShot(100, self.close)
        else:
            event.accept()
