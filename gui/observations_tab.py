"""Observations tab: load gauge observations (cached USGS / USACE services or a local file) for calibration."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import copy
import json
import re
from pathlib import Path

import pandas as pd
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


logger = logging.getLogger(__name__)

MAX_PREVIEW_ROWS = 2000


class ObservationsTab(QWidget):
    obs_changed = Signal(object)     # ObservationSet | None
    xs_requested = Signal(int)       # cross-section index the user asked to jump to

    def __init__(self, workers, settings, parent=None):
        super().__init__(parent)
        self._workers = workers
        self._settings = settings
        self._mds = None
        self._xs_index = None
        self._obs = None
        self._raw_obs = None
        self._qaqc_review = None
        self._qaqc_masks = None
        self._preview_positions = []
        self._service = None
        self._service_error = ""
        self._catalog = None
        self._store = None
        self._pending: dict[int, TaskWorker] = {}      # keep workers alive until their queued signal arrives
        self._mapped_xs_index: int | None = None

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.combo_station = QComboBox()
        self.combo_station.setMinimumWidth(280)
        self.btn_load = QPushButton("Load")
        self.btn_load_all = QPushButton("Load All Data")
        self.btn_refresh = QPushButton("Refresh (re-download)")
        self.btn_import = QPushButton("Import CSV/Excel...")
        self.btn_clear_cache = QPushButton("Clear Station Cache")
        self.btn_open_cache = QPushButton("Open Cache Folder")
        row.addWidget(QLabel("Station:"))
        row.addWidget(self.combo_station, 1)
        for b in (self.btn_load, self.btn_load_all, self.btn_refresh, self.btn_import):
            row.addWidget(b)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.chk_proxy = QCheckBox('Estimate missing discharge'); self.chk_proxy.setChecked(True)
        self.chk_subdaily = QCheckBox('Use sample-day USGS subdaily flow')
        self.chk_subdaily.setToolTip('Optional: fetch only days around missing sample discharge. More requests, but finer timing than daily means.')
        self.btn_proxy = QPushButton('Fill missing Q for imported data')
        self.btn_proxy.setToolTip('Use the station selected above as the imported sediment sampling location. Review that choice before using this tool.')
        row.addWidget(self.chk_proxy); row.addWidget(self.chk_subdaily); row.addWidget(self.btn_proxy)
        row.addStretch(); row.addWidget(self.btn_clear_cache); row.addWidget(self.btn_open_cache)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.combo_qaqc_var = QComboBox()
        for label, field in [('SSC', 'ssc_mg_l'), ('Sediment load', 'ssl_kg_s'), ('Discharge', 'discharge_m3s'),
                             ('Sand concentration', 'sand_mg_l'), ('Fines concentration', 'fines_mg_l'), ('Percent fines', 'pct_fines')]:
            self.combo_qaqc_var.addItem(label, field)
        self.combo_qaqc_method = QComboBox()
        for label, key in [('Physical/qualifier flags only', 'none'), ('Robust MAD', 'mad'), ('IQR', 'iqr'), ('Rating residuals', 'rating_residual')]:
            self.combo_qaqc_method.addItem(label, key)
        self.spin_qaqc = QDoubleSpinBox(); self.spin_qaqc.setRange(.1, 100); self.spin_qaqc.setValue(6)
        self.chk_qaqc_log = QCheckBox('Log values'); self.chk_qaqc_log.setChecked(True)
        self.chk_censored = QCheckBox('Flag censored results'); self.chk_censored.setChecked(True)
        self.chk_q_proxy = QCheckBox('Flag estimated Q')
        for label, widget in [('QA/QC variable:', self.combo_qaqc_var), ('Method:', self.combo_qaqc_method), ('Threshold:', self.spin_qaqc)]:
            row.addWidget(QLabel(label)); row.addWidget(widget)
        row.addWidget(self.chk_qaqc_log); row.addWidget(self.chk_censored); row.addWidget(self.chk_q_proxy)
        row.addStretch(); layout.addLayout(row)

        row = QHBoxLayout()
        self.chk_lower, self.chk_upper = QCheckBox('Minimum'), QCheckBox('Maximum')
        self.spin_lower, self.spin_upper = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.spin_lower, self.spin_upper): spin.setRange(-1e12, 1e12); spin.setDecimals(3)
        self.spin_upper.setValue(1e6)
        self.lbl_qaqc_unit = QLabel('mg/L')
        self.btn_review = QPushButton('Flag suspect values')
        self.btn_exclude_flags = QPushButton('Exclude flagged values')
        self.btn_exclude_selected = QPushButton('Exclude selected values')
        self.btn_restore = QPushButton('Restore raw values')
        self.btn_audit = QPushButton('Export QA/QC audit…')
        self.chk_flagged_only = QCheckBox('Show flagged only')
        for widget in (self.chk_lower, self.spin_lower, self.chk_upper, self.spin_upper, self.lbl_qaqc_unit):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        for widget in (self.btn_review, self.btn_exclude_flags, self.btn_exclude_selected, self.btn_restore, self.btn_audit):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)
        self.lbl_qaqc_status = QLabel('QA/QC flags are candidates for review; no measurements are automatically discarded.')
        self.lbl_qaqc_status.setWordWrap(True)
        row = QHBoxLayout(); row.addWidget(self.lbl_qaqc_status, 1); row.addWidget(self.chk_flagged_only)
        layout.addLayout(row)

        map_row = QHBoxLayout()
        self.lbl_mapping = QLabel("Cross-section mapping: (load a model file first)")
        self.lbl_mapping.setWordWrap(True)
        self.btn_goto_xs = QPushButton("Go to mapped XS")
        self.btn_map_manual = QPushButton("Map station to current XS")
        map_row.addWidget(self.lbl_mapping, 1)
        map_row.addWidget(self.btn_goto_xs)
        map_row.addWidget(self.btn_map_manual)
        layout.addLayout(map_row)

        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setMaximumHeight(150)
        layout.addWidget(self.txt_info)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)

        self.btn_goto_xs.setEnabled(False)
        self.btn_map_manual.setEnabled(False)

        self.btn_load.clicked.connect(lambda: self._load(refresh=False))
        self.btn_load_all.clicked.connect(lambda: self._load_all(refresh=False))
        self.btn_refresh.clicked.connect(lambda: self._load(refresh=True))
        self.btn_import.clicked.connect(self._import_file)
        self.btn_clear_cache.clicked.connect(self._clear_cache)
        self.btn_open_cache.clicked.connect(self._open_cache)
        self.btn_goto_xs.clicked.connect(self._goto_xs)
        self.btn_map_manual.clicked.connect(self._map_manual)
        self.combo_station.currentIndexChanged.connect(self._update_mapping)
        self.btn_proxy.clicked.connect(self._fill_missing_q)
        self.btn_review.clicked.connect(self._review_qaqc)
        self.btn_exclude_flags.clicked.connect(self._exclude_flags)
        self.btn_exclude_selected.clicked.connect(self._exclude_selected)
        self.btn_restore.clicked.connect(self._restore_raw)
        self.btn_audit.clicked.connect(self._export_audit)
        self.chk_flagged_only.toggled.connect(lambda _: self._fill_table(self._obs) if self._obs else None)
        self.combo_qaqc_var.currentIndexChanged.connect(self._qaqc_units)

        self._init_service()
        self._qaqc_units()

    # ------------------------------------------------------------------ setup
    def _init_service(self):
        try:
            from observations.cache import ObservationCache
            from observations.mapping import MappingStore
            from observations.service import ObservationService
            from observations.station_catalog import StationCatalog

            self._catalog = StationCatalog.load()
            cache = ObservationCache(Path(self._settings.observation_cache_dir))
            self._service = ObservationService(self._catalog, cache)
            self._store = MappingStore()
        except Exception as exc:   # shown to the user below; never swallowed
            logger.exception("Observation service could not be initialised")
            self._service_error = str(exc)
            self.txt_info.setPlainText(f"Observation service unavailable: {exc}\n"
                                       "You can still import a local CSV/Excel file.")
            for b in (self.btn_load, self.btn_load_all, self.btn_refresh, self.btn_clear_cache, self.btn_open_cache):
                b.setEnabled(False)
            return
        for s in self._catalog.all():
            self.combo_station.addItem(s.label, s.id)

    def set_model(self, mds, xs_index):
        """Called when a model file is (re)loaded."""
        self._workers.invalidate('obs')
        self._workers.invalidate('obs_all')
        self._set_busy(False)
        self._mds = mds
        self._xs_index = xs_index
        self._update_mapping()

    def set_current_xs(self, xs_index):
        self._xs_index = xs_index
        self.btn_map_manual.setEnabled(self._mds is not None and xs_index is not None and self._catalog is not None)

    @property
    def observations(self):
        return self._obs

    # ------------------------------------------------------------------ mapping
    def _geometry_key(self) -> str:
        info = self._mds.res.info
        return f"{Path(info.path).name}|{info.geometry_title}"

    def _update_mapping(self, *_):
        self._mapped_xs_index = None
        self.btn_goto_xs.setEnabled(False)
        self.btn_map_manual.setEnabled(self._mds is not None and self._xs_index is not None and self._catalog is not None)
        if self._mds is None or self._catalog is None or self.combo_station.currentData() is None:
            return
        from observations.mapping import resolve_mapping
        station = self._catalog.get(self.combo_station.currentData())
        try:
            m = resolve_mapping(station, list(self._mds.res.info.xs), self._store, self._geometry_key())
        except Exception as exc:
            logger.exception("Station mapping failed")
            self.lbl_mapping.setText(f"Cross-section mapping failed: {exc}")
            return
        if m.xs is None:
            self.lbl_mapping.setText(f"Cross-section mapping: none. {m.message}")
        else:
            self._mapped_xs_index = m.xs.index
            self.lbl_mapping.setText(f"Cross-section mapping ({m.source}): {m.xs.label} - {m.message}")
            self.btn_goto_xs.setEnabled(True)

    def _goto_xs(self):
        if self._mapped_xs_index is not None:
            self.xs_requested.emit(self._mapped_xs_index)

    def _map_manual(self):
        if self._mds is None or self._xs_index is None:
            return
        from observations.mapping import xs_key
        station_id = self.combo_station.currentData()
        xs = self._mds.res.info.xs[self._xs_index]
        try:
            self._store.set(self._geometry_key(), station_id, xs_key(xs), "set in GUI")
        except Exception as exc:
            logger.exception("Could not save mapping")
            QMessageBox.warning(self, "Mapping", f"Could not save the mapping: {exc}")
            return
        self._update_mapping()

    # ------------------------------------------------------------------ loading
    def _load(self, refresh: bool):
        if self._service is None:
            return
        if self._mds is None:
            self.txt_info.setPlainText("Open a HEC-RAS results file first (the model period defines the date range).")
            return
        station = self._catalog.get(self.combo_station.currentData())
        times = self._mds.res.info.times
        start, end = times.min(), times.max()
        self.txt_info.setPlainText(f"Loading {station.label}, {start.date()} to {end.date()} "
                                   f"({'forced re-download' if refresh else 'cache first'}) ...")
        self._set_busy(True)
        token = self._workers.submit('obs',self._service.load,
            lambda result:self._on_loaded((token,result)),
            lambda error:self._on_load_error((token,error)),station,start,end,None,refresh,
            derive_discharge=self.chk_proxy.isChecked(),include_subdaily=self.chk_subdaily.isChecked())

    def _on_loaded(self, payload):
        token, (obs, report) = payload
        self._pending.pop(token, None)
        if not self._workers.is_current("obs", token):
            return
        self._set_busy(False)
        lines = [f"{obs.station_name}: {obs.n_records} records"]
        lines += report.lines()
        lines += [f"Derived: {d}" for d in obs.derivations]
        lines += [f"Note: {n}" for n in obs.notes]
        self.txt_info.setPlainText("\n".join(lines))
        self._set_obs(obs)

    def _on_load_error(self, payload):
        token, exc = payload
        self._pending.pop(token, None)
        if not self._workers.is_current("obs", token):
            return
        self._set_busy(False)
        self.txt_info.setPlainText(f"Loading observations failed: {exc}")

    def _load_all(self, refresh: bool):
        if self._service is None:
            return
        if self._mds is None:
            self.txt_info.setPlainText("Open a HEC-RAS results file first (the model period defines the date range).")
            return
        times = self._mds.res.info.times
        start, end = times.min(), times.max()
        self.txt_info.setPlainText(f"Loading ALL stations, {start.date()} to {end.date()} "
                                   f"({'forced re-download' if refresh else 'cache first'}) ...")
        self._set_busy(True)
        derive, subdaily = self.chk_proxy.isChecked(), self.chk_subdaily.isChecked()
        
        def worker_func():
            results = []
            for st in self._catalog.all():
                try:
                    obs, rep = self._service.load(st, start, end, refresh=refresh, derive_discharge=derive, include_subdaily=subdaily)
                    results.append((st, obs, rep, None))
                except Exception as exc:
                    results.append((st, None, None, str(exc)))
            return results
            
        token = self._workers.submit('obs_all',worker_func,
            lambda result:self._on_load_all_finished((token,result)),
            lambda error:self._on_load_all_error((token,error)))

    def _on_load_all_finished(self, payload):
        token, results = payload
        self._pending.pop(token, None)
        if not self._workers.is_current("obs_all", token):
            return
        self._set_busy(False)
        lines = ["Loaded all stations:"]
        current_obs = None
        for st, obs, rep, err in results:
            if err:
                lines.append(f"{st.short_name}: ERROR - {err}")
            elif obs:
                lines.append(f"{st.short_name}: {obs.n_records} records")
                if st.id == self.combo_station.currentData():
                    current_obs = obs
                    
        self.txt_info.setPlainText("\n".join(lines))
        if current_obs:
            self._set_obs(current_obs)

    def _on_load_all_error(self, payload):
        token, exc = payload
        self._pending.pop(token, None)
        if not self._workers.is_current("obs_all", token):
            return
        self._set_busy(False)
        self.txt_info.setPlainText(f"Loading all observations failed: {exc}")

    def _set_busy(self, busy: bool):
        for b in (self.btn_load, self.btn_load_all, self.btn_refresh, self.btn_import, self.btn_proxy,
                  self.btn_review, self.btn_exclude_flags, self.btn_exclude_selected, self.btn_restore, self.btn_audit):
            b.setEnabled(not busy)

    def _set_obs(self, obs):
        self._raw_obs = copy.deepcopy(obs)
        self._qaqc_masks = None
        self._qaqc_review = None
        self._obs = obs
        self._review_qaqc()
        self.obs_changed.emit(obs)

    def _fill_table(self, obs):
        df = obs.df
        cols = [c for c in obs.available_variables()] + ["kind", "source", "qualifier", "sample_station_id", "q_is_proxy", "q_original_m3s", "q_method", "q_sources",
            "q_proxy_recipe", "q_lag_hours", "q_proxy_low_m3s", "q_proxy_high_m3s", "qaqc_excluded_fields"]
        cols = [c for c in cols if c in df.columns]
        positions = np.arange(len(df))
        if self.chk_flagged_only.isChecked() and self._qaqc_review is not None:
            positions = positions[self._qaqc_review.flags.any(axis=1).to_numpy()]
        self._preview_positions = positions[:MAX_PREVIEW_ROWS]
        view = df.iloc[self._preview_positions][cols]
        self.table.clear()
        self.table.setColumnCount(len(cols) + 2)
        self.table.setRowCount(len(view))
        from observations.processing import OBS_VARIABLES
        from sediment.units import CANONICAL
        headers = [f'{c} ({"%" if c == "pct_fines" else CANONICAL[OBS_VARIABLES[c][1]]})' if c in OBS_VARIABLES else c for c in cols]
        self.table.setHorizontalHeaderLabels(["DateTime"] + headers + ['QA/QC flags'])
        for r, (ts, row) in enumerate(view.iterrows()):
            self.table.setItem(r, 0, QTableWidgetItem(str(ts)))
            reasons = self._qaqc_review.reasons.iloc[self._preview_positions[r]] if self._qaqc_review is not None else pd.Series(dtype=str)
            excluded = str(row.get('qaqc_excluded_fields', '')).split(';')
            for c, name in enumerate(cols, start=1):
                v = row[name]
                txt = "" if pd.isna(v) else str(v) if isinstance(v, (bool, np.bool_)) else (f"{v:.5g}" if isinstance(v, (int, float)) else str(v))
                item = QTableWidgetItem(txt)
                if reasons.get(name, ''):
                    item.setBackground(QColor('#fff2cc')); item.setToolTip(reasons[name])
                if name in excluded:
                    item.setBackground(QColor('#e0e0e0')); item.setToolTip('Excluded from analysis by QA/QC; original value remains in the audit.')
                self.table.setItem(r, c, item)
            if self._qaqc_review is not None:
                text = '; '.join(f'{field}: {reason}' for field, reason in reasons.items() if reason)
                self.table.setItem(r, len(cols)+1, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def _qaqc_units(self):
        from observations.processing import OBS_VARIABLES
        from plotting.styles import DisplayUnits
        quantity = OBS_VARIABLES[self.combo_qaqc_var.currentData()][1]
        self.lbl_qaqc_unit.setText('%' if quantity == 'dimensionless' else DisplayUnits(self._settings).label(quantity))
        self.chk_lower.setChecked(False); self.chk_upper.setChecked(False)

    def _review_qaqc(self):
        if self._obs is None: return
        from observations.qaqc import review_observations
        from observations.processing import OBS_VARIABLES
        from sediment.units import to_canonical
        from plotting.styles import DisplayUnits
        variable = self.combo_qaqc_var.currentData(); quantity = OBS_VARIABLES[variable][1]
        du = DisplayUnits(self._settings)
        def bound(spin, check):
            if not check.isChecked(): return None
            return spin.value() if quantity == 'dimensionless' else float(to_canonical(spin.value(), du.unit(quantity)))
        try:
            review = review_observations(self._obs.df, variable, self.combo_qaqc_method.currentData(), self.spin_qaqc.value(),
                self.chk_qaqc_log.isChecked(), bound(self.spin_lower, self.chk_lower), bound(self.spin_upper, self.chk_upper),
                self.chk_censored.isChecked())
            review.options['flag_proxy_discharge'] = self.chk_q_proxy.isChecked()
            if self.chk_q_proxy.isChecked() and 'q_is_proxy' in self._obs.df:
                mask = self._obs.df.q_is_proxy.fillna(False).to_numpy(bool)
                review.flags.loc[:, 'discharge_m3s'] |= mask
                ci = review.reasons.columns.get_loc('discharge_m3s')
                for pos in np.flatnonzero(mask): review.reasons.iat[pos, ci] += '; estimated discharge'
            self._qaqc_review = review
            self.lbl_qaqc_status.setText(f'{review.flags.to_numpy().sum()} flagged values in {review.flags.any(axis=1).sum()}/{len(self._obs.df)} records. '+ ' '.join(review.notes))
            self._fill_table(self._obs)
        except ValueError as exc:
            self._qaqc_review = None
            self.lbl_qaqc_status.setText(f'QA/QC: {exc}')

    def _exclude_flags(self):
        if self._qaqc_review is None: return
        self._add_exclusions(self._qaqc_review.flags)

    def _exclude_selected(self):
        if self._obs is None: return
        from observations.processing import OBS_VARIABLES
        masks = pd.DataFrame(False, index=self._obs.df.index, columns=list(OBS_VARIABLES))
        field = self.combo_qaqc_var.currentData()
        for item in self.table.selectedIndexes():
            masks.iloc[self._preview_positions[item.row()], masks.columns.get_loc(field)] = True
        self._add_exclusions(masks)

    def _add_exclusions(self, masks):
        from observations.qaqc import apply_exclusions
        if self._qaqc_masks is None: self._qaqc_masks = masks.copy()
        else: self._qaqc_masks = self._qaqc_masks.reindex(columns=self._qaqc_masks.columns.union(masks.columns), fill_value=False) | masks.reindex(columns=self._qaqc_masks.columns.union(masks.columns), fill_value=False)
        self._obs = apply_exclusions(self._raw_obs, self._qaqc_masks, self._qaqc_review)
        self._fill_table(self._obs)
        self.lbl_qaqc_status.setText(f'Excluded {self._obs.qaqc["excluded_cells"]} cells in {self._obs.qaqc["excluded_records"]} records. Restore raw values undoes all QA/QC exclusions.')
        self.obs_changed.emit(self._obs)

    def _restore_raw(self):
        if self._raw_obs is not None: self._set_obs(copy.deepcopy(self._raw_obs))

    def _export_audit(self):
        if self._raw_obs is None: return
        from observations.processing import OBS_VARIABLES
        from core.io import atomic_writer, atomic_text
        path, _ = QFileDialog.getSaveFileName(self, 'Export observation QA/QC audit', 'observation_qaqc.csv', 'CSV (*.csv)')
        if not path: return
        out = self._raw_obs.df.copy()
        for field in OBS_VARIABLES:
            if field in self._obs.df: out['used_'+field] = self._obs.df[field].to_numpy()
            if self._qaqc_review is not None and field in self._qaqc_review.reasons:
                out['flags_'+field] = self._qaqc_review.reasons[field].to_numpy()
        out['qaqc_excluded_fields'] = self._obs.df.get('qaqc_excluded_fields', pd.Series('', index=self._obs.df.index)).to_numpy()
        out.index.name = 'DateTime'
        try:
            with atomic_writer(path) as stream: out.to_csv(stream)
            atomic_text(Path(path).with_suffix('.meta.json'), json.dumps({'station': self._obs.station_name,
                'qaqc': self._obs.qaqc, 'review': self._qaqc_review.options if self._qaqc_review else {},
                'sources': self._obs.sources, 'derivations': self._obs.derivations, 'notes': self._obs.notes}, indent=2, default=str))
            self.lbl_qaqc_status.setText(f'Exported raw/used values, flags and metadata to {path}.')
        except OSError as exc: self.lbl_qaqc_status.setText(f'Audit export failed: {exc}')

    def _fill_missing_q(self):
        if self._service is None or self._obs is None or self._obs.df.empty: return
        station = self._catalog.get(self.combo_station.currentData())
        if 'sample_station_id' in self._obs.df:
            codes = self._obs.df.sample_station_id.dropna().astype(str).str.strip().unique()
            for code in codes:
                normalized = code[5:] if code.startswith('USGS-') else code
                if re.fullmatch(r'\d{1,8}(?:\.0)?', normalized):
                    normalized = normalized.split('.')[0].zfill(8)
                    known = {entry.site_no for entry in self._catalog.all()}
                    if normalized in known and normalized != station.site_no:
                        self.txt_info.setPlainText(f'Imported station {code} differs from {station.name}. Select the actual sampling station before estimating discharge.')
                        return
        obs = copy.deepcopy(self._raw_obs)
        self.txt_info.setPlainText(f'Estimating missing Q for imported measurements assigned to {station.name}.')
        self._set_busy(True)
        token = self._workers.submit('obs', self._service.enrich_discharge,
            lambda result: self._proxy_loaded(token, result), lambda error: self._on_load_error((token,error)),
            obs, station, obs.df.index.min(), obs.df.index.max(), include_subdaily=self.chk_subdaily.isChecked())

    def _proxy_loaded(self, token, obs):
        if not self._workers.is_current('obs', token): return
        self._set_busy(False)
        self.txt_info.setPlainText('\n'.join(obs.derivations+obs.notes))
        masks = self._qaqc_masks
        self._set_obs(obs)
        if masks is not None: self._add_exclusions(masks)

    # ------------------------------------------------------------------ local file import
    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import observations", str(self._settings.default_model_dir),
                                              "Tables (*.csv *.txt *.xlsx *.xls *.xlsm);;All Files (*)")
        if not path:
            return
        from observations.local_import import detect_mapping, merge_sets, read_table, to_observation_set
        from gui.dialogs import ColumnMappingDialog
        try:
            df = read_table(path)
            mapping = detect_mapping(df)
            
            dlg = ColumnMappingDialog(list(df.columns), mapping, self)
            if dlg.exec() != dlg.Accepted:
                return
            mapping = dlg.get_mapping()
            
            name = Path(path).name
            obs = to_observation_set(df, mapping, "local", name, f"user file {name}")
        except Exception as exc:
            logger.exception("Import failed")
            self.txt_info.setPlainText(f"Import failed: {exc}")
            return
        obs = merge_sets(self._obs if self._obs is not None and self._obs.station_id == "local" else None, obs)
        used = [f"  {k}: '{v.column}' ({v.unit})" for k, v in mapping.items() if v.column]
        self.txt_info.setPlainText(
            f"Imported {name}: {obs.n_records} records.\nColumns detected (check the units!):\n" + "\n".join(used)
            + "\n" + "\n".join(f"Derived: {d}" for d in obs.derivations))
        self._set_obs(obs)

    # ------------------------------------------------------------------ cache
    def _clear_cache(self):
        if self._service is None:
            return
        sid = self.combo_station.currentData()
        if QMessageBox.question(self, "Clear cache", f"Delete the cached data for {self.combo_station.currentText()}?") \
                != QMessageBox.Yes:
            return
        n = self._service.cache.clear_station(sid)
        self.txt_info.setPlainText(f"Cleared {n} cache file(s) for {sid}.")

    def _open_cache(self):
        if self._service is None:
            return
        folder = self._service.cache.folder(self.combo_station.currentData())
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)   # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            self.txt_info.setPlainText(f"Could not open {folder}: {exc}")
