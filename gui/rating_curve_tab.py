"""Rating curve analysis tab."""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QComboBox, QPushButton, QLabel, QCheckBox)

from gui.mpl_canvas import MplCanvas

logger = logging.getLogger(__name__)

# label -> (frame column, canonical quantity key)
X_VARS = {
    "Discharge": ("Q", "discharge"),
    "Velocity": ("Velocity", "velocity"),
    "BedStress": ("BedStress", "shear_stress"),
    "Stage": ("Stage", "length"),
}
Y_VARS = {
    "Sediment Flux": ("Flux", "mass_flux"),
    "Sediment Concentration": ("Conc", "concentration"),
}
CATEGORICAL = ("month", "season", "limb", "hydro")


class RatingCurveTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._mds = None
        self._du = None
        self._pins = None
        self._xs_index = None
        self._last_req = None
        self._last_result = None
        self._cat_cache: dict = {}

        layout = QVBoxLayout(self)

        # Controls
        ctrl_layout = QHBoxLayout()

        self.combo_x = QComboBox()
        self.combo_x.addItems(list(X_VARS))

        self.combo_y = QComboBox()
        self.combo_y.addItems(list(Y_VARS))

        self.combo_group = QComboBox()

        self.combo_scale = QComboBox()
        self.combo_scale.addItems(["log-log", "log x - linear y", "linear x - log y", "linear-linear"])

        self.combo_color = QComboBox()
        self.combo_color.addItems(["none", "time", "month", "season", "limb", "hydro"])

        self.chk_fit = QCheckBox("Fit Power Law")
        self.chk_fit_cat = QCheckBox("Fit per category")
        self.chk_connect = QCheckBox("Connect Points")
        self.chk_arrows = QCheckBox("Arrows")

        self.btn_pin = QPushButton("Pin Current")
        self.btn_clear_pins = QPushButton("Clear Pins")

        ctrl_layout.addWidget(QLabel("X Axis:"))
        ctrl_layout.addWidget(self.combo_x)
        ctrl_layout.addWidget(QLabel("Y Axis:"))
        ctrl_layout.addWidget(self.combo_y)
        ctrl_layout.addWidget(QLabel("Group:"))
        ctrl_layout.addWidget(self.combo_group)
        ctrl_layout.addWidget(QLabel("Scale:"))
        ctrl_layout.addWidget(self.combo_scale)
        ctrl_layout.addWidget(QLabel("Color By:"))
        ctrl_layout.addWidget(self.combo_color)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        opt_layout = QHBoxLayout()
        opt_layout.addWidget(self.chk_fit)
        opt_layout.addWidget(self.chk_fit_cat)
        opt_layout.addWidget(self.chk_connect)
        opt_layout.addWidget(self.chk_arrows)
        opt_layout.addStretch()
        opt_layout.addWidget(self.btn_pin)
        opt_layout.addWidget(self.btn_clear_pins)
        layout.addLayout(opt_layout)

        # Plot
        self.canvas = MplCanvas(self)
        layout.addWidget(self.canvas, 1)

        # Fit / drop summary
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.lbl_info)

        self.chk_fit_cat.setEnabled(False)

        for c in (self.combo_x, self.combo_y, self.combo_group, self.combo_scale, self.combo_color):
            c.currentIndexChanged.connect(self._redraw)
        self.combo_color.currentIndexChanged.connect(self._sync_enabled)
        for c in (self.chk_fit, self.chk_fit_cat, self.chk_connect, self.chk_arrows):
            c.toggled.connect(self._redraw)
        self.btn_pin.clicked.connect(self._pin_current)
        self.btn_clear_pins.clicked.connect(self._clear_pins)

    # ------------------------------------------------------------------ helpers
    def _sync_enabled(self):
        categorical = self.combo_color.currentText() in CATEGORICAL
        self.chk_fit_cat.setEnabled(categorical)
        if not categorical:
            self.chk_fit_cat.blockSignals(True)
            self.chk_fit_cat.setChecked(False)
            self.chk_fit_cat.blockSignals(False)

    def _show_error(self, msg: str):
        fig = self.canvas.figure
        fig.clear()
        fig.text(0.5, 0.5, msg, ha="center", va="center", wrap=True)
        self.canvas.draw()
        self.lbl_info.setText("")

    def _categories(self, mf, kind: str):
        """Category label per row for month / season / limb / hydro colouring (cached)."""
        from analysis import seasonality as S
        from analysis import hysteresis as H

        key = (id(self._mds), self._xs_index, kind, len(mf.df))
        if key in self._cat_cache:
            return self._cat_cache[key]
        idx = mf.df.index
        if kind == "month":
            cats = S.month_of(idx)
        elif kind == "season":
            cats = S.season_of(idx)
        else:
            q = mf.df["Q"]
            limbs_daily = H.classify_limbs(q)
            if kind == "limb":
                cats = S.map_daily_to_index(limbs_daily, idx)
            else:
                hydro_daily = S.classify_hydrologic_periods(q, limb_labels=limbs_daily)
                cats = S.map_daily_to_index(hydro_daily, idx)
        cats = np.asarray(cats)
        self._cat_cache[key] = cats
        return cats

    # ------------------------------------------------------------------ pins
    def _pin_current(self):
        if self._last_req is None or self._pins is None:
            return
        from plotting.styles import SeriesData
        req = self._last_req
        series = [SeriesData(x=np.array(req.x, copy=True), y=np.array(req.y, copy=True),
                             x_quantity=req.x_quantity, y_quantity=req.y_quantity,
                             label=req.current_label, role="model")]
        if self._last_result is not None:
            for key, (fx, fy) in self._last_result.fit_lines.items():
                f = self._last_result.fits.get(key)
                lab = f"Fit {req.current_label}" + ("" if key == "all" else f" [{key}]")
                if f is not None:
                    lab += f": y={f.a:.3g}x^{f.b:.3f}"
                series.append(SeriesData(x=np.asarray(fx), y=np.asarray(fy), x_quantity=req.x_quantity,
                                         y_quantity=req.y_quantity, label=lab, role="fit"))
        self._pins.pin(req.current_label, "rating", series, {})
        self._redraw()

    def _clear_pins(self):
        if self._pins is not None:
            self._pins.clear("rating")
            self._redraw()

    # ------------------------------------------------------------------ public
    def refresh(self, mds, du, pins, xs_index, obs=None):
        if self._mds is not mds:
            self._cat_cache.clear()
            self.combo_group.blockSignals(True)
            self.combo_group.clear()
            for g in mds.groups():
                self.combo_group.addItem(g.label, g.key)
                self.combo_group.setItemData(self.combo_group.count() - 1, g.description, Qt.ToolTipRole)
            self.combo_group.blockSignals(False)
        self._mds = mds
        self._du = du
        self._pins = pins
        self._xs_index = xs_index
        self._redraw()

    def _redraw(self, *_):
        if self._mds is None or self._xs_index is None:
            return

        from plotting.rating_curve import draw_rating, RatingRequest
        from sediment.rouse import RouseConfig

        group_key = self.combo_group.currentData() or "total"
        try:
            mf = self._mds.frame(self._xs_index, group_key, RouseConfig())
        except Exception as e:
            logger.exception("Rating curve build failed")
            self._show_error(f"Cannot plot: {e}")
            return

        x_label, y_label = self.combo_x.currentText(), self.combo_y.currentText()
        x_col, x_qty = X_VARS[x_label]
        y_col, y_qty = Y_VARS[y_label]
        color_by = self.combo_color.currentText()

        x = mf.df[x_col].to_numpy(dtype=float)
        y = mf.df[y_col].to_numpy(dtype=float)
        if not np.isfinite(x).any():
            self._show_error(f"'{x_label}' is not available in this results file.")
            return

        cats = None
        try:
            if color_by in CATEGORICAL:
                cats = self._categories(mf, color_by)
        except Exception as e:
            logger.exception("Category classification failed")
            self._show_error(f"Cannot classify '{color_by}': {e}")
            return

        req = RatingRequest(
            x=x, y=y, times=mf.df.index, x_quantity=x_qty, y_quantity=y_qty,
            x_name=x_label, y_name=y_label,
            scale=self.combo_scale.currentText(), color_by=color_by, categories=cats,
            connect=self.chk_connect.isChecked(), arrows=self.chk_arrows.isChecked(),
            fit=self.chk_fit.isChecked(), fit_by_category=self.chk_fit_cat.isChecked(),
            current_label=f"HEC-RAS {mf.meta['sediment_group_label']}",
            pinned=self._pins.items("rating") if self._pins is not None else [],
            title=f"{y_label} vs {x_label} at {mf.meta['xs_label']}",
            subtitle=f"{mf.meta['river']} | {mf.meta['reach']} | RS {mf.meta['cross_section']}",
        )
        self._last_req = req

        try:
            result = draw_rating(self.canvas.figure, req, self._du)
        except Exception as e:
            logger.exception("Rating curve draw failed")
            self._show_error(f"Plot error: {e}")
            return
        self._last_result = result
        self.canvas.draw()

        lines = [result.drop.text()]
        for key, f in result.fits.items():
            lines.append(f"[{key}] {f.equation()}  R\u00b2(log)={f.r2_log:.3f}  n={f.n}  "
                         f"b 95% CI=({f.b_ci[0]:.3f}, {f.b_ci[1]:.3f})")
        lines.extend(result.notes)
        if color_by in ("limb", "hydro"):
            lines.append("Limb classification uses the original tool's thresholds (rising/falling gated at "
                         ">500,000 cfs); lower flows are shown as 'Other'.")
        self.lbl_info.setText("\n".join(lines))
