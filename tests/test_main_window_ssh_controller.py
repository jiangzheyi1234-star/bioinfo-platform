from __future__ import annotations

from copy import deepcopy
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
    run_handler = staticmethod(lambda _cmd, _timeout=10: (0, "", ""))
    instances: list["_FakeSSHService"] = []

    def __init__(self, initial_client=None, connect_fn=None) -> None:
        self._active_client = initial_client
        self._connect_fn = connect_fn
        self.connection_status_changed = _DummySignal()
        self.is_connected = True
        self.run_calls: list[tuple[str, int]] = []
        _FakeSSHService.instances.append(self)

    def run(self, cmd: str, timeout: int = 10):
        self.run_calls.append((cmd, timeout))
        return _FakeSSHService.run_handler(cmd, timeout)


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


class _HostKey:
    def get_fingerprint(self) -> bytes:
        return bytes.fromhex("a1" * 16)


class _Transport:
    def get_remote_server_key(self):
        return _HostKey()


class _Client:
    def get_transport(self):
        return _Transport()


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


def _identity() -> str:
    return f"fp:{'a1' * 16}|u:root|p:22"


def _build_controller(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    _FakeSSHService.instances.clear()
    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (0, "", ""))
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


def _capture_worker(worker):
    done: list[dict[str, Any]] = []
    errors: list[tuple[str, dict[str, Any]]] = []
    worker.finished.connect(lambda payload: done.append(payload))
    worker.error.connect(lambda message, context: errors.append((message, context)))
    worker.run()
    return done, errors


def _config_state(initial_profiles: dict[str, dict] | None = None):
    state = {
        "version": 2,
        "runtime": {"conda_profiles": deepcopy(initial_profiles or {})},
    }
    saved: list[dict] = []

    def get_config():
        return deepcopy(state)

    def save_config(cfg: dict) -> None:
        state.clear()
        state.update(deepcopy(cfg))
        saved.append(deepcopy(cfg))

    return get_config, save_config, state, saved


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


def test_conda_bind_worker_cache_hit_validated_skips_detect(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    cached = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, _state, _saved = _config_state({_identity(): {"conda_executable": cached}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    detect_calls = {"count": 0}

    def _detect_should_not_run(_run_fn):
        detect_calls["count"] += 1
        raise AssertionError("detect should not run on valid cache hit")

    monkeypatch.setattr(module.env_detector, "detect", _detect_should_not_run)
    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (0, "conda 24.9.0", ""))
    worker = module.CondaBindWorker(
        ssh=_FakeSSHService(initial_client=_Client()),
        client=_Client(),
        ssh_cfg=_SettingsPage().ssh_card.last_stable_config,
        token=7,
    )

    finished, errors = _capture_worker(worker)

    assert errors == []
    assert finished == [
        {
            "token": 7,
            "identity": _identity(),
            "fingerprint": "a1" * 16,
            "user": "root",
            "port": 22,
            "host": "10.0.0.1",
            "resolved_executable": cached,
            "profile_action": "save",
            "status": "ok",
            "source": "cache_hit",
        }
    ]
    assert detect_calls["count"] == 0
    assert worker._ssh.run_calls[0][0] == f"{cached} --version"


def test_conda_bind_worker_cache_invalid_falls_back_to_detect(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    stale = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, _state, _saved = _config_state({_identity(): {"conda_executable": stale}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    detected = "/home/root/.h2ometa/conda/bin/conda"
    detect_calls = {"count": 0}

    monkeypatch.setattr(
        module.env_detector,
        "detect",
        lambda _run_fn: detect_calls.__setitem__("count", detect_calls["count"] + 1)
        or SimpleNamespace(status=module.CondaStatus.OK, executable=detected, version="24.9.0"),
    )
    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (1, "", "missing"))
    worker = module.CondaBindWorker(
        ssh=_FakeSSHService(initial_client=_Client()),
        client=_Client(),
        ssh_cfg=_SettingsPage().ssh_card.last_stable_config,
        token=11,
    )

    finished, errors = _capture_worker(worker)

    assert errors == []
    assert detect_calls["count"] == 1
    assert finished[0]["status"] == "ok"
    assert finished[0]["source"] == "cache_invalid"
    assert finished[0]["resolved_executable"] == detected


def test_conda_bind_worker_detect_not_found_returns_remove(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    stale = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, _state, _saved = _config_state({_identity(): {"conda_executable": stale}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (1, "", "missing"))
    monkeypatch.setattr(
        module.env_detector,
        "detect",
        lambda _run_fn: SimpleNamespace(
            status=module.CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
        ),
    )
    worker = module.CondaBindWorker(
        ssh=_FakeSSHService(initial_client=_Client()),
        client=_Client(),
        ssh_cfg=_SettingsPage().ssh_card.last_stable_config,
        token=13,
    )

    finished, errors = _capture_worker(worker)

    assert errors == []
    assert finished[0]["status"] == "not_found"
    assert finished[0]["profile_action"] == "remove"


def test_conda_bind_worker_detect_exception_emits_error(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    stale = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, state, _saved = _config_state({_identity(): {"conda_executable": stale}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (1, "", "missing"))
    monkeypatch.setattr(module.env_detector, "detect", lambda _run_fn: (_ for _ in ()).throw(RuntimeError("boom")))
    worker = module.CondaBindWorker(
        ssh=_FakeSSHService(initial_client=_Client()),
        client=_Client(),
        ssh_cfg=_SettingsPage().ssh_card.last_stable_config,
        token=17,
    )

    finished, errors = _capture_worker(worker)

    assert finished == []
    assert errors
    assert errors[0][0] == "boom"
    assert errors[0][1]["token"] == 17
    assert errors[0][1]["profile_action"] == "remove"
    assert _identity() in state["runtime"]["conda_profiles"]


def test_apply_active_client_starts_async_conda_bind_and_clears_stale_value(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)

    started: list[dict[str, Any]] = []
    cap_started: list[dict[str, Any]] = []

    def fake_start(*, client, ssh_cfg, token):
        started.append({"client": client, "ssh_cfg": ssh_cfg, "token": token})

    monkeypatch.setattr(controller, "_start_conda_bind_job", fake_start)
    monkeypatch.setattr(controller, "_start_capability_bind_job", lambda **kwargs: cap_started.append(kwargs))
    locator.conda_executable = "/home/root/.h2ometa/conda/bin/conda"
    locator.server_capabilities = ServerCapabilities("x86_64", True, False, True, True, 20.0)
    locator.server_capability_error = "old error"

    controller.apply_active_client(_Client())

    assert locator.conda_executable == ""
    assert locator.server_capabilities is None
    assert locator.server_capability_error == ""
    assert len(started) == 1
    assert len(cap_started) == 1
    assert started[0]["token"] == controller._conda_bind_token


def test_on_conda_bind_finished_writes_locator_and_profile(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    get_cfg, save_cfg, state, saved = _config_state({})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)
    monkeypatch.setattr(controller, "_start_conda_bind_job", lambda **kwargs: None)

    controller.apply_active_client(_Client())
    payload = {
        "token": controller._conda_bind_token,
        "identity": _identity(),
        "fingerprint": "a1" * 16,
        "user": "root",
        "port": 22,
        "host": "10.0.0.1",
        "resolved_executable": "/home/root/.h2ometa/conda/bin/conda",
        "profile_action": "save",
        "status": "ok",
        "source": "detect",
    }

    controller._on_conda_bind_finished(payload)

    assert locator.conda_executable == payload["resolved_executable"]
    assert saved
    assert state["runtime"]["conda_profiles"][_identity()]["conda_executable"] == payload["resolved_executable"]


def test_on_conda_bind_finished_ignores_stale_token(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)
    monkeypatch.setattr(controller, "_start_conda_bind_job", lambda **kwargs: None)
    controller.apply_active_client(_Client())
    current = controller._conda_bind_token

    controller._on_conda_bind_finished(
        {
            "token": current - 1,
            "identity": _identity(),
            "resolved_executable": "/home/root/.h2ometa/conda/bin/conda",
            "profile_action": "save",
            "status": "ok",
        }
    )

    assert locator.conda_executable == ""


def test_on_conda_bind_error_clears_and_removes_profile(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    get_cfg, save_cfg, state, _saved = _config_state({_identity(): {"conda_executable": "/stale"}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)
    monkeypatch.setattr(controller, "_start_conda_bind_job", lambda **kwargs: None)
    controller.apply_active_client(_Client())
    locator.conda_executable = "/home/root/.h2ometa/conda/bin/conda"

    controller._on_conda_bind_error(
        "boom",
        {
            "token": controller._conda_bind_token,
            "identity": _identity(),
            "profile_action": "remove",
        },
    )

    assert locator.conda_executable == ""
    assert _identity() not in state["runtime"]["conda_profiles"]


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
    monkeypatch.setattr(controller, "_start_conda_bind_job", lambda **kwargs: None)
    controller.apply_active_client(_Client())
    caps = ServerCapabilities("x86_64", True, False, True, True, 20.0)

    controller._on_capability_bind_finished(controller._capability_bind_token, caps)

    assert locator.server_capabilities == caps
    assert locator.server_capability_error == ""


def test_on_capability_bind_error_updates_locator(monkeypatch):
    controller, locator, *_ = _build_controller(monkeypatch)
    monkeypatch.setattr(controller, "_start_conda_bind_job", lambda **kwargs: None)
    controller.apply_active_client(_Client())

    controller._on_capability_bind_error(controller._capability_bind_token, "远端缺少 screen")

    assert locator.server_capabilities is None
    assert locator.server_capability_error == "远端缺少 screen"
