from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

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

    def __init__(self, client_provider, connect_fn=None) -> None:
        self._client_provider = client_provider
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
    return controller, locator, status_bar, disk_cb, notify_cb


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

    result = controller.apply_active_client(None)

    assert result is None
    assert locator.ssh_service is None
    assert locator.conda_executable == ""
    assert status_bar.states[-1] is False
    assert disk_cb.values[-1] is False
    assert len(notify_cb.values) == 1


def test_apply_active_client_cache_hit_validated_skips_detect(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    cached = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, _state, saved = _config_state({_identity(): {"conda_executable": cached}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    detect_calls = {"count": 0}

    def _detect_should_not_run(_run_fn):
        detect_calls["count"] += 1
        raise AssertionError("detect should not run on valid cache hit")

    monkeypatch.setattr(module.env_detector, "detect", _detect_should_not_run)
    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (0, "conda 24.9.0", ""))

    controller.apply_active_client(_Client())

    assert locator.conda_executable == cached
    assert detect_calls["count"] == 0
    assert saved, "cache hit should refresh timestamp/profile"
    assert _FakeSSHService.instances[-1].run_calls[0][0] == f"{cached} --version"


def test_apply_active_client_cache_miss_runs_detect_and_writes_profile(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    get_cfg, save_cfg, state, saved = _config_state({})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    detected = "/home/root/.h2ometa/conda/bin/conda"
    monkeypatch.setattr(
        module.env_detector,
        "detect",
        lambda _run_fn: SimpleNamespace(
            status=module.CondaStatus.OK,
            executable=detected,
            version="24.9.0",
        ),
    )

    controller.apply_active_client(_Client())

    assert locator.conda_executable == detected
    assert saved
    profile = state["runtime"]["conda_profiles"][_identity()]
    assert profile["conda_executable"] == detected
    assert profile["fingerprint"] == "a1" * 16
    assert profile["user"] == "root"
    assert profile["port"] == 22
    assert profile["host"] == "10.0.0.1"


def test_apply_active_client_cache_invalid_falls_back_to_detect(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    stale = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, state, _saved = _config_state({_identity(): {"conda_executable": stale}})
    monkeypatch.setattr(module, "get_config", get_cfg)
    monkeypatch.setattr(module, "save_config", save_cfg)

    _FakeSSHService.run_handler = staticmethod(lambda _cmd, _timeout=10: (1, "", "missing"))
    refreshed = "/home/root/.h2ometa/conda/bin/conda"
    detect_calls = {"count": 0}

    def _detect(_run_fn):
        detect_calls["count"] += 1
        return SimpleNamespace(status=module.CondaStatus.OK, executable=refreshed, version="24.9.1")

    monkeypatch.setattr(module.env_detector, "detect", _detect)

    controller.apply_active_client(_Client())

    assert detect_calls["count"] == 1
    assert locator.conda_executable == refreshed
    assert state["runtime"]["conda_profiles"][_identity()]["conda_executable"] == refreshed


def test_apply_active_client_detect_failure_clears_and_removes_profile(monkeypatch):
    import ui.controllers.main_window_ssh_controller as module

    controller, locator, *_ = _build_controller(monkeypatch)
    stale = "/home/root/.h2ometa/conda/bin/conda"
    get_cfg, save_cfg, state, _saved = _config_state({_identity(): {"conda_executable": stale}})
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

    controller.apply_active_client(_Client())

    assert locator.conda_executable == ""
    assert _identity() not in state["runtime"]["conda_profiles"]
