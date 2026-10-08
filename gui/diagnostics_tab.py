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
        
        lines.append("\n=== Current Cross Section ===")
        lines.append(f"River: {xs.river}")
        lines.append(f"Reach: {xs.reach}")
        lines.append(f"RS: {xs.station}")
        lines.append(f"Node Name: {xs.name}")
        lines.append(f"Label: {xs.label}")
        
        self.txt.setPlainText("\n".join(lines))

