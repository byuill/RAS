"""Time series analysis tab."""
from __future__ import annotations

import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QComboBox, QPushButton, QLabel, QSpinBox, QCheckBox, QFileDialog, QMessageBox)

from gui.mpl_canvas import MplCanvas

logger = logging.getLogger(__name__)

class TimeSeriesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        # Controls
        ctrl_layout = QHBoxLayout()
        
        self.combo_hyd = QComboBox()
        self.combo_hyd.addItems(["Discharge", "Stage", "Velocity", "BedStress"])
        
        self.combo_sed = QComboBox()
        self.combo_sed.addItems(["Sediment Flux", "Sediment Concentration"])
        
        self.combo_group = QComboBox()
        self.combo_group.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_group.setMinimumContentsLength(24)
        
        self.combo_view = QComboBox()
        self.combo_view.addItems(["Series", "Cumulative Load", "Annual/Water-Year Loads", "Class Contribution Stacked"])
        
        self.spin_rolling = QSpinBox()
        self.spin_rolling.setRange(0, 365)
        self.spin_rolling.setSuffix(" days")
        
        self.btn_pin = QPushButton("Pin Current")
        self.btn_clear_pins = QPushButton("Clear Pins")
        self.btn_export = QPushButton('Export model CSV...')
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip('Export the selected sediment group and hydraulic fields in display units, '
                                   'including time intervals and a metadata sidecar.')
        
        ctrl_layout.addWidget(QLabel("Hydraulic:"))
        ctrl_layout.addWidget(self.combo_hyd)
        ctrl_layout.addWidget(QLabel("Sediment:"))
        ctrl_layout.addWidget(self.combo_sed)
        ctrl_layout.addWidget(QLabel("Group:"))
        ctrl_layout.addWidget(self.combo_group)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)
        view_layout = QHBoxLayout()
        view_layout.addWidget(QLabel('View:'));view_layout.addWidget(self.combo_view)
        view_layout.addWidget(QLabel('Rolling mean:'));view_layout.addWidget(self.spin_rolling)
        view_layout.addStretch();view_layout.addWidget(self.btn_pin);view_layout.addWidget(self.btn_clear_pins)
        view_layout.addWidget(self.btn_export)
        layout.addLayout(view_layout)
        self.lbl_info = QLabel('')
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)
        
        # Plot
        self.canvas = MplCanvas(self)
        layout.addWidget(self.canvas,1)
        
        self.combo_hyd.currentIndexChanged.connect(self._redraw)
        self.combo_sed.currentIndexChanged.connect(self._redraw)
        self.combo_group.currentIndexChanged.connect(self._redraw)
        self.combo_view.currentIndexChanged.connect(self._redraw)
        
        self.spin_rolling.valueChanged.connect(self._redraw)
        self.btn_pin.clicked.connect(self._pin_current)
        self.btn_clear_pins.clicked.connect(self._clear_pins)
        self.btn_export.clicked.connect(self._export_current)
        
    def _pin_current(self):
        if not hasattr(self, '_last_req') or not self._last_req:
            return
        title = self._last_req.title
        # Append rolling mean info to title if applicable
        if self.spin_rolling.value() > 0:
            title += f" ({self.spin_rolling.value()}d avg)"
        series = self._last_req.left + self._last_req.right
        self._pins.pin(title, "timeseries", series, {})
        self._redraw()

    def _clear_pins(self):
        if hasattr(self, '_pins') and self._pins:
            self._pins.clear("timeseries")
            self._redraw()
            
    def refresh(self, mds, du, pins, xs_index, obs=None):
        """Update plot with ModelDataService and display units."""
        if getattr(self, '_mds', None) is not mds:
            self.combo_group.blockSignals(True)
            self.combo_group.clear()
            for g in mds.groups():
                self.combo_group.addItem(g.label, g.key)
                self.combo_group.setItemData(self.combo_group.count() - 1, g.description, Qt.ToolTipRole)
                if g.kind == 'rouse' and mds.rouse_reason:
                    self.combo_group.model().item(self.combo_group.count()-1).setEnabled(False)
            self.combo_group.blockSignals(False)
        self._mds = mds
        self._du = du
        self._pins = pins
        self._xs_index = xs_index
        self._redraw()
        
    def _redraw(self):
        if not hasattr(self, '_mds') or self._mds is None:
            return
            
        hyd_var = self.combo_hyd.currentText()
        sed_var = self.combo_sed.currentText()
        
        from sediment.rouse import RouseConfig
        cfg = self._mds.rouse_cfg
        group_key = self.combo_group.currentData() or "total"
        
        try:
            mf = self._mds.frame(self._xs_index, group_key, cfg)
        except Exception as e:
            logger.exception("Time series build failed")
            self._show_error(f'Cannot plot: {e}')
            return
        self._last_req = None
        self._last_frame = mf
        self.btn_export.setEnabled(True)
        self.lbl_info.setText('\n'.join(mf.meta.get('warnings',[])))
        
        view = self.combo_view.currentText()
        
        from plotting.timeseries import draw_timeseries, TimeSeriesRequest, draw_periodic_loads, draw_stacked_contribution
        from plotting.styles import SeriesData
        
        if view == "Class Contribution Stacked":
            class_flux = self._mds.class_flux_frame(self._xs_index, cfg)
            draw_stacked_contribution(
                self.canvas.figure, class_flux, self._du, relative=False,
                title=f"Class Contribution at {mf.meta['xs_label']}",
                subtitle=f"{mf.meta['river']} | {mf.meta['reach']} | RS {mf.meta['cross_section']}"
            )
            self.canvas.draw()
            self.lbl_info.setText('\n'.join(mf.meta.get('warnings',[])) + '\nNegative signed flux is omitted from the positive contribution stack.')
            return
            
        if view == "Annual/Water-Year Loads":
            from analysis.calibration_metrics import periodic_loads
            loads = periodic_loads(mf.df["Flux"], mf.df["dt_days"], by="water")
            draw_periodic_loads(
                self.canvas.figure, loads, self._du,
                label=f"{group_key} Load",
                title=f"Water-Year Loads at {mf.meta['xs_label']}",
                subtitle=f"{mf.meta['river']} | {mf.meta['reach']} | RS {mf.meta['cross_section']}"
            )
            self.canvas.draw()
            self.lbl_info.setText('\n'.join(mf.meta.get('warnings',[])) +
                f'\nBackward-interval load estimate; {int(loads.n_missing.sum())} missing intervals excluded. '
                'Intervals crossing year boundaries are split between years.')
            return
            
        hyd_qty = {"Discharge": "discharge", "Stage": "length", "Velocity": "velocity", "BedStress": "shear_stress"}[hyd_var]
        hyd_col = {"Discharge": "Q", "Stage": "Stage", "Velocity": "Velocity", "BedStress": "BedStress"}[hyd_var]
        
        window_days = self.spin_rolling.value()
        
        hyd_y = mf.df[hyd_col].values
        if window_days > 0:
            from analysis.calibration_metrics import rolling_mean
            import pandas as pd
            hyd_y = rolling_mean(pd.Series(hyd_y, index=mf.df.index), window_days).values
            
        left_series = []
        if view == "Cumulative Load":
            from analysis.calibration_metrics import cumulative_load
            mass, missing = cumulative_load(mf.df["Flux"], mf.df["dt_days"])
            self.lbl_info.setText('\n'.join(mf.meta.get('warnings',[])) +
                f'\nBackward-interval load estimate; {missing} missing intervals excluded from cumulative load.')
            
            y = mass.values
            if window_days > 0:
                y = rolling_mean(pd.Series(y, index=mf.df.index), window_days).values
                
            left_series.append(SeriesData(
                x=mf.df.index.values,
                y=y,
                x_quantity="time",
                y_quantity="mass",
                label=f"{group_key} Cum. Load"
            ))
            left_name = "Cumulative Load"
        else:
            # Standard Series
            if sed_var == "Sediment Flux":
                y = mf.df["Flux"].values
                qty = "mass_flux"
            else:
                y = mf.df["Conc"].values
                qty = "concentration"
                
            if window_days > 0:
                from analysis.calibration_metrics import rolling_mean
                import pandas as pd
                y = rolling_mean(pd.Series(y, index=mf.df.index), window_days).values
                
            left_series.append(SeriesData(
                x=mf.df.index.values,
                y=y,
                x_quantity="time",
                y_quantity=qty,
                label=f"{group_key} {sed_var}"
            ))
            left_name = sed_var
            
        right_series = []
        right_series.append(SeriesData(
            x=mf.df.index.values,
            y=hyd_y,
            x_quantity="time",
            y_quantity=hyd_qty,
            label=hyd_var
        ))
        
        req = TimeSeriesRequest(
            left=left_series,
            right=right_series,
            pinned=self._pins.items("timeseries") if hasattr(self, '_pins') else [],
            title=f"{left_name} at {mf.meta['xs_label']}",
            subtitle=f"{mf.meta['river']} | {mf.meta['reach']} | RS {mf.meta['cross_section']}",
            left_name=left_name,
            right_name=hyd_var
        )
        self._last_req = req
        
        draw_timeseries(self.canvas.figure, req, self._du)
        self.canvas.draw()

    def _show_error(self,message):
        self._last_req = None
        self._last_frame = None
        self.btn_export.setEnabled(False)
        self.lbl_info.setText(message)
        fig = self.canvas.figure
        fig.clear()
        fig.text(.5,.5,message,ha='center',va='center',wrap=True)
        self.canvas.draw()

    def _export_current(self):
        if getattr(self,'_last_frame',None) is None:
            return
        path,_ = QFileDialog.getSaveFileName(self,'Export model frame','model.csv','CSV (*.csv)')
        if path:
            from export.csv_export import export_model_frame
            try:
                export_model_frame(self._last_frame,path,self._du)
                self.lbl_info.setText(f'Exported model data to {path}; metadata sidecar written.')
            except (OSError,ValueError,TypeError) as exc:
                QMessageBox.warning(self,'Export failed',str(exc))

