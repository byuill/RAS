"""Dialog windows (e.g. column mapping for local CSV import)."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QLineEdit, QDialogButtonBox, QGridLayout)

from observations.local_import import FIELDS, ColumnChoice

class ColumnMappingDialog(QDialog):
    def __init__(self, columns: list[str], mapping: dict[str, ColumnChoice], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map CSV Columns")
        self.resize(500, 400)
        
        self.columns = ["<None>"] + columns
        self.mapping = mapping
        self.controls = {}  # field: (combo_col, edit_unit)
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Please confirm or adjust the detected column mapping."))
        
        grid = QGridLayout()
        layout.addLayout(grid)
        
        grid.addWidget(QLabel("Target Field"), 0, 0)
        grid.addWidget(QLabel("File Column"), 0, 1)
        grid.addWidget(QLabel("Unit"), 0, 2)
        
        for i, (field, (syn, qty, default_unit)) in enumerate(FIELDS.items(), start=1):
            grid.addWidget(QLabel(field), i, 0)
            
            combo = QComboBox()
            combo.addItems(self.columns)
            
            edit = QLineEdit()
            if not default_unit:
                edit.setEnabled(False)
            
            choice = mapping.get(field)
            if choice:
                if choice.column in self.columns:
                    combo.setCurrentText(choice.column)
                edit.setText(choice.unit)
            
            grid.addWidget(combo, i, 1)
            grid.addWidget(edit, i, 2)
            self.controls[field] = (combo, edit)
            
        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def get_mapping(self) -> dict[str, ColumnChoice]:
        out = {}
        for field, (combo, edit) in self.controls.items():
            col = combo.currentText()
            if col == "<None>":
                col = None
            out[field] = ColumnChoice(column=col, unit=edit.text().strip())
        return out
