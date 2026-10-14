"""Package-local Qt canvas and workers for standalone folder launches.

Import explicit Qt canvas classes without changing Matplotlib's global backend.
No imports depend on the calibration application's top-level ``gui`` package.
"""
import logging

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget


logger = logging.getLogger(__name__)


class MplCanvas(QWidget):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        super().__init__(parent)
        self.figure = Figure(figsize=(width, height), dpi=dpi)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def draw_idle(self):
        self.canvas.draw_idle()


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(object)


class TaskWorker(QRunnable):
    def __init__(self, key, fn):
        super().__init__()
        self.key, self.fn = key, fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:
            logger.exception('Boundary workbench operation failed')
            self.signals.error.emit((self.key, exc))
        else:
            self.signals.finished.emit((self.key, result))


class WorkerManager(QObject):
    """Keep workers alive and deliver their callbacks on the GUI thread."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._tokens = {}
        self._tasks = {}

    def submit(self, category, fn, on_success, on_error):
        token = self._tokens.get(category, 0)+1
        self._tokens[category] = token
        key = (category, token)
        worker = TaskWorker(key, fn)
        self._tasks[key] = (worker, on_success, on_error)
        worker.signals.finished.connect(self._finished, Qt.QueuedConnection)
        worker.signals.error.connect(self._failed, Qt.QueuedConnection)
        self._pool.start(worker)

    @Slot(object)
    def _finished(self, payload):
        key, result = payload
        _, success, _ = self._tasks.pop(key)
        if self._tokens.get(key[0]) == key[1]:
            success(result)

    @Slot(object)
    def _failed(self, payload):
        key, exc = payload
        _, _, error = self._tasks.pop(key)
        if self._tokens.get(key[0]) == key[1]:
            error(exc)

    def idle(self):
        return self._pool.activeThreadCount() == 0 and not self._tasks
