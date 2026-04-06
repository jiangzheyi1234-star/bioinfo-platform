"""Thread-pool-backed helpers for one-off background tasks."""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.qt_compat import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)


class _Task(QRunnable):
    """Execute a callable in the thread pool and report the outcome by signal."""

    def __init__(
        self,
        task_id: str,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        signals: "TaskRunner",
    ) -> None:
        super().__init__()
        self._task_id = task_id
        self._fn = fn
        self._args = args
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as exc:
            logger.exception("TaskRunner task failed: %s", self._task_id)
            self._signals.task_failed.emit(self._task_id, str(exc))
            return

        self._signals.task_succeeded.emit(self._task_id, result)


class TaskRunner(QObject):
    """Run one-off functions on a shared Qt thread pool."""

    task_succeeded = pyqtSignal(str, object)
    task_failed = pyqtSignal(str, str)

    def __init__(self, max_threads: int = 3, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)

    def submit(self, fn: Callable[..., Any], *args: Any, task_id: str) -> None:
        """Queue a single callable for background execution."""
        self._pool.start(_Task(task_id=task_id, fn=fn, args=args, signals=self))

    def wait_for_done(self, timeout_ms: int = 30000) -> bool:
        """Block until queued tasks finish or the timeout elapses."""
        return self._pool.waitForDone(timeout_ms)
