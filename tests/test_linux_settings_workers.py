import pytest
import time


pytestmark = pytest.mark.ui


def test_conda_detect_worker_cancel_suppresses_emit(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import CondaDetectWorker

    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.env_detector.detect",
        lambda ssh_run_fn: {"status": "ok"},
    )

    worker = CondaDetectWorker(lambda *args, **kwargs: (0, "", ""))
    received = []
    worker.finished.connect(lambda result: received.append(result))

    worker.cancel()
    worker.run()

    assert received == []


def test_env_batch_check_worker_uses_ssh_run_fn(monkeypatch):
    from ui.widgets.linux_settings_card import EnvBatchCheckWorker

    called = {"fn": None}

    def fake_check_all_envs(ssh_run_fn, tools, conda_executable):
        called["fn"] = ssh_run_fn
        rc, out, err = ssh_run_fn("echo ok", 5)
        assert rc == 0
        assert out == "ok"
        assert err == ""
        return [], ["/home/user/.h2ometa/conda/envs/demo"]

    monkeypatch.setattr("ui.widgets.linux_settings_card.check_all_envs", fake_check_all_envs)

    worker = EnvBatchCheckWorker(
        ssh_run_fn=lambda cmd, timeout=30: (0, "ok", ""),
        tools=[{"id": "demo", "conda_env": "demo"}],
        conda_executable="/home/user/.h2ometa/conda/bin/conda",
    )
    done_payload = []
    worker.finished.connect(lambda payload: done_payload.append(payload))
    worker.run()

    assert called["fn"] is not None
    assert done_payload == [["/home/user/.h2ometa/conda/envs/demo"]]


def test_get_existing_env_paths_uses_batch_checker(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    card = LinuxSettingsCard()
    card._conda_executable = "/home/user/.h2ometa/conda/bin/conda"
    card.set_ssh_service(type("S", (), {"is_connected": True, "run": staticmethod(lambda cmd, timeout=10: (0, "{}", ""))})())

    called = {"count": 0}

    def fake_get_existing_env_paths(ssh_run_fn, conda_executable):
        called["count"] += 1
        assert callable(ssh_run_fn)
        assert conda_executable == "/home/user/.h2ometa/conda/bin/conda"
        return {"/home/user/.h2ometa/conda/envs/a"}

    monkeypatch.setattr("ui.widgets.linux_settings_card.get_existing_env_paths", fake_get_existing_env_paths)
    paths = card._get_existing_env_paths()

    assert called["count"] == 1
    assert "/home/user/.h2ometa/conda/envs/a" in paths


def test_set_values_rejects_non_managed_conda_path(qapp):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    card = LinuxSettingsCard()
    card.set_values(conda_executable="/home/user/miniforge3/bin/conda", auto_installed=True)

    values = card.get_values()
    assert values["conda_executable"] == ""
    assert values["auto_installed"] is False


def test_conda_not_found_startup_uses_silent_install(qapp, monkeypatch):
    from core.environment.env_detector import CondaStatus
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._detect_interactive_request = False

    calls = {"silent": 0, "prompt": 0}
    monkeypatch.setattr(card, "_start_miniforge_install_silent", lambda: calls.__setitem__("silent", calls["silent"] + 1))
    monkeypatch.setattr(card, "_prompt_miniforge_install", lambda: calls.__setitem__("prompt", calls["prompt"] + 1))

    result = type("R", (), {"status": CondaStatus.NOT_FOUND})()
    card._on_conda_detected(result)

    assert calls["silent"] == 1
    assert calls["prompt"] == 0


def test_conda_not_found_interactive_prompts_install(qapp, monkeypatch):
    from core.environment.env_detector import CondaStatus
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._detect_interactive_request = True

    calls = {"silent": 0, "prompt": 0}
    monkeypatch.setattr(card, "_start_miniforge_install_silent", lambda: calls.__setitem__("silent", calls["silent"] + 1))
    monkeypatch.setattr(card, "_prompt_miniforge_install", lambda: calls.__setitem__("prompt", calls["prompt"] + 1))

    result = type("R", (), {"status": CondaStatus.NOT_FOUND})()
    card._on_conda_detected(result)

    assert calls["silent"] == 0
    assert calls["prompt"] == 1


def test_poll_miniforge_running_but_session_dead_fails(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card.active_client = object()
    card._miniforge_installing = True
    card._miniforge_task_dir = "~/.h2ometa/runtime/miniforge_bootstrap"
    card.set_ssh_service(type("S", (), {"is_connected": True, "run": staticmethod(lambda cmd, timeout=10: (0, "", ""))})())
    stale = str(int(time.time()) - 3600)

    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.check_status",
        lambda *args, **kwargs: {"status": "RUNNING", "exit_code": "", "heartbeat": stale},
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.is_session_alive",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.read_log",
        lambda *args, **kwargs: "tail log",
    )

    failed = {"message": ""}
    monkeypatch.setattr(card, "_prompt_miniforge_install_failed", lambda message: failed.__setitem__("message", message))

    card._poll_miniforge_status()

    assert card._miniforge_installing is False
    assert "会话已退出" in failed["message"]


def test_poll_miniforge_running_dead_session_but_fresh_heartbeat_keeps_running(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card.active_client = object()
    card._miniforge_installing = True
    card._miniforge_task_dir = "~/.h2ometa/runtime/miniforge_bootstrap"
    card.set_ssh_service(type("S", (), {"is_connected": True, "run": staticmethod(lambda cmd, timeout=10: (0, "", ""))})())

    fresh = str(int(time.time()))
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.check_status",
        lambda *args, **kwargs: {"status": "RUNNING", "exit_code": "", "heartbeat": fresh},
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.is_session_alive",
        lambda *args, **kwargs: False,
    )

    failed = {"count": 0}
    monkeypatch.setattr(card, "_prompt_miniforge_install_failed", lambda message: failed.__setitem__("count", failed["count"] + 1))

    card._poll_miniforge_status()

    assert card._miniforge_installing is True
    assert failed["count"] == 0


def test_poll_miniforge_stale_heartbeat_and_dead_session_fails(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card.active_client = object()
    card._miniforge_installing = True
    card._miniforge_task_dir = "~/.h2ometa/runtime/miniforge_bootstrap"
    card.set_ssh_service(type("S", (), {"is_connected": True, "run": staticmethod(lambda cmd, timeout=10: (0, "", ""))})())

    stale = str(int(time.time()) - 3600)
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.check_status",
        lambda *args, **kwargs: {"status": "", "exit_code": "", "heartbeat": stale},
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.is_session_alive",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.read_log",
        lambda *args, **kwargs: "tail log",
    )

    failed = {"message": ""}
    monkeypatch.setattr(card, "_prompt_miniforge_install_failed", lambda message: failed.__setitem__("message", message))

    card._poll_miniforge_status()

    assert card._miniforge_installing is False
    assert "心跳超时" in failed["message"]


def test_poll_miniforge_done_emits_install_task_success(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card.active_client = object()
    card._miniforge_installing = True
    card._miniforge_task_dir = "~/.h2ometa/runtime/miniforge_bootstrap"
    card.set_ssh_service(type("S", (), {"is_connected": True, "run": staticmethod(lambda cmd, timeout=10: (0, "", ""))})())

    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.check_status",
        lambda *args, **kwargs: {"status": "DONE", "exit_code": "0", "heartbeat": str(int(time.time()))},
    )
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.miniforge_bootstrap.is_session_alive",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr("ui.widgets.linux_settings_card.Toast.show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(card, "_ensure_conda_ready", lambda interactive=False: None)

    events = []
    card.install_task_event.connect(lambda payload: events.append(payload))
    card._poll_miniforge_status()

    assert any(e.get("task_id") == "bootstrap:miniforge" and e.get("state") == "success" for e in events)


def test_tool_install_success_emits_install_task_event(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._tools = [{"id": "fastp", "name": "fastp", "conda_env": "fastp_env"}]
    monkeypatch.setattr("ui.widgets.linux_settings_card.Toast.show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr("ui.widgets.linux_settings_card.QTimer.singleShot", lambda _ms, _fn: None)

    events = []
    card.install_task_event.connect(lambda payload: events.append(payload))
    card._on_install_succeeded("fastp")

    assert any(
        e.get("task_id") == "tool_env:fastp" and e.get("state") == "success"
        for e in events
    )
