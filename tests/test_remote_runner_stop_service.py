from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from apps.api.ssh_routes import list_servers, stop_server_runner
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.runner import (
    RUNNER_STOP_ACTIVE_LEASES_REASON,
    RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE_REASON,
)
from core.app_runtime.service import RuntimeService, ServiceLocator


def make_service(_tmp_path: Path, ssh_service) -> RuntimeService:
    service = RuntimeService(
        service_locator=ServiceLocator(ssh_service=ssh_service),
    )
    service._initialized = True
    return service


def _idle_execution_diagnostics() -> dict:
    return {
        "ok": True,
        "activeLeases": [],
        "allocatedResources": [],
        "resourceWaits": [],
        "workerHealth": {"summary": {"runningSlots": 0}, "workers": []},
        "queueMetrics": {"claimedJobs": 0},
    }


class IdleRemoteRunnerManager:
    def request_execution_lifecycle_guard(self, **_kwargs):
        return _lifecycle_guard_payload()


def test_stop_remote_runner_service_runs_explicit_stop_commands(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeSSH:
        is_connected = True

        def __init__(self) -> None:
            self.commands: list[tuple[str, int]] = []

        def run(self, cmd: str, timeout: int = 10):
            self.commands.append((cmd, timeout))
            return 0, "systemd_user=stopped\nstop_script=stopped\nprocess=not-running\n", ""

    fake_ssh = FakeSSH()
    service = make_service(tmp_path, fake_ssh)
    service._service_locator.remote_runner_manager = IdleRemoteRunnerManager()

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", save_capture)
    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        "bootstrap_version": "phase1-test",
        "runner_mode": "background_process",
        "service_port": 43127,
        "tunnel_port": 18765,
        "token_ref": "runner://srv_test",
    }

    result = asyncio.run(stop_server_runner(server_id))

    command, timeout = fake_ssh.commands[0]
    assert timeout == 30
    assert "systemctl --user stop h2ometa-remote.service" in command
    assert "bash \"$STOP_SCRIPT\"" in command
    assert "pkill -f '[r]emote_runner.run'" in command
    assert "runner-state.json" in command
    assert result["data"]["ok"] is True
    assert result["data"]["runner"]["reasonCode"] == "RUNNER_STOPPED"
    assert result["data"]["lifecycleAction"] == "stop"
    registry_entry = next(iter(cfg["servers"].values()))
    assert registry_entry["last_health_snapshot"]["reasonCode"] == "RUNNER_STOPPED"
    assert registry_entry["runner_stop_intent"] == {
        "schemaVersion": "h2ometa.runner-stop-intent.v1",
        "active": True,
        "reasonCode": "RUNNER_STOPPED",
        "serverId": server_id,
        "stoppedAt": result["data"]["completedAt"],
        "source": "explicit-stop",
    }


def test_stop_remote_runner_blocks_active_execution_before_kill(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeSSH:
        is_connected = True

        def run(self, cmd: str, timeout: int = 10):
            raise AssertionError(f"stop command must not run while execution is active: {cmd}")

    class ActiveRemoteRunnerManager:
        def request_execution_lifecycle_guard(self, **_kwargs):
            return _lifecycle_guard_payload(
                block_reasons=["active-workflow-leases"],
                active_lease_count=1,
            )

    service = make_service(tmp_path, FakeSSH())
    service._service_locator.remote_runner_manager = ActiveRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        "bootstrap_version": "phase1-test",
        "runner_mode": "background_process",
        "service_port": 43127,
        "tunnel_port": 18765,
        "token_ref": "runner://srv_test",
    }

    with pytest.raises(RuntimeServiceError) as raised:
        asyncio.run(stop_server_runner(server_id))

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == RUNNER_STOP_ACTIVE_LEASES_REASON
    assert raised.value.detail["activeLeaseCount"] == 1
    assert raised.value.detail["nextAction"] == "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_STOP"


def test_stop_remote_runner_blocks_when_execution_diagnostics_unavailable(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeSSH:
        is_connected = True

        def run(self, cmd: str, timeout: int = 10):
            raise AssertionError(f"stop command must not run without diagnostics: {cmd}")

    class BrokenDiagnosticsRemoteRunnerManager:
        def request_execution_lifecycle_guard(self, **_kwargs):
            raise RuntimeError("runner diagnostics offline")

    service = make_service(tmp_path, FakeSSH())
    service._service_locator.remote_runner_manager = BrokenDiagnosticsRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        "bootstrap_version": "phase1-test",
        "runner_mode": "background_process",
        "service_port": 43127,
        "tunnel_port": 18765,
        "token_ref": "runner://srv_test",
    }

    with pytest.raises(RuntimeServiceError) as raised:
        asyncio.run(stop_server_runner(server_id))

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE_REASON
    assert raised.value.detail["nextAction"] == "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_STOP"


def _lifecycle_guard_payload(
    *,
    block_reasons: list[str] | None = None,
    active_lease_count: int = 0,
) -> dict:
    reasons = block_reasons or []
    return {
        "schemaVersion": "h2ometa.execution-lifecycle-guard.v1",
        "action": "stop",
        "owner": "srv_test:stop:lifecycle",
        "idle": not reasons,
        "maintenanceActive": True,
        "requestedAt": "2099-06-07T10:00:00Z",
        "expiresAt": "2099-06-07T10:10:00Z",
        "activeWorkerCount": 1,
        "drainRequestedWorkerCount": 1,
        "activeLeaseCount": active_lease_count,
        "allocatedResourceCount": 0,
        "resourceWaitCount": 0,
        "queuedJobCount": 0,
        "claimedJobCount": 0,
        "runningSlotCount": 0,
        "blockReasons": reasons,
    }
