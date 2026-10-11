"""Background worker management for PySide6 GUI operations."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(object)
    progress = Signal(float, str)


class Worker(QRunnable):
    def __init__(self, func):
        super().__init__()
        self.func = func
        self.signals = WorkerSignals()

    def _emit_progress(self, *args):
        try:
            if not args:
                self.signals.progress.emit(-1.0, "")
            elif len(args) == 1:
                if isinstance(args[0], (int, float)):
                    self.signals.progress.emit(float(args[0]), "")
                else:
                    self.signals.progress.emit(-1.0, str(args[0]))
            else:
                self.signals.progress.emit(float(args[0]), str(args[1]))
        except Exception:
            pass

    def run(self):
        try:
            try:
                result = self.func(self._emit_progress)
            except TypeError:
                result = self.func()
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(e)


class WorkerManager:
    def __init__(self, parent=None):
        self.parent = parent
        self.pool = QThreadPool.globalInstance()
        self._active_workers = set()

    def submit(self, name, func, success, error, progress=None):
        worker = Worker(func)
        self._active_workers.add(worker)

        def on_success(result):
            self._active_workers.discard(worker)
            success(result)

        def on_error(err):
            self._active_workers.discard(worker)
            error(err)

        worker.signals.finished.connect(on_success)
        worker.signals.error.connect(on_error)
        if progress:
            worker.signals.progress.connect(progress)
        self.pool.start(worker)

    def idle(self):
        return len(self._active_workers) == 0
