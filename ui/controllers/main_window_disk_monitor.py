"""Disk usage monitor for MainWindow."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.remote.storage_manager import StorageManager


class _DiskUsageWorker(QObject):
    """Run remote disk usage query off the UI thread."""

    finished = pyqtSignal(float, float, float)
    failed = pyqtSignal(str)

    def __init__(self, ssh_service):
        super().__init__()
        self._ssh_service = ssh_service

    def run(self) -> None:
        try:
            mgr = StorageManager(self._ssh_service)
            usage = mgr.get_disk_usage("/h2ometa")
            self.finished.emit(usage.used_gb, usage.total_gb, usage.percent)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindowDiskMonitor:
    """Own timer/thread lifecycle for disk usage refresh."""

    def __init__(self, *, parent, status_bar, locator, logger) -> None:
        self._status_bar = status_bar
        self._locator = locator
        self._logger = logger
        self._timer = QTimer(parent)
        self._timer.setInterval(300_000)
        self._timer.timeout.connect(self.refresh)
        self._disk_thread: Optional[QThread] = None
        self._disk_worker: Optional[_DiskUsageWorker] = None

    @property
    def timer(self) -> QTimer:
        return self._timer

    def on_ssh_changed(self, connected: bool) -> None:
        if connected:
            self._timer.start()
            QTimer.singleShot(100, self.refresh)
        else:
            self._timer.stop()
            self.cleanup()
            self._status_bar.update_disk_usage(0, 0, 0)

    def refresh(self) -> None:
        ssh = self._locator.ssh_service
        if ssh is None or not getattr(ssh, "is_connected", False):
            return

        if self._disk_thread is not None and self._disk_thread.isRunning():
            return

        self.cleanup()

        thread = QThread(self._timer.parent())
        worker = _DiskUsageWorker(ssh)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ready)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self.cleanup)

        self._disk_thread = thread
        self._disk_worker = worker
        thread.start()

    def _on_ready(self, used_gb: float, total_gb: float, percent: float) -> None:
        self._status_bar.update_disk_usage(used_gb, total_gb, percent)

    def _on_failed(self, err: str) -> None:
        self._logger.warning("Failed to refresh disk usage: %s", err)

    def cleanup(self) -> None:
        if self._disk_thread is not None:
            try:
                if self._disk_thread.isRunning():
                    self._disk_thread.quit()
                    self._disk_thread.wait(1000)
            except Exception:
                self._logger.debug("Failed to cleanup disk usage worker", exc_info=True)
        self._disk_worker = None
        self._disk_thread = None

