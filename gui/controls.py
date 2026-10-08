"""Custom UI controls (XS selector, date range slider, etc)."""
from __future__ import annotations

import datetime
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtWidgets import (QComboBox, QWidget, QHBoxLayout, QLabel, 
                               QDateEdit, QPushButton, QSlider, QCompleter)

class SearchableComboBox(QComboBox):
    """A combo box that supports typing to filter items."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.completer().setFilterMode(Qt.MatchContains)

class DateRangeSlider(QWidget):
    """Dual slider for date ranges (start and end). Note: using simplified single slider or two for now."""
    rangeChanged = Signal(datetime.date, datetime.date)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_date = datetime.date(2000, 1, 1)
        self._max_date = datetime.date(2025, 1, 1)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.dateChanged.connect(self._on_date_changed)
        
        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.dateChanged.connect(self._on_date_changed)
        
        self.btn_full = QPushButton("Full Record")
        self.btn_full.clicked.connect(self._set_full)
        
        self.btn_prev = QPushButton("< Year")
        self.btn_prev.clicked.connect(self._shift_prev)
        
        self.btn_next = QPushButton("Year >")
        self.btn_next.clicked.connect(self._shift_next)
        
        layout.addWidget(QLabel("Start:"))
        layout.addWidget(self.start_edit)
        layout.addWidget(QLabel("End:"))
        layout.addWidget(self.end_edit)
        layout.addWidget(self.btn_full)
        layout.addWidget(self.btn_prev)
        layout.addWidget(self.btn_next)
        
    def setBounds(self, start: datetime.date, end: datetime.date):
        self.start_edit.blockSignals(True)
        self.end_edit.blockSignals(True)
        
        self._min_date = start
        self._max_date = end
        
        # update bounds
        qstart = QDate(start.year, start.month, start.day)
        qend = QDate(end.year, end.month, end.day)
        self.start_edit.setMinimumDate(qstart)
        self.start_edit.setMaximumDate(qend)
        self.end_edit.setMinimumDate(qstart)
        self.end_edit.setMaximumDate(qend)
        
        self.start_edit.setDate(qstart)
        self.end_edit.setDate(qend)
        
        self.start_edit.blockSignals(False)
        self.end_edit.blockSignals(False)
        self.rangeChanged.emit(start, end)
        
    def _on_date_changed(self):
        s = self.start_edit.date().toPython()
        e = self.end_edit.date().toPython()
        if s > e:
            # force consistency
            if self.sender() == self.start_edit:
                self.end_edit.setDate(self.start_edit.date())
            else:
                self.start_edit.setDate(self.end_edit.date())
            return
        self.rangeChanged.emit(s, e)
        
    def _set_full(self):
        self.start_edit.setDate(QDate(self._min_date.year, self._min_date.month, self._min_date.day))
        self.end_edit.setDate(QDate(self._max_date.year, self._max_date.month, self._max_date.day))
        
    def _shift_prev(self):
        s = self.start_edit.date().addYears(-1)
        e = self.end_edit.date().addYears(-1)
        if s < self.start_edit.minimumDate():
            return
        self.start_edit.setDate(s)
        self.end_edit.setDate(e)
        
    def _shift_next(self):
        s = self.start_edit.date().addYears(1)
        e = self.end_edit.date().addYears(1)
        if e > self.end_edit.maximumDate():
            return
        self.start_edit.setDate(s)
        self.end_edit.setDate(e)
