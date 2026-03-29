from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSlot

logger = logging.getLogger(__name__)


def _safe_emit(signal, *args) -> bool:
    try:
        signal.emit(*args)
        return True
    except RuntimeError:
        logger.debug("Skipped emit on deleted Qt object", exc_info=True)
        return False


class BaseCancellableWorker(QObject):
    """Shared cancellable worker base for thread-bound jobs."""

    def __init__(self):
        super().__init__()
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    def _emit(self, signal_name: str, *args) -> bool:
        if self._cancelled:
            return False
        try:
            signal = getattr(self, signal_name)
        except RuntimeError:
            logger.debug("Skipped worker signal access on deleted Qt object", exc_info=True)
            return False
        return _safe_emit(signal, *args)


def _clear_attr_if_current(parent: QObject, attr_name: str, expected) -> None:
    if getattr(parent, attr_name, None) is expected:
        try:
            delattr(parent, attr_name)
        except AttributeError:
            pass


def launch_worker(
    parent: QObject,
    thread_attr: str,
    worker_attr: str,
    worker: QObject,
    *,
    on_finished=None,
    on_error=None,
) -> QThread:
    """Launch a singleton-style worker using the Qt 6 worker-object pattern."""
    existing_thread = getattr(parent, thread_attr, None)
    if existing_thread is not None and existing_thread.isRunning():
        raise RuntimeError(f"线程仍在运行，拒绝重复启动: {thread_attr}")

    thread = QThread(parent)
    worker.moveToThread(thread)
    setattr(parent, thread_attr, thread)
    setattr(parent, worker_attr, worker)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.error.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(lambda thread=thread: _clear_attr_if_current(parent, thread_attr, thread))
    thread.finished.connect(lambda worker=worker: _clear_attr_if_current(parent, worker_attr, worker))

    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_error is not None:
        worker.error.connect(on_error)

    thread.start()
    return thread


def request_worker_stop(parent: QObject, thread_attr: str, worker_attr: str) -> None:
    """Request cancellation of a singleton-style worker without blocking the UI thread."""
    worker = getattr(parent, worker_attr, None)
    if worker is not None:
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except RuntimeError:
                logger.debug("Worker already deleted during cancellation", exc_info=True)

    thread = getattr(parent, thread_attr, None)
    if thread is not None and thread.isRunning():
        thread.quit()
