"""Reversible survey QA/QC choices with original/used elevations side by side."""
import copy
import json

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget)

from .display_units import (FT_PER_M, customary_frame, customary_mapping, customary_header,
                            read_customary_spin, set_customary_spin)
from .qaqc import review_survey
from .workflow import export_survey_qaqc


class SurveyQaqcWindow(QMainWindow):
    def __init__(self, reviews, provenance, apply_options, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Survey QA/QC — review flags before excluding values')
        self.resize(1200, 950)
        self.reviews, self.provenance, self.apply_options = reviews, provenance, apply_options
        self.options = {name: copy.deepcopy(provenance['settings']['surveys'][name].get('qaqc', {})) for name in reviews}
        self.raw = {name: review.audit[['xs_id', 'u_m', 'original_z_m', 'source_nonfinite']].rename(
            columns={'original_z_m': 'z_m'}) for name, review in reviews.items()}
        self.survey, self.section = QComboBox(), QComboBox()
        self.survey.addItems(list(reviews))
        self.flags_only = QCheckBox('Show flagged/excluded only')
        self.flags_only.setChecked(True)
        self.exclude_flags = QCheckBox('Exclude elevation/spike/slope flags when applied')
        self.duplicate_policy = QComboBox()
        self.duplicate_policy.addItems(['error', 'mean', 'median'])
        self.spike_min = self._spin(0, 1000*FT_PER_M, FT_PER_M, FT_PER_M)
        self.low_enabled, self.high_enabled, self.slope_enabled = QCheckBox('Minimum elevation (ft)'), QCheckBox('Maximum elevation (ft)'), QCheckBox('Maximum lateral slope (ft/ft)')
        self.low, self.high, self.slope = self._spin(-1e6*FT_PER_M, 1e6*FT_PER_M, -100*FT_PER_M, FT_PER_M), self._spin(-1e6*FT_PER_M, 1e6*FT_PER_M, 100*FT_PER_M, FT_PER_M), self._spin(.001, 1000, 1)
        self.offset = self._spin(-100*FT_PER_M, 100*FT_PER_M, 0, FT_PER_M)
        self.evidence = QLineEdit()
        self.evidence.setPlaceholderText('Independent benchmark/datum evidence required for a correction')
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.figure = Figure(figsize=(10, 3), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.message = QTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(110)
        central, layout = QWidget(), QVBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)
        selectors = QHBoxLayout()
        for widget in (QLabel('Survey'), self.survey, QLabel('Cross section'), self.section, self.flags_only):
            selectors.addWidget(widget)
        layout.addLayout(selectors)
        controls = QFormLayout()
        for label, control in [('Duplicate station decision', self.duplicate_policy), ('Minimum spike deviation (ft)', self.spike_min),
                               (self.low_enabled, self.low), (self.high_enabled, self.high), (self.slope_enabled, self.slope),
                               ('Documented elevation correction (ft)', self.offset), ('Correction evidence', self.evidence)]:
            controls.addRow(label, control)
        layout.addLayout(controls)
        layout.addWidget(self.exclude_flags)
        actions = QHBoxLayout()
        self.preview_button = QPushButton('Review these limits')
        self.exclude_button = QPushButton('Exclude selected points')
        self.restore_button = QPushButton('Restore raw values and decisions')
        self.apply_button = QPushButton('Apply decisions to comparison')
        self.export_button = QPushButton('Export QA/QC audit')
        for button, callback in [(self.preview_button, self.preview), (self.exclude_button, self.exclude_selected),
                                 (self.restore_button, self.restore), (self.apply_button, self.apply),
                                 (self.export_button, self.export)]:
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.apply_button.setMinimumHeight(36)
        self.apply_button.setStyleSheet('QPushButton { font-weight: bold; padding: 6px; }')
        self.preview_button.setText('1  Preview limits')
        self.apply_button.setText('2  Apply reviewed decisions')
        layout.addWidget(QLabel('Flags do not prove errors. Missing/excluded values remain gaps; source surveys are never edited.'))
        layout.addWidget(self.table, 2)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.message)
        self.survey.currentTextChanged.connect(self.load_controls)
        self.section.currentTextChanged.connect(self.render)
        self.flags_only.toggled.connect(self.render)
        self.load_controls()

    @staticmethod
    def _spin(low, high, value, factor=1):
        control = QDoubleSpinBox()
        control.setRange(low, high)
        control.setDecimals(6)
        set_customary_spin(control, value/factor, factor)
        return control

    def load_controls(self, *_):
        name = self.survey.currentText()
        options = self.options[name]
        self.duplicate_policy.setCurrentText(options.get('duplicate_policy', 'error'))
        set_customary_spin(self.spike_min, options.get('spike_min_m', 1))
        self.exclude_flags.setChecked(options.get('exclude_flagged', False))
        set_customary_spin(self.offset, options.get('datum_correction_m', 0))
        self.evidence.setText(options.get('datum_correction_evidence', ''))
        for enabled, spin, key in [(self.low_enabled, self.low, 'elevation_min_m'),
                                   (self.high_enabled, self.high, 'elevation_max_m'),
                                   (self.slope_enabled, self.slope, 'max_slope_m_per_m')]:
            enabled.setChecked(key in options)
            if key in options:
                set_customary_spin(spin, options[key], 1 if key == 'max_slope_m_per_m' else FT_PER_M)
        self.section.blockSignals(True)
        self.section.clear()
        self.section.addItems(self.raw[name].xs_id.drop_duplicates().tolist())
        self.section.blockSignals(False)
        self.render()

    def collect_options(self):
        options = copy.deepcopy(self.options[self.survey.currentText()])
        options.update(duplicate_policy=self.duplicate_policy.currentText(), spike_min_m=read_customary_spin(self.spike_min),
                       exclude_flagged=self.exclude_flags.isChecked(), datum_correction_m=read_customary_spin(self.offset),
                       datum_correction_evidence=self.evidence.text())
        for enabled, spin, key in [(self.low_enabled, self.low, 'elevation_min_m'),
                                   (self.high_enabled, self.high, 'elevation_max_m'),
                                   (self.slope_enabled, self.slope, 'max_slope_m_per_m')]:
            options.pop(key, None)
            if enabled.isChecked():
                options[key] = read_customary_spin(spin, 1 if key == 'max_slope_m_per_m' else FT_PER_M)
        return options

    def preview(self):
        name = self.survey.currentText()
        try:
            options = self.collect_options()
            review = review_survey(self.raw[name], options,
                                  max_gap_m=self.provenance['settings'].get('integration', {}).get('max_gap_m', 25),
                                  allow_unresolved_duplicates=True)
            self.options[name], self.reviews[name] = options, review
            self.render()
            return True
        except Exception as exc:
            self.message.setPlainText(str(exc))
            return False

    def render(self, *_):
        review = self.reviews[self.survey.currentText()]
        rows = review.audit[review.audit.xs_id == self.section.currentText()]
        self.figure.clear()
        axis = self.figure.subplots()
        axis.plot(rows.u_m*FT_PER_M, rows.original_z_m*FT_PER_M, '.', label='Original elevations')
        axis.plot(rows.u_m*FT_PER_M, rows.used_z_m*FT_PER_M, '.', label='Used elevations')
        flags = rows[rows.flagged]
        axis.scatter(flags.u_m*FT_PER_M, flags.original_z_m*FT_PER_M, c='firebrick', marker='x', label='Review flags')
        axis.set(xlabel='Lateral station (ft)', ylabel='Elevation (ft)', title=self.section.currentText())
        axis.legend()
        self.canvas.draw_idle()
        visible = rows[rows.flagged | rows.excluded] if self.flags_only.isChecked() else rows
        self.visible = visible.head(2000)
        columns = ['xs_id', 'u_m', 'original_z_m', 'used_z_m', 'flag_reasons', 'excluded', 'manual_exclusion_reason']
        display = customary_frame(self.visible[columns])
        columns = list(display.columns)
        self.table.setRowCount(len(self.visible))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([customary_header(column) for column in columns])
        for i, (_, row) in enumerate(display.iterrows()):
            for j, column in enumerate(columns):
                self.table.setItem(i, j, QTableWidgetItem(str(row[column])))
        self.table.resizeColumnsToContents()
        self.message.setPlainText(json.dumps(customary_mapping(review.summary), indent=2)+f'\nShowing {len(self.visible)} of {len(visible)} matching rows. Export contains all rows.')

    def exclude_selected(self):
        options = self.collect_options()
        excluded = options.setdefault('excluded_points', [])
        for row in {index.row() for index in self.table.selectedIndexes()}:
            point = self.visible.iloc[row]
            choice = {'xs_id': point.xs_id, 'u_m': float(point.u_m), 'reason': 'Excluded after interactive survey QA/QC review'}
            if not any(p['xs_id'] == choice['xs_id'] and p['u_m'] == choice['u_m'] for p in excluded):
                excluded.append(choice)
        self.options[self.survey.currentText()] = options
        self.preview()

    def restore(self):
        name = self.survey.currentText()
        self.options[name] = {}
        self.reviews[name] = review_survey(self.raw[name],
                                         max_gap_m=self.provenance['settings'].get('integration', {}).get('max_gap_m', 25),
                                         allow_unresolved_duplicates=True)
        self.load_controls()

    def apply(self):
        if self.preview():
            try:
                self.apply_options(copy.deepcopy(self.options))
                self.message.append('Decisions applied to this session. Recompute comparisons; save a configuration copy to reuse them.')
            except Exception as exc:
                self.message.setPlainText(str(exc))

    def export(self):
        if not self.preview():
            return
        directory = QFileDialog.getExistingDirectory(self, 'Export complete survey QA/QC audit')
        if directory:
            try:
                provenance = copy.deepcopy(self.provenance)
                for name, options in self.options.items():
                    provenance['settings']['surveys'][name]['qaqc'] = options
                saved = export_survey_qaqc(self.reviews, provenance, directory)
                self.message.append(f'Exported to {saved}')
            except Exception as exc:
                self.message.setPlainText(str(exc))
