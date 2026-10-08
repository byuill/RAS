"""Calibration tab: pair HEC-RAS output with observations, report statistics and draw 1:1 / residual plots."""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from gui.mpl_canvas import MplCanvas

logger = logging.getLogger(__name__)

# label -> (model frame column, canonical quantity key)
VARS = {
    "Discharge": ("Q", "discharge"),
    "Stage": ("Stage", "length"),
    "Sediment Flux": ("Flux", "mass_flux"),
    "Sediment Concentration": ("Conc", "concentration"),
}
SEDIMENT_VARS = ("Sediment Flux", "Sediment Concentration")
KINDS = {"Samples": "sample", "Daily values": "daily", "CWMS": "cwms"}

STAT_ROWS = [
    ("n_pairs", "Pairs (n)", "{:d}"),
    ("mean_obs", "Mean observed", "{:.4g}"),
    ("mean_mod", "Mean modelled", "{:.4g}"),
    ("bias", "Bias (mod - obs)", "{:.4g}"),
    ("pbias_pct", "Percent bias (%)", "{:.2f}"),
    ("mae", "MAE", "{:.4g}"),
    ("rmse", "RMSE", "{:.4g}"),
    ("pearson_r", "Pearson r", "{:.3f}"),
    ("nse", "Nash-Sutcliffe (NSE)", "{:.3f}"),
    ("n_pairs_log", "Pairs with both > 0 (n)", "{:d}"),
    ("geometric_ratio", "Geometric mean ratio (mod/obs)", "{:.3f}"),
    ("log10_rmse", "RMSE of log10 ratio", "{:.3f}"),
    ("pearson_r_log", "Pearson r (log10)", "{:.3f}"),
]


class CalibrationTab(QWidget):
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self._mds = None
        self._du = None
        self._xs_index = None
        self._obs = None
        self._paired: pd.DataFrame | None = None
        self._context: dict = {}
        self._default_gap = float(getattr(settings, "pairing_max_gap_hours", 36.0))

        layout = QVBoxLayout(self)

        row1 = QHBoxLayout()
        self.combo_var = QComboBox()
        self.combo_var.addItems(list(VARS))
        self.combo_group = QComboBox()
        self.combo_group.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_group.setMinimumContentsLength(24)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Interpolate in time", "interpolate")
        self.combo_mode.addItem("Nearest model step", "nearest")
        self.spin_gap = QDoubleSpinBox()
        self.spin_gap.setRange(1.0, 24.0 * 30)
        self.spin_gap.setValue(self._default_gap)
        self.spin_gap.setSuffix(" h")
        self.spin_gap.setToolTip("Maximum spacing between model steps for a pairing to be accepted.")
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-48.0, 48.0)
        self.spin_offset.setSingleStep(0.5)
        self.spin_offset.setSuffix(" h")
        self.spin_offset.setToolTip("Added to the observation clock to bring it to model time "
                                    "(e.g. -6 for UTC to CST). Default 0 = no shift.")
        for lbl, w in (("Variable:", self.combo_var), ("Group:", self.combo_group), ("Pairing:", self.combo_mode),
                       ("Max gap:", self.spin_gap), ("Obs time offset:", self.spin_offset)):
            row1.addWidget(QLabel(lbl))
            row1.addWidget(w)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.date_start = QDateEdit()
        self.date_end = QDateEdit()
        for d in (self.date_start, self.date_end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
        self.btn_full = QPushButton("Full Record")
        self.kind_checks: dict[str, QCheckBox] = {}
        row2.addWidget(QLabel("From:"))
        row2.addWidget(self.date_start)
        row2.addWidget(QLabel("To:"))
        row2.addWidget(self.date_end)
        row2.addWidget(self.btn_full)
        row2.addSpacing(16)
        row2.addWidget(QLabel("Use:"))
        for label in KINDS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self.kind_checks[label] = cb
            row2.addWidget(cb)
        row2.addSpacing(16)
        self.chk_log = QCheckBox("Log axes")
        self.chk_log.setChecked(True)
        row2.addWidget(self.chk_log)
        row2.addStretch()
        self.btn_export = QPushButton("Export Paired CSV...")
        self.btn_export.setEnabled(False)
        row2.addWidget(self.btn_export)
        layout.addLayout(row2)

        self.lbl_status = QLabel("Load observations on the Observations tab to compare with the model.")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        split = QSplitter(Qt.Horizontal)
        self.canvas = MplCanvas(self)
        split.addWidget(self.canvas)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Statistic", "Value"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        split.addWidget(self.table)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        self.combo_var.currentIndexChanged.connect(self._on_var_changed)
        self.combo_group.currentIndexChanged.connect(self._recompute)
        self.combo_mode.currentIndexChanged.connect(self._recompute)
        self.spin_gap.valueChanged.connect(self._recompute)
        self.spin_offset.valueChanged.connect(self._recompute)
        self.date_start.dateChanged.connect(self._recompute)
        self.date_end.dateChanged.connect(self._recompute)
        self.chk_log.toggled.connect(self._recompute)
        for cb in self.kind_checks.values():
            cb.toggled.connect(self._recompute)
        self.btn_full.clicked.connect(self._full_record)
        self.btn_export.clicked.connect(self._export)
        self._on_var_changed(emit=False)

    # ------------------------------------------------------------------ public API
    def refresh(self, mds, du, xs_index):
        new_model = self._mds is not mds
        if new_model:
            self.combo_group.blockSignals(True)
            self.combo_group.clear()
            for g in mds.groups():
                self.combo_group.addItem(g.label, g.key)
                self.combo_group.setItemData(self.combo_group.count() - 1, g.description, Qt.ToolTipRole)
                if g.kind == 'rouse' and mds.rouse_reason:
                    self.combo_group.model().item(self.combo_group.count()-1).setEnabled(False)
            self.combo_group.blockSignals(False)
        self._mds, self._du, self._xs_index = mds, du, xs_index
        if new_model:
            self._full_record(recompute=False)
        self._recompute()

    def set_observations(self, obs):
        self._obs = obs
        self._recompute()

    # ------------------------------------------------------------------ helpers
    def _on_var_changed(self, *_, emit: bool = True):
        sediment = self.combo_var.currentText() in SEDIMENT_VARS
        self.combo_group.setEnabled(sediment)
        self.chk_log.blockSignals(True)
        self.chk_log.setChecked(sediment)
        self.chk_log.blockSignals(False)
        if emit:
            self._recompute()

    def _full_record(self, *_, recompute: bool = True):
        if self._mds is None:
            return
        t = self._mds.res.info.times
        for edit, ts in ((self.date_start, t.min()), (self.date_end, t.max())):
            edit.blockSignals(True)
            edit.setDate(QDate(ts.year, ts.month, ts.day))
            edit.blockSignals(False)
        if recompute:
            self._recompute()

    def _show_message(self, msg: str):
        fig = self.canvas.figure
        fig.clear()
        fig.text(0.5, 0.5, msg, ha="center", va="center", wrap=True)
        self.canvas.draw()
        self.table.setRowCount(0)
        self._paired = None
        self.btn_export.setEnabled(False)

    def _selected_kinds(self) -> list[str]:
        return [KINDS[k] for k, cb in self.kind_checks.items() if cb.isChecked()]

    # ------------------------------------------------------------------ main computation
    def _recompute(self, *_):
        if self._mds is None or self._xs_index is None:
            return
        if self._obs is None or self._obs.df.empty:
            self.lbl_status.setText("No observations loaded. Use the Observations tab (load a station or import a file).")
            self._show_message("No observations loaded.\nOpen the Observations tab and load a station or import a file.")
            return

        from analysis.calibration_metrics import filter_date_range, interpolate_model_to_times
        from analysis.observed import observed_series
        from analysis.statistics import paired_statistics
        from plotting.calibration import draw_calibration
        from sediment.rouse import RouseConfig

        label = self.combo_var.currentText()
        col, qty = VARS[label]
        group_key = self.combo_group.currentData() or "total" if label in SEDIMENT_VARS else "total"
        kinds = self._selected_kinds()
        if not kinds:
            self._show_message("Select at least one observation type (Samples / Daily values / CWMS).")
            return

        try:
            mf = self._mds.frame(self._xs_index, group_key, self._mds.rouse_cfg)
            obs_s, note = observed_series(self._obs.df, col, group_key, kinds)
        except Exception as exc:
            logger.exception("Calibration data build failed")
            self.lbl_status.setText(f"Cannot compare: {exc}")
            self._show_message(f"Cannot compare: {exc}")
            return

        if obs_s.empty:
            reason = (f"The loaded observations contain no '{label}' values for group '{group_key}' "
                      f"(types used: {', '.join(kinds)}).")
            if label in SEDIMENT_VARS and group_key not in ("total", "sand", "fines"):
                reason = f"No observed counterpart exists for sediment group '{group_key}'. Choose Total, Sand or Fines."
            self.lbl_status.setText(reason)
            self._show_message(reason)
            return

        start = pd.Timestamp(self.date_start.date().toPython())
        end = pd.Timestamp(self.date_end.date().toPython())
        obs_s = filter_date_range(obs_s, start, end)
        n_obs = len(obs_s)
        if n_obs == 0:
            msg = f"No observations between {start.date()} and {end.date()}."
            self.lbl_status.setText(msg)
            self._show_message(msg)
            return

        mode = self.combo_mode.currentData()
        mod = interpolate_model_to_times(mf.df[col], obs_s.index, mode, self.spin_gap.value(), self.spin_offset.value())
        paired = pd.DataFrame({"obs": obs_s.values, "mod": mod.values}, index=obs_s.index)
        paired = paired.dropna()
        n_pairs = len(paired)
        if n_pairs == 0:
            msg = (f"{n_obs} observations in range, but none could be paired with the model "
                   f"(outside the model period, model value missing, or model step gap > {self.spin_gap.value():g} h).")
            self.lbl_status.setText(msg)
            self._show_message(msg)
            return

        du = self._du
        o = np.asarray(du.convert(paired["obs"].values, qty), dtype=float)
        m = np.asarray(du.convert(paired["mod"].values, qty), dtype=float)
        stats = paired_statistics(o, m)
        unit = du.label(qty)
        self._fill_stats(stats, unit)

        pbias = stats.get("pbias_pct", float("nan"))
        stats_text = (f"n={stats['n_pairs']}  PBIAS={pbias:.1f}%  NSE={stats.get('nse', float('nan')):.2f}\n"
                      f"r={stats.get('pearson_r', float('nan')):.2f}  "
                      f"geo-ratio={stats.get('geometric_ratio', float('nan')):.2f}")
        group_label = mf.meta["sediment_group_label"] if label in SEDIMENT_VARS else ""
        title = f"Calibration: {label}{' - ' + group_label if group_label else ''} at {mf.meta['xs_label']}"
        subtitle = (f"Observations: {self._obs.station_name} | pairing: {mode}, max gap {self.spin_gap.value():g} h, "
                    f"time offset {self.spin_offset.value():g} h | {start.date()} to {end.date()}")
        try:
            draw_calibration(self.canvas.figure, paired, qty, label, du, self.chk_log.isChecked(), stats_text,
                             title, subtitle)
        except Exception as exc:
            logger.exception("Calibration plot failed")
            self._show_message(f"Plot error: {exc}")
            return
        self.canvas.draw()

        self._paired = paired
        self._context = {
            "model_file": mf.meta.get("source_hdf"), "plan": mf.meta.get("plan"), "cross_section": mf.meta["xs_label"],
            "variable": label, "sediment_group": group_key, "observation_station": self._obs.station_name,
            "observation_sources": self._obs.sources, "observation_derivations": self._obs.derivations,
            "observation_types": kinds, "pairing_mode": mode, "max_gap_hours": self.spin_gap.value(),
            "obs_time_offset_hours": self.spin_offset.value(), "start": str(start.date()), "end": str(end.date()),
            "display_unit": unit, "n_observations_in_range": n_obs, "n_pairs": n_pairs, "statistics": stats,
        }
        self.btn_export.setEnabled(True)

        status = f"{n_pairs} of {n_obs} observations paired ({n_obs - n_pairs} unpaired)."
        if note:
            status += f" Observed: {note}."
        if "daily" in kinds and (self._obs.df["kind"] == "daily").any():
            status += (" Daily values are daily means stamped at 00:00 and are paired with the instantaneous model "
                       "value at that time.")
        status += f" Model cross section: {mf.meta['xs_label']}."
        self.lbl_status.setText(status)

    def _fill_stats(self, stats: dict, unit: str):
        rows = [(label, fmt, stats[key]) for key, label, fmt in STAT_ROWS if key in stats]
        self.table.setRowCount(len(rows))
        for r, (label, fmt, val) in enumerate(rows):
            show = label
            if label in ("Mean observed", "Mean modelled", "Bias (mod - obs)", "MAE", "RMSE"):
                show = f"{label} ({unit})"
            try:
                txt = fmt.format(int(val) if fmt.endswith("d}") else float(val))
            except (TypeError, ValueError):
                txt = str(val)
            self.table.setItem(r, 0, QTableWidgetItem(show))
            item = QTableWidgetItem(txt)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, item)

    # ------------------------------------------------------------------ export
    def _export(self):
        if self._paired is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export paired calibration table", "paired_calibration.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        qty = VARS[self.combo_var.currentText()][1]
        unit = self._du.label(qty)
        o = np.asarray(self._du.convert(self._paired["obs"].values, qty), dtype=float)
        m = np.asarray(self._du.convert(self._paired["mod"].values, qty), dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(o > 0, m / o, np.nan)
        out = pd.DataFrame({f"Observed_{unit}": o, f"Model_{unit}": m, f"Residual_{unit}": m - o,
                            "Model_over_Observed": ratio}, index=self._paired.index)
        out.index.name = "DateTime"
        try:
            out.to_csv(path)
            meta_path = path[:-4] + ".meta.json" if path.lower().endswith(".csv") else path + ".meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(self._context, f, indent=2, default=str)
        except OSError as exc:
            logger.exception("Export failed")
            self.lbl_status.setText(f"Export failed: {exc}")
            return
        self.lbl_status.setText(f"Exported {len(out)} pairs to {path} (metadata sidecar written).")
