"""Diagnostics and metadata inspection tab."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit

class DiagnosticsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        layout.addWidget(self.txt)
        
    def refresh(self, mds, xs_index):
        if not mds or xs_index is None:
            return
            
        info = mds.res.info
        xs = info.xs[xs_index]
        
        lines = []
        lines.append("=== Model Information ===")
        lines.append(f"Geometry: {info.geometry_title}")
        lines.append(f"Plan: {info.short_id} ({info.plan_name})")
        lines.append(f"Time Range: {info.times.min()} to {info.times.max()}")
        lines.append(f"Sediment Classes: {', '.join([gc.name for gc in info.grain_classes])}")
        lines.append(f'HEC-RAS version: {info.hec_version}; model units: {info.units_system}')
        lines.append('\n=== Input warnings ===')
        lines.extend(info.warnings or ['None reported.'])
        raw = mds.res.cache_info()
        lines.append('\n=== Memory caches ===')
        lines.append(f'HDF arrays: {raw["bytes"]/1024**2:.2f} / {raw["limit_bytes"]/1024**2:.2f} MiB; '
                     f'{raw["hits"]} hits, {raw["misses"]} misses')
        lines.append(f'Analysis objects: {mds._cache.bytes/1024**2:.2f} / {mds._cache.limit/1024**2:.2f} MiB')
        
        lines.append("\n=== Current Cross Section ===")
        lines.append(f"River: {xs.river}")
        lines.append(f"Reach: {xs.reach}")
        lines.append(f"RS: {xs.station}")
        lines.append(f"Node Name: {xs.name}")
        lines.append(f"Label: {xs.label}")
        try:
            mf = mds.frame(xs_index,'total',mds.rouse_cfg)
            lines.append('\n=== Current analysis warnings ===')
            lines.extend(mf.meta['warnings'] or ['None reported.'])
            lines.append('\n=== Data provenance ===')
            lines.extend(f'{key}: {text}' for key,text in mf.meta['provenance'].items())
            lines.append('\n=== Integrity comparisons ===')
            lines.extend(f'{key}: {value}' for key,value in mf.meta['integrity'].items())
        except Exception as exc:
            lines.append(f'Analysis unavailable: {exc}')
        
        self.txt.setPlainText("\n".join(lines))

