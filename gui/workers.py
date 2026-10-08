"""QRunnable worker threads for long-running data assembly/rendering tasks."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, QThreadPool

logger = logging.getLogger(__name__)

class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(tuple)

class TaskWorker(QRunnable):
    """Executes a function in a background thread."""
    def __init__(self, token: int, fn: Callable, *args, **kwargs):
        super().__init__()
        self.token = token
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit((self.token, result))
        except Exception as exc:
            logger.exception("Worker error")
            self.signals.error.emit((self.token, exc))

class WorkerManager:
    """Manages thread pool and stale tokens."""
    def __init__(self):
        self._pool = QThreadPool.globalInstance()
        self._tokens: dict[str, int] = {}
        
    def next_token(self, category: str) -> int:
        self._tokens[category] = self._tokens.get(category, 0) + 1
        return self._tokens[category]
        
    def is_current(self, category: str, token: int) -> bool:
        return self._tokens.get(category) == token
        
    def submit(self, category: str, fn: Callable, on_success: Callable, on_error: Callable, *args, **kwargs) -> int:
        token = self.next_token(category)
        worker = TaskWorker(token, fn, *args, **kwargs)
        
        def handle_finished(payload):
            tok, result = payload
            if self.is_current(category, tok):
                on_success(result)
                
        def handle_error(payload):
            tok, exc = payload
            if self.is_current(category, tok):
                on_error(exc)
                
        worker.signals.finished.connect(handle_finished)
        worker.signals.error.connect(handle_error)
        self._pool.start(worker)
        return token
