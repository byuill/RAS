"""QRunnable worker threads for long-running data assembly/rendering tasks."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot, QThreadPool, Qt

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

class WorkerManager(QObject):
    """Manages thread pool and stale tokens."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._tokens: dict[str, int] = {}
        self._tasks = {}
        
    def next_token(self, category: str) -> int:
        self._tokens[category] = self._tokens.get(category, 0) + 1
        return self._tokens[category]
        
    def is_current(self, category: str, token: int) -> bool:
        return self._tokens.get(category) == token
        
    def submit(self, category: str, fn: Callable, on_success: Callable, on_error: Callable,
               *args, on_discard=None, **kwargs) -> int:
        token = self.next_token(category)
        key = (category,token)
        worker = TaskWorker(key, fn, *args, **kwargs)
        self._tasks[key] = (worker,on_success,on_error,on_discard)
        worker.signals.finished.connect(self._finished, Qt.QueuedConnection)
        worker.signals.error.connect(self._failed, Qt.QueuedConnection)
        self._pool.start(worker)
        return token

    @Slot(object)
    def _finished(self,payload):
        key,result = payload
        _,success,_,discard = self._tasks.pop(key)
        if self.is_current(*key):
            success(result)
        elif discard:
            discard(result)

    @Slot(object)
    def _failed(self,payload):
        key,exc = payload
        _,_,error,_ = self._tasks.pop(key)
        if self.is_current(*key):
            error(exc)

    def invalidate(self,category):
        self.next_token(category)

    def idle(self):
        return self._pool.activeThreadCount() == 0 and not self._tasks
