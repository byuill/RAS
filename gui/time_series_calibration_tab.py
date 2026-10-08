"""Measured and rating-derived sediment time-series comparisons."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from analysis.time_series_calibration import build_comparison, comparison_statistics
from core.io import atomic_text, atomic_writer
from gui.calibration_tab import CalibrationTab, KINDS, STAT_ROWS, VARS
from gui.mpl_canvas import MplCanvas
from plotting.time_series_calibration import draw_time_series_calibration
from sediment.units import convert, M3_PER_CFS

logger = logging.getLogger(__name__)

EXTRA_STATS = [
    ('median_error', 'Median error', '{:.4g}'),
    ('nrmse_pct', 'RMSE / |mean reference| (%)', '{:.2f}'),
    ('kge', 'Kling-Gupta efficiency (KGE)', '{:.3f}'),
    ('r_squared_pearson', 'Squared Pearson r', '{:.3f}'),
    ('scale_model_to_reference', 'Least-squares model multiplier', '{:.4g}'),
]


def _json_safe(value):
    """Represent undefined diagnostics as JSON null, not nonstandard NaN tokens."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


class TimeSeriesCalibrationTab(CalibrationTab):
    """Share date/group/observation lifecycle helpers with the existing calibration tab."""

    def __init__(self, settings=None, parent=None):
        QWidget.__init__(self, parent)
        self._mds = self._du = self._xs_index = self._obs = None
        self._paired = self._result = None
        self._context = {}
        self._manual_points = []
        self._curve_context = None
        self._threshold_initialized = False
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.combo_var = QComboBox()
        self.combo_var.addItems(['Sediment Concentration', 'Sediment Flux'])
        self.combo_var.setToolTip('Sediment Flux is the sediment load rate, displayed in the configured units (short tons/day by default).')
        self.combo_group = QComboBox()
        self.combo_group.setMinimumContentsLength(20)
        self.combo_group.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_display = QComboBox()
        self.combo_display.addItem('Measured points', 'points')
        self.combo_display.addItem('Rating-derived series', 'rating')
        self.combo_display.addItem('Points and rating series', 'both')
        self.combo_display.setCurrentIndex(2)
        self.chk_log = QCheckBox('Log sediment axis')
        for label, widget in [('Quantity:', self.combo_var), ('Group:', self.combo_group), ('Display:', self.combo_display)]:
            row.addWidget(QLabel(label)); row.addWidget(widget)
        row.addWidget(self.chk_log); row.addStretch()
        layout.addLayout(row)

        row = QHBoxLayout()
        self.combo_function = QComboBox()
        for label, value in [('Linear', 'linear'), ('Power law', 'power'), ('Logarithmic', 'logarithmic'), ('Polynomial', 'polynomial')]:
            self.combo_function.addItem(label, value)
        self.combo_function.setCurrentIndex(1)
        self.spin_degree = QSpinBox(); self.spin_degree.setRange(1, 5); self.spin_degree.setValue(2)
        self.combo_driver = QComboBox()
        self.combo_driver.addItem('Observed discharge', 'observed')
        self.combo_driver.addItem('Model discharge', 'model')
        self.combo_driver.setToolTip('The function is always fitted to same-record observed discharge and sediment. Model discharge produces a reference conditional on simulated hydraulics.')
        self.chk_smear = QCheckBox('Power-law bias correction')
        self.chk_smear.setToolTip('Duan smearing: multiply log-regression predictions by mean(exp(log residual)).')
        self.chk_extrapolate = QCheckBox('Allow discharge extrapolation')
        self.chk_extrapolate.setToolTip('Permit predictions outside the sampled discharge range; time extrapolation remains disabled.')
        for label, widget in [('Function:', self.combo_function), ('Degree:', self.spin_degree), ('Series driver:', self.combo_driver)]:
            row.addWidget(QLabel(label)); row.addWidget(widget)
        row.addWidget(self.chk_smear); row.addWidget(self.chk_extrapolate); row.addStretch()
        layout.addLayout(row)

        row = QHBoxLayout()
        self.date_start, self.date_end = QDateEdit(), QDateEdit()
        for edit in (self.date_start, self.date_end):
            edit.setCalendarPopup(True); edit.setDisplayFormat('yyyy-MM-dd')
        self.btn_full = QPushButton('Full Record')
        row.addWidget(QLabel('From:')); row.addWidget(self.date_start)
        row.addWidget(QLabel('To:')); row.addWidget(self.date_end); row.addWidget(self.btn_full)
        self.kind_checks = {}
        row.addWidget(QLabel('Use:'))
        for label in KINDS:
            check = QCheckBox(label); check.setChecked(True)
            self.kind_checks[label] = check; row.addWidget(check)
        row.addStretch()
        self.btn_export = QPushButton('Export comparison CSV…'); self.btn_export.setEnabled(False)
        row.addWidget(self.btn_export)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItem('Interpolate in time', 'interpolate')
        self.combo_mode.addItem('Nearest model step', 'nearest')
        self.spin_gap = QDoubleSpinBox(); self.spin_gap.setRange(1, 720)
        self.spin_gap.setValue(float(getattr(settings, 'pairing_max_gap_hours', 36)))
        self.spin_gap.setSuffix(' h')
        self.spin_gap.setToolTip('Maximum model-step spacing for interpolation; nearest tolerance is half this value. Also limits gaps in the observed hydrograph.')
        self.spin_offset = QDoubleSpinBox(); self.spin_offset.setRange(-48, 48)
        self.spin_offset.setSingleStep(.5); self.spin_offset.setSuffix(' h')
        self.spin_offset.setToolTip('Added to the observation clock. Points, fitting window and observed discharge then use model time.')
        for label, widget in [('Sample pairing:', self.combo_mode), ('Max gap:', self.spin_gap), ('Observation clock offset:', self.spin_offset)]:
            row.addWidget(QLabel(label)); row.addWidget(widget)
        row.addStretch(); layout.addLayout(row)

        row = QHBoxLayout()
        self.spin_low_q = QDoubleSpinBox(); self.spin_low_q.setRange(0, 1e9)
        self.spin_low_q.setDecimals(0); self.spin_low_q.setValue(300000)
        self.lbl_low_q_unit = QLabel('cfs')
        self.btn_low_q = QPushButton('Exclude low-Q measurements'); self.btn_low_q.setCheckable(True)
        self.btn_low_q.setToolTip('Exclude registered Q below the threshold from fitting and sample metrics in this tab. Unknown Q stays available for concentration comparisons. Click again to restore.')
        self.combo_fit_source = QComboBox()
        self.combo_fit_source.addItem('Observed measurements', 'observed')
        self.combo_fit_source.addItem('Drawn control points', 'manual')
        self.btn_draw = QPushButton('Draw points'); self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip('Click the observed rating-curve plot to add positive-discharge control points. Turn off the toolbar pan/zoom mode first.')
        self.btn_undo_point = QPushButton('Undo point')
        self.btn_clear_points = QPushButton('Clear points')
        for label, widget in [('Low-Q threshold:', self.spin_low_q), ('Fit to:', self.combo_fit_source)]:
            row.addWidget(QLabel(label)); row.addWidget(widget)
            if widget is self.spin_low_q: row.addWidget(self.lbl_low_q_unit); row.addWidget(self.btn_low_q)
        for widget in (self.btn_draw, self.btn_undo_point, self.btn_clear_points): row.addWidget(widget)
        row.addStretch(); layout.addLayout(row)

        self.lbl_status = QLabel('Load a model and observations on the Observations tab.')
        self.lbl_status.setWordWrap(True); layout.addWidget(self.lbl_status)
        self.lbl_fit = QLabel('Rating functions use observed discharge and sediment from the same record.')
        self.lbl_fit.setWordWrap(True); layout.addWidget(self.lbl_fit)
        split = QSplitter(Qt.Horizontal)
        self.canvas = MplCanvas(self); split.addWidget(self.canvas)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Statistic', 'Measured points', 'Rating reference'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumWidth(380)
        self.table.setToolTip('Errors are model minus reference. Rating-reference metrics compare reconstructed estimates, not additional measured samples. The suggested multiplier minimizes squared errors and is not applied to the solver.')
        split.addWidget(self.table); split.setStretchFactor(0, 3); split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        for combo in (self.combo_var, self.combo_group, self.combo_mode, self.combo_driver):
            combo.currentIndexChanged.connect(self._recompute)
        for combo in (self.combo_function, self.combo_display):
            combo.currentIndexChanged.connect(self._options_changed)
        for spin in (self.spin_gap, self.spin_offset, self.spin_degree):
            spin.valueChanged.connect(self._recompute)
        for edit in (self.date_start, self.date_end):
            edit.dateChanged.connect(self._recompute)
        for check in [self.chk_log, self.chk_smear, self.chk_extrapolate, *self.kind_checks.values()]:
            check.toggled.connect(self._recompute)
        self.btn_full.clicked.connect(self._full_record)
        self.btn_export.clicked.connect(self._export)
        self.btn_low_q.toggled.connect(self._low_flow_changed)
        self.spin_low_q.valueChanged.connect(self._recompute)
        self.combo_fit_source.currentIndexChanged.connect(self._recompute)
        self.btn_draw.toggled.connect(self._drawing_changed)
        self.btn_undo_point.clicked.connect(self._undo_point)
        self.btn_clear_points.clicked.connect(self._clear_points)
        self.canvas.canvas.mpl_connect('button_press_event', self._on_plot_click)
        self._options_changed()

    def refresh(self, mds, du, xs_index):
        # Only groups with a measured counterpart can be calibrated here.
        if self._mds is not mds:
            self.combo_group.blockSignals(True); self.combo_group.clear()
            for group in mds.groups():
                if group.key in ('total', 'sand', 'fines'):
                    self.combo_group.addItem(group.label, group.key)
                    self.combo_group.setItemData(self.combo_group.count()-1, group.description, Qt.ToolTipRole)
            self.combo_group.blockSignals(False)
            self._mds, self._du, self._xs_index = mds, du, xs_index
            self._full_record(recompute=False)
        else:
            self._du, self._xs_index = du, xs_index
        if not self._threshold_initialized:
            self.spin_low_q.blockSignals(True)
            self.spin_low_q.setValue(float(du.convert(300000*M3_PER_CFS, 'discharge')))
            self.spin_low_q.blockSignals(False)
            self.lbl_low_q_unit.setText(du.label('discharge'))
            self._threshold_initialized = True
        self._recompute()

    def set_observations(self, obs):
        if self._obs is not obs:
            self._reset_manual()
        super().set_observations(obs)

    def _reset_manual(self):
        self._manual_points = []
        self.combo_fit_source.blockSignals(True); self.combo_fit_source.setCurrentIndex(0)
        self.combo_fit_source.blockSignals(False)
        self.btn_draw.blockSignals(True); self.btn_draw.setChecked(False); self.btn_draw.blockSignals(False)

    def _low_flow_changed(self, checked):
        self.btn_low_q.setText('Restore low-Q measurements' if checked else 'Exclude low-Q measurements')
        self._recompute()

    def _drawing_changed(self, checked):
        if checked:
            self.combo_display.setCurrentIndex(self.combo_display.findData('both'))
            self.combo_fit_source.setCurrentIndex(self.combo_fit_source.findData('manual'))
            self.lbl_status.setText('Click the rating plot to add control points; at least two distinct Q values are needed (degree+1 for a polynomial).')

    def _on_plot_click(self, event):
        if not self.btn_draw.isChecked() or self._du is None or self.canvas.toolbar.mode:
            return
        axes = self.canvas.figure.axes
        if len(axes) != 3 or event.inaxes is not axes[2] or event.button != 1:
            return
        if event.xdata is None or event.ydata is None or not np.isfinite([event.xdata, event.ydata]).all():
            return
        quantity = VARS[self.combo_var.currentText()][1]
        q = float(convert(event.xdata, self._du.unit('discharge'), 'm3/s'))
        y = float(convert(event.ydata, self._du.unit(quantity), 'mg/L' if quantity == 'concentration' else 'kg/s'))
        if q <= 0 or y < 0: return
        self._manual_points.append((q, y)); self._recompute()

    def _undo_point(self):
        if self._manual_points: self._manual_points.pop()
        self._recompute()

    def _clear_points(self):
        self._manual_points = []; self._recompute()

    def _options_changed(self, *_):
        enabled = self.combo_display.currentData() != 'points'
        for widget in (self.combo_function, self.combo_driver, self.chk_extrapolate):
            widget.setEnabled(enabled)
        self.spin_degree.setEnabled(enabled and self.combo_function.currentData() == 'polynomial')
        self.chk_smear.setEnabled(enabled and self.combo_function.currentData() == 'power')
        self._recompute()

    def _show_message(self, message):
        self._result = None
        self._context = {}
        self.lbl_status.setText(message)
        self.lbl_fit.setText('')
        super()._show_message(message)

    def _recompute(self, *_):
        if self._mds is None or self._xs_index is None:
            return
        if self._obs is None or self._obs.df.empty:
            self._show_message('No observations loaded. Import a file or load a station on the Observations tab.')
            return
        kinds = self._selected_kinds()
        if not kinds:
            self._show_message('Select at least one observation type.'); return
        start, end = pd.Timestamp(self.date_start.date().toPython()), pd.Timestamp(self.date_end.date().toPython())
        if start > end:
            self._show_message('The start date must be on or before the end date.'); return
        col, quantity = VARS[self.combo_var.currentText()]
        group = self.combo_group.currentData() or 'total'
        context = (id(self._mds), self._xs_index, col, group)
        if self._curve_context != context:
            self._reset_manual(); self._curve_context = context
        display = self.combo_display.currentData()
        try:
            frame = self._mds.frame(self._xs_index, group, self._mds.rouse_cfg)
            result = build_comparison(frame.df, self._obs.df, col, group, kinds, start, end,
                self.combo_mode.currentData(), self.spin_gap.value(), self.spin_offset.value(),
                self.combo_function.currentData(), self.spin_degree.value(), self.combo_driver.currentData(),
                self.chk_extrapolate.isChecked(), self.chk_smear.isChecked(), display != 'points',
                float(convert(self.spin_low_q.value(), self._du.unit('discharge'), 'm3/s')) if self.btn_low_q.isChecked() else None,
                self._manual_points if self.combo_fit_source.currentData() == 'manual' else None)
            if result.series.empty:
                self._show_message('No model output in the selected date range.'); return
            measured = comparison_statistics(self._du.convert(result.samples.obs.to_numpy(), quantity),
                                             self._du.convert(result.samples['mod'].to_numpy(), quantity))
            rating = comparison_statistics(self._du.convert(result.series.reference.to_numpy(), quantity),
                                           self._du.convert(result.series['mod'].to_numpy(), quantity))
            label = 'Sediment concentration' if col == 'Conc' else 'Sediment load'
            draw_time_series_calibration(self.canvas.figure, result, quantity, label, self._du, display,
                                         self.chk_log.isChecked(), f'{label}: {frame.meta["sediment_group_label"]} at {frame.meta["xs_label"]}',
                                         self.chk_extrapolate.isChecked(), self.chk_smear.isChecked(), self._manual_points)
            self.canvas.draw()
            self._fill_comparison_stats(measured, rating, self._du.label(quantity))
            fit_meta = result.fit.summary() if result.fit else None
            if fit_meta:
                canonical_y = 'mg/L' if col == 'Conc' else 'kg/s'
                text = (f'{self.combo_function.currentText()} fit: {result.fit.n_used} samples; '
                        f'R² (original space)={result.fit.r2:.3g}; fit RMSE (before bias correction)='
                        f'{float(self._du.convert(result.fit.rmse, quantity)):.4g} {self._du.label(quantity)}. '
                        f'{fit_meta["equation_canonical_units"]} (Q in m³/s, y in {canonical_y}).')
                if result.fit.form == 'power':
                    text += f' Log-space R²={result.fit.r2_log:.3g}; smearing factor={result.fit.smearing_factor:.4g}'
                    text += ' (applied to predictions).' if self.chk_smear.isChecked() else ' (not applied).'
                self.lbl_fit.setText(text)
                if self.combo_fit_source.currentData() == 'manual':
                    self.lbl_fit.setText('MANUAL CONTROL-POINT FIT (not measured-data fit quality). '+text)
            else:
                self.lbl_fit.setText('Rating fit not requested.' if display == 'points' else 'No usable rating fit; measured pairs remain available.')
            finite_obs = np.isfinite(result.samples.obs.to_numpy())
            status = f'{measured["n_pairs"]}/{finite_obs.sum()} measured values paired; {rating["n_pairs"]}/{len(result.series)} rating-reference steps compared. '
            if 'daily' in kinds and (self._obs.df.kind == 'daily').any():
                status += 'Daily observations are compared at their timestamp, not to a daily model mean. '
            if self.chk_log.isChecked():
                status += 'Log plots omit values ≤0; statistics retain all finite pairs. '
            status += ' '.join(result.notes + frame.meta.get('warnings', []))
            self.lbl_status.setText(status)
            self._result = result
            self._paired = result.samples[np.isfinite(result.samples.obs) & np.isfinite(result.samples['mod'])]
            self._context = {'model': frame.meta, 'station': self._obs.station_name,
                'observation_sources': self._obs.sources, 'observation_derivations': self._obs.derivations,
                'observation_qaqc': self._obs.qaqc,
                'variable': col, 'group': group, 'display_unit': self._du.unit(quantity),
                'start_model_clock': str(start), 'end_model_clock': str(end), 'observation_types': kinds,
                'pairing_mode': self.combo_mode.currentData(), 'max_gap_hours': self.spin_gap.value(),
                'observation_clock_offset_hours': self.spin_offset.value(), 'display': display,
                'rating_driver': self.combo_driver.currentData(), 'allow_discharge_extrapolation': self.chk_extrapolate.isChecked(),
                'power_law_smearing_applied': result.fit is not None and result.fit.form == 'power' and self.chk_smear.isChecked(),
                'fit': fit_meta, 'measured_statistics': measured, 'rating_reference_statistics': rating,
                'rating_fit_source': self.combo_fit_source.currentData(), 'manual_points_canonical': list(self._manual_points),
                'low_flow_filter_enabled': self.btn_low_q.isChecked(),
                'low_flow_threshold_m3s': float(convert(self.spin_low_q.value(), self._du.unit('discharge'), 'm3/s')),
                'metric_weighting': 'Each finite pair/step has equal weight; reconstructed steps are not independent measurements.',
                'notes': result.notes}
            self.btn_export.setEnabled(True)
        except Exception as exc:
            logger.exception('Time-series calibration failed')
            self._show_message(f'Cannot compare: {exc}')

    def _fill_comparison_stats(self, measured, rating, unit):
        rows = STAT_ROWS + EXTRA_STATS
        self.table.setRowCount(len(rows))
        dimensioned = {'mean_obs', 'mean_mod', 'bias', 'mae', 'rmse', 'median_error'}
        for r, (key, label, fmt) in enumerate(rows):
            label = {'mean_obs': 'Mean reference', 'mean_mod': 'Mean model', 'bias': 'Bias (model − reference)'}.get(key, label)
            label = f'{label} ({unit})' if key in dimensioned else label
            item = QTableWidgetItem(label); item.setToolTip(label)
            self.table.setItem(r, 0, item)
            for c, statistics in enumerate((measured, rating), 1):
                value = statistics.get(key, np.nan)
                text = fmt.format(value) if np.isfinite(value) else '—'
                item = QTableWidgetItem(text); item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)

    def _export(self):
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export time-series calibration', 'time_series_calibration.csv', 'CSV (*.csv)')
        if not path:
            return
        target = Path(path)
        samples_path = target.with_name(target.stem + '.samples.csv')
        meta_path = target.with_suffix('.meta.json')
        quantity = VARS[self.combo_var.currentText()][1]
        unit, q_unit = self._du.label(quantity), self._du.label('discharge')
        result = self._result
        series = pd.DataFrame({f'Model_{unit}': self._du.convert(result.series['mod'].to_numpy(), quantity),
            f'RatingReference_{unit}': self._du.convert(result.series.reference.to_numpy(), quantity),
            f'ModelMinusReference_{unit}': self._du.convert(result.series.residual.to_numpy(), quantity),
            f'ModelDischarge_{q_unit}': self._du.convert(result.series.Q.to_numpy(), 'discharge'),
            f'RatingDriverDischarge_{q_unit}': self._du.convert(result.series.rating_q.to_numpy(), 'discharge')}, index=result.series.index)
        samples = pd.DataFrame({f'Observed_{unit}': self._du.convert(result.samples.obs.to_numpy(), quantity),
            f'Model_{unit}': self._du.convert(result.samples['mod'].to_numpy(), quantity),
            f'Residual_{unit}': self._du.convert(result.samples.residual.to_numpy(), quantity),
            f'ObservedDischarge_{q_unit}': self._du.convert(result.samples.Q.to_numpy(), 'discharge'),
            'ObservationDateTime': result.samples.index - pd.Timedelta(hours=self.spin_offset.value())}, index=result.samples.index)
        for column in ('q_is_proxy', 'q_method', 'q_sources', 'q_proxy_recipe', 'q_lag_hours',
                       'q_proxy_low_m3s', 'q_proxy_high_m3s', 'qaqc_excluded_fields'):
            if column in result.samples: samples[column] = result.samples[column].to_numpy()
        series.index.name = samples.index.name = 'ModelDateTime'
        try:
            metadata = json.dumps(_json_safe(self._context), indent=2, default=str, allow_nan=False)
            with atomic_writer(target) as stream:
                series.to_csv(stream)
            with atomic_writer(samples_path) as stream:
                samples.to_csv(stream)
            atomic_text(meta_path, metadata)
        except OSError as exc:
            self.lbl_status.setText(f'Export failed: {exc}'); return
        self.lbl_status.setText(f'Exported model/rating series to {target}, measured records to {samples_path.name}, and fit/metrics to {meta_path.name}.')
