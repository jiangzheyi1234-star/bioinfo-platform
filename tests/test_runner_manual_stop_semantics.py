from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator


def _stopped_runner_config() -> tuple[str, dict]:
    server_id = f"srv_{uuid.uuid5(uuid.NAMESPACE_DNS, '192.0.2.10:22:tester').hex[:12]}"
    return server_id, {
        "ssh": {
            "auth_mode": "key_file",
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {
            server_id: {
                "bootstrap_version": "phase1-test",
                "runner_mode": "background_process",
                "tunnel_port": 18000,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "runner_stop_intent": {
                    "schemaVersion": "h2ometa.runner-stop-intent.v1",
                    "active": True,
                    "reasonCode": "RUNNER_STOPPED",
                    "serverId": server_id,
                    "stoppedAt": "2026-04-21T12:00:00Z",
                    "source": "explicit-stop",
                },
                "last_health_snapshot": {
                    "serverId": server_id,
                    "state": "stopped",
                    "startup": {"ok": True, "message": "Remote runner stop command ran."},
                    "live": {"ok": False, "message": "Remote runner is stopped."},
                    "ready": {"ok": False, "message": "Remote runner was manually stopped."},
                    "reasonCode": "RUNNER_STOPPED",
                    "checkedAt": "2026-04-21T12:00:00Z",
                },
            }
        },
    }


def test_submit_run_does_not_restart_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise AssertionError("stopped runner submission should not read remote health")

        def bootstrap(self, **_kwargs):
            raise AssertionError("stopped runner submission should not bootstrap")

        def call_remote_endpoint(self, **_kwargs):
            raise AssertionError("stopped runner submission should not call remote endpoints")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.submit_run(
            {
                "serverId": server_id,
                "requestId": "req_stopped_runner",
                "runSpec": {"pipelineId": "moving-pictures-16s-rulegraph-v1"},
            }
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOPPED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_explicit_ensure_runner_rejects_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise AssertionError("manual stop ensure should not read remote health")

        def bootstrap(self, **_kwargs):
            raise AssertionError("manual stop ensure should not bootstrap")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.ensure_remote_runner_ready(server_id)

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOPPED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_snapshot_only_stop_state_requires_explicit_start_without_autostart(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    del cfg["servers"][server_id]["runner_stop_intent"]
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise AssertionError("unsupported stop state must not read remote health")

        def bootstrap(self, **_kwargs):
            raise AssertionError("unsupported stop state must not bootstrap through ensure")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.ensure_remote_runner_ready(server_id)

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOP_INTENT_REQUIRED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_existing_runner_diagnostics_rejects_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def get_execution_diagnostics(self, **_kwargs):
            raise AssertionError("manual stop diagnostics should not touch the remote runner")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.get_runner_execution_diagnostics(server_id)

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOPPED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_upgrade_runner_rejects_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def bootstrap(self, **_kwargs):
            raise AssertionError("manual stop upgrade should not bootstrap")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.upgrade_remote_runner(server_id)

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOPPED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_rotate_runner_token_rejects_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    class FailIfCalledRemoteRunnerManager:
        def rotate_token(self, **_kwargs):
            raise AssertionError("manual stop token rotation should not restart the runner")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    with pytest.raises(RuntimeServiceError) as raised:
        service.rotate_server_token(server_id)

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == "RUNNER_STOPPED"
    assert raised.value.detail["nextAction"] == "START_RUNNER"


def test_server_health_projects_manual_stop_while_ssh_is_disconnected(monkeypatch) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True

    class FailIfCalledRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise AssertionError("offline manual stop health should not touch remote runner")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    server = service.list_servers()[0]
    health = service.get_server_health(server_id)

    assert server["connected"] is False
    assert server["runner"]["state"] == "stopped"
    assert server["runner"]["reasonCode"] == "RUNNER_STOPPED"
    assert server["reasonCode"] == "RUNNER_STOPPED"
    assert health["reasonCode"] == "RUNNER_STOPPED"
    assert health["ready"]["ok"] is False
    assert health["ready"]["message"] == "Remote runner was manually stopped."


def test_server_health_projects_manual_stop_intent_without_saved_snapshot(monkeypatch) -> None:
    server_id, cfg = _stopped_runner_config()
    del cfg["servers"][server_id]["last_health_snapshot"]
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True

    class FailIfCalledRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise AssertionError("manual stop intent health should not touch remote runner")

    service._service_locator.remote_runner_manager = FailIfCalledRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)

    server = service.list_servers()[0]
    health = service.get_server_health(server_id)

    assert server["runner"]["state"] == "stopped"
    assert server["runner"]["reasonCode"] == "RUNNER_STOPPED"
    assert server["reasonCode"] == "RUNNER_STOPPED"
    assert health["reasonCode"] == "RUNNER_STOPPED"
    assert health["ready"]["ok"] is False
    assert health["ready"]["message"] == (
        "Remote runner was manually stopped. Use the explicit start action before submitting runs."
    )


def test_explicit_start_runner_starts_manually_stopped_runner(monkeypatch, tmp_path) -> None:
    server_id, cfg = _stopped_runner_config()
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    bootstrap_calls: list[str] = []

    class ReadyRemoteRunnerManager:
        def bootstrap(self, **kwargs):
            bootstrap_calls.append(str(kwargs["server_id"]))
            return {
                "bootstrap_version": "phase1-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "health": {
                    "serverId": server_id,
                    "startup": {"ok": True, "message": "Remote runner config loaded."},
                    "live": {"ok": True, "message": "Remote runner process is alive."},
                    "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                    "reasonCode": "",
                    "checkedAt": "2026-04-21T12:00:00Z",
                },
                "bootstrap_metadata": {"deployment_action": "explicit-start"},
            }

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    service._service_locator.remote_runner_manager = ReadyRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", save_capture)

    result = service.start_remote_runner(server_id)

    assert bootstrap_calls == [server_id]
    assert result["data"]["runner"]["ready"] is True
    assert cfg["servers"][server_id]["last_health_snapshot"]["reasonCode"] == ""
    assert cfg["servers"][server_id]["runner_stop_intent"]["active"] is False
    assert cfg["servers"][server_id]["runner_stop_intent"]["clearedByAction"] == "start"
