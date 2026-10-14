"""Desktop workbench for reviewing daily Lower Mississippi flow scenarios."""
from dataclasses import fields
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSlider, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QHeaderView)

from gui.mpl_canvas import MplCanvas
from gui.workers import WorkerManager
from .engine import calculate_budget
from .export import dss_available, export_result
from .parameters import Parameters
from .plots import LABELS, draw_hydrographs, draw_network


CHOICES = {
    'input_reference': [('union_point', 'Union Point (pre-ORCC)'), ('tarbert', 'Tarbert Landing (post-ORCC)')],
    'orcc_mode': [('prescribed', 'Prescribed from input CSV'), ('calculated', 'Calculate from latitude-flow ratio')],
    'split_semantics': [('fraction', 'MMR / (MMR + Ohio) fraction'), ('ratio', 'MMR / Ohio ratio')],
    'split_sampling': [('monthly_mean', 'Historical monthly mean'), ('sample_year', 'Sample a historical seasonal year')],
    'upstream_balance': [('preserve', 'Preserve coefficients; report flow gap'), ('close_minor', 'Close budget using minor tributaries')],
    'spill_style': [('threshold', 'Bonnet Carré first, then Morganza'), ('ratio', 'Divide excess using ratios')],
}


class BoundaryWindow(QMainWindow):
    def __init__(self, input_path=None, parameters=None):
        super().__init__()
        self.setWindowTitle('Lower Mississippi · Boundary Condition Workbench')
        self.resize(1600, 1000)
        self.workers = WorkerManager(self)
        self.result = None
        self.dirty = True
        self._loading = True
        self.editors = {}
        self.base = Path(__file__).parent
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel('LOWER MISSISSIPPI  /  FLOW BOUNDARY CONDITIONS')
        title.setStyleSheet('font-size: 19px; font-weight: bold; color: #173e58; padding: 8px 0;')
        layout.addWidget(title)
        layout.addWidget(QLabel('Review empirical flow partitions, operating assumptions, and daily water budgets before exporting to HEC-RAS.'))
        self.input_edit = QLineEdit(str(input_path or self.base/'new_data_RF.csv'))
        self.split_edit = QLineEdit(str(self.base/'ohio_split_wyV2.csv'))
        self.stage_edit = QLineEdit()
        self.stage_edit.setPlaceholderText('Optional date,stage_ft CSV for DSS export; verify the model datum')
        paths = QFormLayout()
        for label, edit in [('Observed flows (cfs)', self.input_edit), ('MMR / Ohio seasonal splits', self.split_edit), ('Stage series (optional)', self.stage_edit)]:
            row = QHBoxLayout()
            browse = QPushButton('Browse…')
            browse.clicked.connect(lambda checked=False, e=edit: self._browse(e))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            paths.addRow(label, row)
            edit.textChanged.connect(self._mark_dirty)
        self.path_panel = QWidget()
        self.path_panel.setLayout(paths)
        layout.addWidget(self.path_panel)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.parameter_panel = QWidget()
        side = QVBoxLayout(self.parameter_panel)
        side.setContentsMargins(0, 6, 12, 0)
        side.addWidget(QLabel('SCENARIO PARAMETERS'))
        group_combo = QComboBox()
        groups = list(dict.fromkeys(f.metadata['group'] for f in fields(Parameters)))
        group_combo.addItems(groups)
        side.addWidget(group_combo)
        self.forms = QStackedWidget()
        for group in groups:
            body = QWidget()
            form = QFormLayout(body)
            form.setRowWrapPolicy(QFormLayout.WrapAllRows)
            form.setVerticalSpacing(12)
            for f in fields(Parameters):
                if f.metadata['group'] != group:
                    continue
                if isinstance(f.default, bool):
                    editor = QCheckBox('Enabled')
                    editor.toggled.connect(self._mark_dirty)
                elif f.name in CHOICES:
                    editor = QComboBox()
                    for value, label in CHOICES[f.name]:
                        editor.addItem(label, value)
                    editor.currentIndexChanged.connect(self._mark_dirty)
                elif isinstance(f.default, int):
                    editor = QSpinBox()
                    editor.setRange(int(f.metadata['low']), int(f.metadata['high']))
                    editor.valueChanged.connect(self._mark_dirty)
                else:
                    editor = QLineEdit()
                    editor.textChanged.connect(self._mark_dirty)
                editor.setToolTip(f.metadata['help'])
                label = QLabel(f.metadata['label'])
                label.setToolTip(f.metadata['help'])
                form.addRow(label, editor)
                help_label = QLabel(f.metadata['help'])
                help_label.setWordWrap(True)
                help_label.setStyleSheet('color: #60717e; font-size: 11px;')
                form.addRow(help_label)
                self.editors[f.name] = editor
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(body)
            self.forms.addWidget(scroll)
        group_combo.currentIndexChanged.connect(self.forms.setCurrentIndex)
        side.addWidget(self.forms, 1)
        actions = QHBoxLayout()
        self.load_button, self.save_button = QPushButton('Load scenario…'), QPushButton('Save scenario…')
        self.load_button.clicked.connect(self._load_scenario)
        self.save_button.clicked.connect(self._save_scenario)
        actions.addWidget(self.load_button)
        actions.addWidget(self.save_button)
        side.addLayout(actions)
        reset = QPushButton('Restore historical defaults')
        reset.clicked.connect(lambda: self.set_parameters(Parameters()))
        side.addWidget(reset)
        self.calculate_button = QPushButton('Calculate & check budget')
        self.calculate_button.setStyleSheet('background: #206688; color: white; padding: 10px; font-weight: bold;')
        self.calculate_button.clicked.connect(self.calculate)
        side.addWidget(self.calculate_button)
        self.parameter_panel.setMinimumWidth(345)
        self.parameter_panel.setMaximumWidth(480)
        splitter.addWidget(self.parameter_panel)
        right = QWidget()
        review = QVBoxLayout(right)
        self.summary_label = QLabel('Load the included calibration and calculate to inspect the budget.')
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumHeight(78)
        self.summary_label.setStyleSheet('background: #edf4f8; padding: 12px; border-radius: 5px; color: #173e58;')
        review.addWidget(self.summary_label)
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel('Inspect day'))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat('dd MMM yyyy')
        self.date_edit.dateChanged.connect(self._date_changed)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._day_changed)
        date_row.addWidget(self.date_edit)
        date_row.addWidget(self.slider, 1)
        review.addLayout(date_row)
        self.tabs = QTabWidget()
        self.network = MplCanvas(width=13, height=8)
        self.hydrographs = MplCanvas(width=12, height=8)
        self.ledger = QTableWidget(0, 3)
        self.ledger.setHorizontalHeaderLabels(['Flow / ledger entry', 'Value', 'Units'])
        self.ledger.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ledger.setEditTriggers(QTableWidget.NoEditTriggers)
        self.qaqc = QTextEdit()
        self.qaqc.setReadOnly(True)
        self.tabs.addTab(self.network, 'River flow budget')
        self.tabs.addTab(self.hydrographs, 'Hydrographs & residuals')
        self.tabs.addTab(self.ledger, 'Daily ledger')
        self.tabs.addTab(self.qaqc, 'QA/QC & assumptions')
        review.addWidget(self.tabs, 1)
        self.export_button = QPushButton('Export checked run…')
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        self.include_dss = QCheckBox('Include HEC-DSS')
        self.include_dss.setEnabled(dss_available())
        self.include_dss.setChecked(dss_available())
        self.include_dss.setToolTip('Optional pydsstools dependency; each exported record is read back and checked.')
        self.scenario_edit = QLineEdit('Cal')
        self.scenario_edit.setMaximumWidth(160)
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel('DSS scenario'))
        export_row.addWidget(self.scenario_edit)
        export_row.addWidget(self.include_dss)
        export_row.addStretch()
        export_row.addWidget(self.export_button)
        review.addLayout(export_row)
        splitter.addWidget(right)
        splitter.setSizes([370, 1200])
        self.date_edit.setEnabled(False)
        self.slider.setEnabled(False)
        self.statusBar().showMessage('Ready to calculate. Existing input and DSS files remain untouched.')
        self.editors['water_year'].toggled.connect(self._year_type_changed)
        self.set_parameters(parameters or Parameters())
        self._loading = False
        # Draw selected-day network only after slider dragging pauses.
        self.day_timer = QTimer(self)
        self.day_timer.setSingleShot(True)
        self.day_timer.setInterval(80)
        self.day_timer.timeout.connect(self._render_day)
        QTimer.singleShot(0, self.calculate)

    def _browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, 'Select daily CSV', str(self.base), 'CSV (*.csv);;All files (*)')
        if path:
            edit.setText(path)

    def _year_type_changed(self, water_year):
        if self._loading:
            return
        if Path(self.split_edit.text()).resolve() in {
            (self.base/'ohio_split_wyV2.csv').resolve(), (self.base/'ohio_split_cy.csv').resolve()}:
            self.split_edit.setText(str(self.base/('ohio_split_wyV2.csv' if water_year else 'ohio_split_cy.csv')))
            editor = self.editors['split_semantics']
            editor.setCurrentIndex(editor.findData('fraction' if water_year else 'ratio'))

    def parameters(self):
        values = {}
        for name, editor in self.editors.items():
            if isinstance(editor, QCheckBox):
                values[name] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                values[name] = editor.currentData()
            elif isinstance(editor, QSpinBox):
                values[name] = editor.value()
            else:
                try:
                    values[name] = (tuple(float(v.strip()) for v in editor.text().split(','))
                                    if name == 'bp_return_weights' else float(editor.text()))
                except ValueError as exc:
                    raise ValueError(f'{name}: enter a finite number') from exc
        return Parameters(**values).validate()

    def set_parameters(self, p):
        p.validate()
        previous = self._loading
        self._loading = True
        for name, editor in self.editors.items():
            value = getattr(p, name)
            if isinstance(editor, QCheckBox):
                editor.setChecked(value)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(editor.findData(value))
            elif isinstance(editor, QSpinBox):
                editor.setValue(value)
            else:
                editor.setText(', '.join(format(v, '.12g') for v in value) if name == 'bp_return_weights' else format(value, '.12g'))
        self._loading = previous
        if Path(self.split_edit.text()).resolve() in {
            (self.base/'ohio_split_wyV2.csv').resolve(), (self.base/'ohio_split_cy.csv').resolve()}:
            self.split_edit.setText(str(self.base/('ohio_split_wyV2.csv' if p.water_year else 'ohio_split_cy.csv')))
        self._mark_dirty()

    def _mark_dirty(self, *args):
        if self._loading:
            return
        self.dirty = True
        self.export_button.setEnabled(False)
        self.summary_label.setText('Inputs changed. Click Calculate & check budget to refresh the displayed results.')

    def _busy(self, busy):
        self.parameter_panel.setEnabled(not busy)
        self.path_panel.setEnabled(not busy)
        self.date_edit.setEnabled(not busy and self.result is not None)
        self.slider.setEnabled(not busy and self.result is not None)
        if busy and hasattr(self, 'day_timer'):
            self.day_timer.stop()
        self.export_button.setEnabled(not busy and self.result is not None and not self.dirty)

    def calculate(self):
        if not self.workers.idle():
            return
        try:
            p = self.parameters()
            path, split = self.input_edit.text(), self.split_edit.text()
            if not path or not split:
                raise ValueError('Select an input flow CSV and monthly split CSV')
        except Exception as exc:
            self._failed(exc)
            return
        self._busy(True)
        self.statusBar().showMessage('Calculating daily boundaries and checking water budgets…')
        self.workers.submit('budget', lambda: calculate_budget(path, split, p), self._calculated, self._failed)

    def _calculated(self, result):
        self.result, self.dirty = result, False
        self._busy(False)
        self.date_edit.setEnabled(True)
        self.slider.setEnabled(True)
        f = result.flows
        with QSignalBlocker(self.slider), QSignalBlocker(self.date_edit):
            self.slider.setRange(0, len(f)-1)
            self.slider.setValue(0)
            self.date_edit.setDateRange(QDate(f.date.iloc[0].date()), QDate(f.date.iloc[-1].date()))
            self.date_edit.setDate(QDate(f.date.iloc[0].date()))
        residual = result.summary['max_abs_residual_cfs']
        gap = residual['upstream_residual_cfs']
        self.summary_label.setText(f'{len(f):,} daily records  ·  {result.summary["start"]} to {result.summary["end"]}\n'
            f'ORCC / latitude / lower river close within {max(residual[k] for k in ["orcc_residual_cfs", "latitude_residual_cfs", "lower_residual_cfs"]):.2g} cfs. '
            f'Maximum upstream gap: {gap:,.0f} cfs.  '
            f'ORCC adjusted on {result.summary["issue_counts"].get("orcc_adjusted", 0)} days.')
        self.qaqc.setPlainText(self._report_text(result))
        draw_hydrographs(self.hydrographs.figure, result)
        self.hydrographs.draw_idle()
        self._render_day()
        self.statusBar().showMessage('Calculated. Review the regional residual and model boundary roles before export.')

    def _report_text(self, result):
        s = result.summary
        lines = ['Daily budget checks', '']
        for key, value in s['max_abs_residual_cfs'].items():
            lines.append(f'{key}: max |residual| = {value:,.6f} cfs')
        lines += ['', 'Recorded conditions (days)']
        for code, count in s['issue_counts'].items():
            messages = result.issues.loc[result.issues.code == code, 'message']
            lines.append(f'{code}: {count:,} — {messages.iloc[0]}')
        lines += ['', 'Floodway volume ledger (ft³)',
            f'Diverted: {s["floodway_diverted_ft3"]:,.0f}; returned: {s["floodway_returned_ft3"]:,.0f}',
            f'Loss: {s["floodway_loss_ft3"]:,.0f}; scheduled return after run: {s["floodway_tail_ft3"]:,.0f}',
            '', 'Assumptions'] + s['assumptions']
        lines += ['', 'Boundary mapping',
            'Minor_Tribs is an aggregate diagnostic: use Hatchie + Arkansas + Yazoo, or the aggregate, once.',
            'Terminal_Passes is the magnitude of EACH of South Pass and Pass a Loutre, not their combined total.',
            'Southwest Pass and other terminal diagnostics require model-specific treatment at the downstream boundary.',
            'Red River is an external Atchafalaya source; do not add it as a Mississippi mainstem inflow.',
            'Input smoothing changes gauge forcing. Outputs are not independently filtered.',
            'Missing stage data is optional; no random stage series or datum assumption is created.']
        return '\n'.join(lines)

    def _day_changed(self, index):
        if self.result is None:
            return
        with QSignalBlocker(self.date_edit):
            self.date_edit.setDate(QDate(self.result.flows.date.iloc[index].date()))
        self.day_timer.start()

    def _date_changed(self, date):
        if self.result is not None:
            self.slider.setValue((pd.Timestamp(date.toPython())-self.result.flows.date.iloc[0]).days)

    def _render_day(self):
        if self.result is None:
            return
        index = self.slider.value()
        draw_network(self.network.figure, self.result, index)
        self.network.draw_idle()
        row = self.result.flows.iloc[index]
        self.ledger.setRowCount(len(row)-1)
        for i, (name, value) in enumerate(row.drop('date').items()):
            units = 'ft³' if name.endswith('_ft3') else 'state' if name in ['Rising_ID', 'head_constraint'] else 'fraction' if name == 'MMR_fraction' else 'cfs'
            self.ledger.setItem(i, 0, QTableWidgetItem(LABELS.get(name, name)))
            self.ledger.setItem(i, 1, QTableWidgetItem(f'{float(value):,.6g}'))
            self.ledger.setItem(i, 2, QTableWidgetItem(units))

    def _failed(self, exc):
        self._busy(False)
        self.statusBar().showMessage(f'Operation failed: {exc}')
        self.summary_label.setText(f'Operation failed: {exc}')
        QMessageBox.warning(self, 'Boundary condition workbench', str(exc))

    def _load_scenario(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load scenario parameters', str(self.base), 'JSON (*.json)')
        if path:
            try:
                self.set_parameters(Parameters.load(path))
            except Exception as exc:
                self._failed(exc)

    def _save_scenario(self):
        try:
            p = self.parameters()
            path, _ = QFileDialog.getSaveFileName(self, 'Save scenario parameters', 'scenario.json', 'JSON (*.json)')
            if path:
                p.save(path)
                self.statusBar().showMessage(f'Saved scenario: {path}')
        except Exception as exc:
            self._failed(exc)

    def _export(self):
        if self.result is None or self.dirty or not self.workers.idle():
            return
        parent = QFileDialog.getExistingDirectory(self, 'Export to a new run directory', str(self.base/'output'))
        if not parent:
            return
        result, scenario, stage = self.result, self.scenario_edit.text(), self.stage_edit.text() or None
        include_dss, index = self.include_dss.isChecked(), self.slider.value()
        self._busy(True)
        self.statusBar().showMessage('Exporting tables, plots, and optional DSS; verifying DSS records…')
        self.workers.submit('export', lambda: export_result(result, parent, scenario=scenario,
            include_dss=include_dss, stage=stage, index=index), self._exported, self._failed)

    def _exported(self, path):
        self._busy(False)
        self.statusBar().showMessage(f'Exported complete checked run: {path}')
        QMessageBox.information(self, 'Export complete', str(path))

    def closeEvent(self, event):
        if not self.workers.idle():
            self.statusBar().showMessage('Wait for the current calculation/export to finish before closing.')
            event.ignore()
        else:
            event.accept()
