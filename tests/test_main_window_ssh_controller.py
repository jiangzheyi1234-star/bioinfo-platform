from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from core.remote.server_capabilities import ServerCapabilities
from ui.controllers.main_window_ssh_controller import MainWindowSSHController


class _DummySignal:
    def __init__(self) -> None:
        self._callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback: Any) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError as exc:
            raise TypeError("callback not connected") from exc


class _FakeSSHService:
    instances: list["_FakeSSHService"] = []

    def __init__(self, initial_client=None, connect_fn=None) -> None:
        self._active_client = initial_client
        self._connect_fn = connect_fn
        self.connection_status_changed = _DummySignal()
        self.is_connected = True
        _FakeSSHService.instances.append(self)

    def run(self, cmd: str, timeout: int = 10):
        return 0, "", ""


class _StatusBar:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def update_ssh_status(self, connected: bool) -> None:
        self.states.append(connected)


@dataclass
class _Recorder:
    values: list[Any]

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs:
            self.values.append((args, kwargs))
        elif len(args) == 1:
            self.values.append(args[0])
        else:
            self.values.append(args)


class _Locator:
    def __init__(self) -> None:
        self.ssh_service = None
        self.conda_executable = "/old/path"
        self.server_capabilities = None
        self.server_capability_error = ""


class _Client:
    pass


class _SettingsPage:
    def __init__(self) -> None:
        self.ssh_card = SimpleNamespace(
            last_stable_config={
                "ip": "10.0.0.1",
                "port": 22,
                "user": "root",
                "pwd": "secret",
                "use_key": False,
                "key_file": "",
            }
        )


def _build_controller(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    _FakeSSHService.instances.clear()
    monkeypatch.setattr(module, "SSHService", _FakeSSHService)

    locator = _Locator()
    status_bar = _StatusBar()
    status_cb = _Recorder([])
    disk_cb = _Recorder([])
    notify_cb = _Recorder([])
    controller = MainWindowSSHController(
        locator=locator,
        settings_page=_SettingsPage(),
        status_bar=status_bar,
        on_ssh_status_changed=status_cb,
        on_ssh_changed_for_disk=disk_cb,
        notify_pages_context_changed=notify_cb,
    )
    monkeypatch.setattr(controller, "_start_capability_bind_job", lambda **kwargs: None)
    return controller, locator, status_bar, disk_cb, notify_cb


def test_apply_active_client_none_clears_ssh_and_conda(monkeypatch):
    controller, locator, status_bar, disk_cb, notify_cb = _build_controller(monkeypatch)
    locator.conda_executable = "/home/user/.h2ometa/conda/bin/conda"
    locator.server_capabilities = ServerCapabilities("x86_64", True, False, True, True, 20.0)
    locator.server_capability_error = "old error"

    result = controller.apply_active_client(None)

    assert result is None
    assert locator.ssh_service is None
    assert locator.conda_executable == ""
    assert locator.server_capabilities is None
    assert locator.server_capability_error == ""
    assert status_bar.states[-1] is False
    assert disk_cb.values[-1] is False
    assert len(notify_cb.values) == 1


def test_apply_active_client_starts_capability_bind_and_clears_stale_conda(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)

    cap_started: list[dict[str, Any]] = []
    monkeypatch.setattr(controller, "_start_capability_bind_job", lambda **kwargs: cap_started.append(kwargs))
    locator.conda_executable = "/home/root/.h2ometa/conda/bin/conda"
    locator.server_capabilities = ServerCapabilities("x86_64", True, False, True, True, 20.0)
    locator.server_capability_error = "old error"

    controller.apply_active_client(_Client())

    assert locator.conda_executable == ""
    assert locator.server_capabilities is None
    assert locator.server_capability_error == ""
    assert len(cap_started) == 1
    assert cap_started[0]["token"] == controller._capability_bind_token


def test_capability_bind_worker_success(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    caps = ServerCapabilities("x86_64", True, False, True, True, 20.0)
    monkeypatch.setattr(module, "run_preflight", lambda _run_fn: caps)

    worker = module.CapabilityBindWorker(ssh=_FakeSSHService(initial_client=_Client()))
    finished: list[object] = []
    errors: list[str] = []
    worker.finished.connect(lambda payload: finished.append(payload))
    worker.error.connect(lambda message: errors.append(message))
    worker.run()

    assert finished == [caps]
    assert errors == []


def test_capability_bind_worker_error(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    monkeypatch.setattr(module, "run_preflight", lambda _run_fn: (_ for _ in ()).throw(RuntimeError("boom")))

    worker = module.CapabilityBindWorker(ssh=_FakeSSHService(initial_client=_Client()))
    finished: list[object] = []
    errors: list[str] = []
    worker.finished.connect(lambda payload: finished.append(payload))
    worker.error.connect(lambda message: errors.append(message))
    worker.run()

    assert finished == []
    assert errors == ["boom"]


def test_on_capability_bind_finished_updates_locator(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)
    controller.apply_active_client(_Client())
    caps = ServerCapabilities("x86_64", True, False, True, True, 20.0)

    controller._on_capability_bind_finished(controller._capability_bind_token, caps)

    assert locator.server_capabilities == caps
    assert locator.server_capability_error == ""


def test_on_capability_bind_error_updates_locator(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)
    controller.apply_active_client(_Client())

    controller._on_capability_bind_error(controller._capability_bind_token, "远端缺少 screen")

    assert locator.server_capabilities is None
    assert locator.server_capability_error == "远端缺少 screen"
