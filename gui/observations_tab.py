"""Observations tab: load gauge observations (cached USGS / USACE services or a local file) for calibration."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from gui.workers import TaskWorker

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
        for b in (self.btn_load, self.btn_load_all, self.btn_refresh, self.btn_import, self.btn_clear_cache, self.btn_open_cache):
            row.addWidget(b)
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

        self._init_service()

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
        token = self._workers.next_token("obs")
        worker = TaskWorker(token, self._service.load, station, start, end, None, refresh)
        worker.signals.finished.connect(self._on_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._pending[token] = worker
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(worker)

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
        token = self._workers.next_token("obs_all")
        
        def worker_func():
            results = []
            for st in self._catalog.all():
                try:
                    obs, rep = self._service.load(st, start, end, refresh=refresh)
                    results.append((st, obs, rep, None))
                except Exception as exc:
                    results.append((st, None, None, str(exc)))
            return results
            
        worker = TaskWorker(token, worker_func)
        worker.signals.finished.connect(self._on_load_all_finished)
        worker.signals.error.connect(self._on_load_all_error)
        self._pending[token] = worker
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(worker)

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
        for b in (self.btn_load, self.btn_load_all, self.btn_refresh, self.btn_import):
            b.setEnabled(not busy)

    def _set_obs(self, obs):
        self._obs = obs
        self._fill_table(obs)
        self.obs_changed.emit(obs)

    def _fill_table(self, obs):
        df = obs.df
        cols = [c for c in obs.available_variables()] + ["kind", "source"]
        cols = [c for c in cols if c in df.columns]
        view = df[cols].head(MAX_PREVIEW_ROWS)
        self.table.clear()
        self.table.setColumnCount(len(cols) + 1)
        self.table.setRowCount(len(view))
        self.table.setHorizontalHeaderLabels(["DateTime"] + cols)
        for r, (ts, row) in enumerate(view.iterrows()):
            self.table.setItem(r, 0, QTableWidgetItem(str(ts)))
            for c, name in enumerate(cols, start=1):
                v = row[name]
                txt = "" if pd.isna(v) else (f"{v:.5g}" if isinstance(v, (int, float)) else str(v))
                self.table.setItem(r, c, QTableWidgetItem(txt))
        self.table.resizeColumnsToContents()

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
