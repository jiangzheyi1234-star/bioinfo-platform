from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QDialog


def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drain_events(app, attempts: int = 20, delay: float = 0.01) -> None:
    for _ in range(attempts):
        app.processEvents()
        time.sleep(delay)


def test_ssh_diagnostic_dialog_runs_worker_off_main_thread(monkeypatch):
    from ui.widgets import ssh_settings_components as module

    app = qapp()
    seen_threads = []

    def fake_run(self):
        seen_threads.append(QThread.currentThread())
        self.log.emit("ok")
        self.done.emit()

    monkeypatch.setattr(module.SSHDiagnosticWorker, "run", fake_run)
    dlg = module.SSHDiagnosticDialog("127.0.0.1", 22, "root", "pwd")
    _drain_events(app)

    assert seen_threads
    assert seen_threads[0] != app.thread()
    assert dlg._diagnostics_done is True
    assert dlg._thread is None


def test_ssh_diagnostic_dialog_close_while_running_waits_for_thread(monkeypatch):
    from ui.widgets import ssh_settings_components as module

    app = qapp()
    started = threading.Event()
    release = threading.Event()

    def fake_run(self):
        started.set()
        release.wait(timeout=2)
        self.done.emit()

    monkeypatch.setattr(module.SSHDiagnosticWorker, "run", fake_run)
    dlg = module.SSHDiagnosticDialog("127.0.0.1", 22, "root", "pwd")

    deadline = time.time() + 1.0
    while not started.is_set() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)

    dlg._on_close_requested()
    assert dlg._close_requested is True
    assert dlg.result() == int(QDialog.DialogCode.Rejected)

    release.set()
    _drain_events(app, attempts=40)

    assert dlg._diagnostics_running is False
    assert dlg.result() == int(QDialog.DialogCode.Accepted)
