from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.response_cache import invalidate_response_cache
from apps.api.models import RunnerReleasePruneRunRequest, RunnerUninstallRunRequest
from apps.api.ssh_routes import (
    ensure_server_runner,
    list_servers,
    preview_server_runner_release_prune,
    preview_server_runner_uninstall,
    run_server_runner_release_prune,
    run_server_runner_uninstall,
    start_server_runner,
    upgrade_server_runner,
)
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator
from core.remote_runner.bootstrap_guard import (
    BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON,
    UPGRADE_ACTIVE_LEASES_REASON,
    UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON,
    UPGRADE_EXECUTION_BUSY_REASON,
)
from core.remote_runner.errors import RemoteRunnerManagerError


def _make_service(_tmp_path: Path) -> RuntimeService:
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    return service


def _patch_runtime_service(monkeypatch: pytest.MonkeyPatch, service: RuntimeService) -> None:
    asyncio.run(invalidate_response_cache("servers", "ssh_status"))
    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: service)


def _runtime_config() -> dict[str, Any]:
    return {
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


def _ready_health() -> dict[str, Any]:
    return {
        "startup": {"ok": True, "message": "Remote runner config loaded."},
        "live": {"ok": True, "message": "Remote runner process is alive."},
        "ready": {"ok": True, "message": "Remote runner control plane is ready."},
        "reasonCode": "",
        "checkedAt": "2026-04-21T12:00:00Z",
    }


def _save_capture(target: dict[str, Any]):
    def _capture(next_cfg: dict[str, Any]) -> None:
        snapshot = dict(next_cfg)
        target.clear()
        target.update(snapshot)

    return _capture


def _prepared_record() -> dict[str, Any]:
    return {
        "bootstrap_version": "old-ready-version",
        "runner_mode": "background_process",
        "service_port": 43127,
        "tunnel_port": 18765,
        "token_ref": "runner://srv_test",
    }


def test_ensure_runner_bootstrap_persists_server_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.bootstrap_calls: list[dict[str, object]] = []

        def bootstrap(self, **kwargs):
            self.bootstrap_calls.append(kwargs)
            return {
                "bootstrap_version": "phase1-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "health": _ready_health(),
            }

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    result = asyncio.run(ensure_server_runner(server_id))

    assert len(fake_manager.bootstrap_calls) == 1
    assert fake_manager.bootstrap_calls[0]["bootstrap_action"] == "ensure"
    assert cfg["servers"][server_id]["bootstrap_version"] == "phase1-test"
    assert cfg["servers"][server_id]["runner_mode"] == "background_process"
    assert cfg["servers"][server_id]["tunnel_port"] == 18765
    assert result["data"]["health"]["ready"]["ok"] is True
    assert result["data"]["health"]["reasonCode"] == ""
    assert result["data"]["runner"]["state"] == "ready"
    assert result["data"]["lifecycleAction"] == "ensure"


def test_ensure_runner_http_conflict_preserves_manual_stop_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConflictRuntime:
        def ensure_remote_runner_ready(self, server_id: str):
            raise RuntimeServiceError(
                "Remote runner was manually stopped. Use the explicit start action before submitting runs.",
                status_code=409,
                detail={
                    "reasonCode": "RUNNER_STOPPED",
                    "serverId": server_id,
                    "nextAction": "START_RUNNER",
                },
            )

    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: ConflictRuntime())

    response = TestClient(app).post(
        "/api/v1/servers/srv_stopped/ensure-runner",
        headers={"X-Request-Id": "req_ensure_stopped"},
    )

    assert response.status_code == 409
    assert response.headers["X-Request-Id"] == "req_ensure_stopped"
    payload = response.json()
    assert payload["code"] == "RUNTIME_SERVICE_ERROR"
    assert payload["requestId"] == "req_ensure_stopped"
    assert "RUNNER_STOPPED" in payload["detail"]
    assert "START_RUNNER" in payload["detail"]


def test_ensure_runner_keeps_ready_existing_runner_without_implicit_upgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.bootstrap_calls = 0

        def get_health(self, **_kwargs):
            return _ready_health()

        def bootstrap(self, **_kwargs):
            self.bootstrap_calls += 1
            raise AssertionError("ensure must not deploy when an existing runner is ready")

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = _prepared_record()

    result = asyncio.run(ensure_server_runner(server_id))

    assert fake_manager.bootstrap_calls == 0
    assert cfg["servers"][server_id]["bootstrap_version"] == "old-ready-version"
    assert cfg["servers"][server_id]["last_health_snapshot"]["ready"]["ok"] is True
    assert result["data"]["lifecycleAction"] == "ensure"


def test_start_runner_uses_explicit_start_lifecycle_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def bootstrap(self, **_kwargs):
            return {
                "bootstrap_version": "phase-start-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "health": _ready_health(),
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    result = asyncio.run(start_server_runner(server_id))

    assert result["data"]["lifecycleAction"] == "start"
    assert cfg["servers"][server_id]["bootstrap_version"] == "phase-start-test"
    assert cfg["servers"][server_id]["runner_started_at"]


def test_upgrade_runner_requires_existing_runner_and_persists_upgrade_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.bootstrap_calls: list[dict[str, object]] = []

        def bootstrap(self, **kwargs):
            self.bootstrap_calls.append(kwargs)
            return {
                "bootstrap_version": "phase-upgrade-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "bootstrap_metadata": {
                    "upgradeGuard": {"checked": True, "activeLeaseCount": 0},
                    "deployment_action": "installed",
                },
                "health": _ready_health(),
            }

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    with pytest.raises(RuntimeServiceError) as not_prepared:
        asyncio.run(upgrade_server_runner(server_id))
    assert not_prepared.value.status_code == 409
    assert not_prepared.value.detail["reasonCode"] == "RUNNER_UPGRADE_NOT_PREPARED"

    cfg["servers"][server_id] = _prepared_record()

    result = asyncio.run(upgrade_server_runner(server_id))

    assert len(fake_manager.bootstrap_calls) == 1
    assert fake_manager.bootstrap_calls[0]["server_record"]["bootstrap_version"] == "old-ready-version"
    assert fake_manager.bootstrap_calls[0]["bootstrap_action"] == "upgrade"
    assert cfg["servers"][server_id]["bootstrap_version"] == "phase-upgrade-test"
    assert cfg["servers"][server_id]["runner_upgraded_at"]
    assert cfg["servers"][server_id]["bootstrap_metadata"]["upgradeGuard"]["activeLeaseCount"] == 0
    assert result["data"]["lifecycleAction"] == "upgrade"


def test_upgrade_runner_active_lease_block_preserves_health_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def bootstrap(self, **_kwargs):
            raise RemoteRunnerManagerError(
                "remote runner upgrade blocked because active workflow run leases exist",
                bootstrap_metadata={"upgradeGuard": {"checked": True, "activeLeaseCount": 1}},
                status_code=409,
                detail={
                    "reasonCode": UPGRADE_ACTIVE_LEASES_REASON,
                    "activeLeaseCount": 1,
                    "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE",
                },
            )

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    health = _ready_health()
    cfg["servers"][server_id] = {**_prepared_record(), "last_health_snapshot": health}

    with pytest.raises(RuntimeServiceError) as blocked:
        asyncio.run(upgrade_server_runner(server_id))

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == UPGRADE_ACTIVE_LEASES_REASON
    assert cfg["servers"][server_id]["last_health_snapshot"] == health
    assert cfg["servers"][server_id]["runner_upgrade_blocked_at"]
    assert cfg["servers"][server_id]["bootstrap_metadata"]["upgradeGuard"]["activeLeaseCount"] == 1


def test_upgrade_runner_diagnostics_unavailable_block_preserves_health_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def bootstrap(self, **_kwargs):
            raise RemoteRunnerManagerError(
                "remote runner upgrade guard failed because execution diagnostics are unavailable",
                bootstrap_metadata={
                    "upgradeGuard": {
                        "checked": False,
                        "reason": "execution-diagnostics-unavailable",
                        "message": "runner not reachable",
                    }
                },
                status_code=409,
                detail={
                    "reasonCode": UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_UPGRADE",
                },
            )

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    health = _ready_health()
    cfg["servers"][server_id] = {**_prepared_record(), "last_health_snapshot": health}

    with pytest.raises(RuntimeServiceError) as blocked:
        asyncio.run(upgrade_server_runner(server_id))

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
    assert cfg["servers"][server_id]["last_health_snapshot"] == health
    assert cfg["servers"][server_id]["runner_upgrade_blocked_at"]
    assert cfg["servers"][server_id]["bootstrap_metadata"]["upgradeGuard"]["checked"] is False


def test_upgrade_runner_execution_busy_block_preserves_health_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def bootstrap(self, **_kwargs):
            raise RemoteRunnerManagerError(
                "remote runner bootstrap blocked because runner execution state is not idle",
                bootstrap_metadata={
                    "upgradeGuard": {
                        "checked": True,
                        "idle": False,
                        "blockReasons": ["claimed-jobs", "running-worker-slots"],
                        "claimedJobCount": 2,
                        "runningSlotCount": 1,
                    }
                },
                status_code=409,
                detail={
                    "reasonCode": UPGRADE_EXECUTION_BUSY_REASON,
                    "blockReasons": ["claimed-jobs", "running-worker-slots"],
                    "claimedJobCount": 2,
                    "runningSlotCount": 1,
                    "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE",
                },
            )

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    health = _ready_health()
    cfg["servers"][server_id] = {**_prepared_record(), "last_health_snapshot": health}

    with pytest.raises(RuntimeServiceError) as blocked:
        asyncio.run(upgrade_server_runner(server_id))

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == UPGRADE_EXECUTION_BUSY_REASON
    assert cfg["servers"][server_id]["last_health_snapshot"] == health
    assert cfg["servers"][server_id]["runner_upgrade_blocked_at"]
    assert cfg["servers"][server_id]["bootstrap_metadata"]["upgradeGuard"]["blockReasons"] == [
        "claimed-jobs",
        "running-worker-slots",
    ]


def test_ensure_runner_diagnostics_unavailable_block_preserves_health_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def get_health(self, **_kwargs):
            raise RuntimeServiceError("runner health unavailable")

        def bootstrap(self, **_kwargs):
            raise RemoteRunnerManagerError(
                "remote runner bootstrap guard failed because execution diagnostics are unavailable",
                bootstrap_metadata={
                    "upgradeGuard": {
                        "checked": False,
                        "reason": "execution-diagnostics-unavailable",
                        "message": "runner not reachable",
                    }
                },
                status_code=409,
                detail={
                    "reasonCode": BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_BOOTSTRAP",
                },
            )

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    health = _ready_health()
    cfg["servers"][server_id] = {**_prepared_record(), "last_health_snapshot": health}

    with pytest.raises(RuntimeServiceError) as blocked:
        asyncio.run(ensure_server_runner(server_id))

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON
    assert cfg["servers"][server_id]["last_health_snapshot"] == health
    assert cfg["servers"][server_id]["runner_upgrade_blocked_at"]
    assert cfg["servers"][server_id]["bootstrap_metadata"]["upgradeGuard"]["checked"] is False


def test_upgrade_runner_http_conflict_preserves_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConflictRuntime:
        def upgrade_remote_runner(self, server_id: str):
            raise RuntimeServiceError(
                "remote runner upgrade blocked because active workflow run leases exist",
                status_code=409,
                detail={
                    "reasonCode": UPGRADE_ACTIVE_LEASES_REASON,
                    "serverId": server_id,
                    "blockReasons": ["active-workflow-leases"],
                    "activeLeaseCount": 1,
                    "activeLeases": [{"runId": "run_sensitive"}],
                    "host": "runner.internal",
                    "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE",
                },
            )

    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: ConflictRuntime())

    response = TestClient(app).post(
        "/api/v1/servers/srv_active/runner/upgrade",
        headers={"X-Request-Id": "req_upgrade_active"},
    )

    assert response.status_code == 409
    assert response.headers["X-Request-Id"] == "req_upgrade_active"
    payload = response.json()
    assert payload["code"] == "RUNTIME_SERVICE_ERROR"
    assert payload["requestId"] == "req_upgrade_active"
    assert payload["reasonCode"] == UPGRADE_ACTIVE_LEASES_REASON
    assert payload["serverId"] == "srv_active"
    assert payload["blockReasons"] == ["active-workflow-leases"]
    assert payload["activeLeaseCount"] == 1
    assert payload["nextAction"] == "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE"
    assert "activeLeases" not in payload
    assert "host" not in payload
    assert UPGRADE_ACTIVE_LEASES_REASON in payload["detail"]
    assert "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE" in payload["detail"]


def test_runner_lifecycle_mutation_failures_invalidate_ssh_state_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    invalidations: list[tuple[str, ...]] = []

    async def fake_invalidate_response_cache(*_keys: str, prefixes=()) -> None:
        invalidations.append(tuple(prefixes))

    class ConflictRuntime:
        def upgrade_remote_runner(self, server_id: str):
            raise RuntimeServiceError(
                "remote runner upgrade blocked because active workflow run leases exist",
                status_code=409,
                detail={"reasonCode": UPGRADE_ACTIVE_LEASES_REASON, "serverId": server_id},
            )

        def stop_remote_runner_service(self, server_id: str):
            raise RuntimeServiceError(
                "remote runner stop failed",
                status_code=503,
                detail={"reasonCode": "RUNNER_STOP_FAILED", "serverId": server_id},
            )

    monkeypatch.setattr("apps.api.ssh_control_service.runtime_service", lambda: ConflictRuntime())
    monkeypatch.setattr("apps.api.ssh_control_service.invalidate_response_cache", fake_invalidate_response_cache)

    client = TestClient(app)
    upgrade_response = client.post("/api/v1/servers/srv_active/runner/upgrade")
    stop_response = client.post("/api/v1/servers/srv_active/runner/stop")

    assert upgrade_response.status_code == 409
    assert stop_response.status_code == 503
    assert len(invalidations) == 2
    assert all("servers" in prefixes and "ssh_" in prefixes for prefixes in invalidations)


def test_runner_release_prune_api_forwards_preview_and_plan_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _runtime_config()

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.run_plan_hash = ""

        def preview_release_prune(self, **_kwargs):
            return {
                "schemaVersion": "h2ometa.remote-runner-release-prune.v1",
                "planHash": "a" * 64,
                "releases": [],
                "deletableReleaseCount": 0,
            }

        def run_release_prune(self, **kwargs):
            self.run_plan_hash = str(kwargs["plan_hash"])
            return {
                "schemaVersion": "h2ometa.remote-runner-release-prune.v1",
                "planHash": self.run_plan_hash,
                "deletedReleases": [],
                "deletedReleaseCount": 0,
            }

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = _prepared_record()

    preview = asyncio.run(preview_server_runner_release_prune(server_id))
    result = asyncio.run(
        run_server_runner_release_prune(
            server_id,
            RunnerReleasePruneRunRequest(
                confirmation="prune-runner-releases",
                planHash=preview["data"]["planHash"],
            ),
        )
    )

    assert preview["data"]["schemaVersion"] == "h2ometa.remote-runner-release-prune.v1"
    assert fake_manager.run_plan_hash == "a" * 64
    assert result["data"]["deletedReleaseCount"] == 0


def test_runner_uninstall_api_forwards_plan_hash_and_clears_prepared_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _make_service(tmp_path)
    closed_tunnels: list[str] = []
    service._service_locator.ssh_service = SimpleNamespace(
        is_connected=True,
        close=lambda: None,
        close_local_tunnel=lambda name: closed_tunnels.append(name),
    )
    cfg = _runtime_config()
    deleted_tokens: list[str] = []

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.run_plan_hash = ""

        def preview_uninstall(self, **_kwargs):
            return {
                "schemaVersion": "h2ometa.remote-runner-uninstall.v1",
                "planHash": "b" * 64,
                "controlPlaneOnly": True,
                "preservedPaths": [{"path": "/home/tester/.h2ometa/runner/shared/data"}],
                "uninstallTargets": [],
                "targetCount": 0,
            }

        def run_uninstall(self, **kwargs):
            self.run_plan_hash = str(kwargs["plan_hash"])
            return {
                "schemaVersion": "h2ometa.remote-runner-uninstall.v1",
                "planHash": self.run_plan_hash,
                "controlPlaneOnly": True,
                "preservedPaths": [{"path": "/home/tester/.h2ometa/runner/shared/data"}],
                "removedTargets": [],
                "removedTargetCount": 0,
            }

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.runtime_config.save_runtime_config", _save_capture(cfg))
    monkeypatch.setattr("core.app_runtime.runner_ops.delete_runner_token", lambda token_ref: deleted_tokens.append(token_ref))
    _patch_runtime_service(monkeypatch, service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        **_prepared_record(),
        "last_health_snapshot": _ready_health(),
    }

    preview = asyncio.run(preview_server_runner_uninstall(server_id))
    result = asyncio.run(
        run_server_runner_uninstall(
            server_id,
            RunnerUninstallRunRequest(
                confirmation="uninstall-runner-control-plane",
                planHash=preview["data"]["planHash"],
            ),
        )
    )

    assert preview["data"]["schemaVersion"] == "h2ometa.remote-runner-uninstall.v1"
    assert fake_manager.run_plan_hash == "b" * 64
    assert deleted_tokens == ["runner://srv_test"]
    assert closed_tunnels == [f"runner-{server_id}"]
    assert result["data"]["lifecycleAction"] == "uninstall"
    assert result["data"]["runner"]["state"] == "repair_needed"
    assert cfg["servers"][server_id]["last_health_snapshot"]["reasonCode"] == "RUNNER_UNINSTALLED"
    assert cfg["servers"][server_id]["runner_uninstall"]["removedTargetCount"] == 0
    assert "bootstrap_version" not in cfg["servers"][server_id]
    assert "token_ref" not in cfg["servers"][server_id]
    assert "service_port" not in cfg["servers"][server_id]
