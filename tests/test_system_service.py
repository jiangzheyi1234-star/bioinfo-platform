from __future__ import annotations

import asyncio

import pytest

from apps.api import system_service
from core.deployment_mode import DeploymentModeError, UnsupportedDeploymentModeError


def test_service_info_exposes_local_identity_version_readiness(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("H2OMETA_RUNTIME_BUILD_ID", "build-test-123")
    monkeypatch.setenv("H2OMETA_BACKEND_SOURCE", "windows-launcher")

    payload = asyncio.run(system_service.service_info_from_request())

    item = payload["item"]
    assert item["service"] == "h2ometa-local-api"
    assert item["kind"] == "local-control-plane"
    assert item["identity"]["service"] == "h2ometa-local-api"
    assert item["identity"]["backendSource"] == "windows-launcher"
    assert item["identity"]["processId"] > 0
    assert item["version"] == {
        "buildId": "build-test-123",
        "terminalRuntimeBuildId": system_service.TERMINAL_RUNTIME_BUILD_ID,
        "terminalTransport": "websocket",
        "backendSource": "windows-launcher",
    }
    assert item["readiness"] == {
        "status": "degraded",
        "checks": {
            "process": True,
            "systemRoutes": True,
            "remoteRunner": False,
            "executionDiagnostics": False,
            "executionReady": False,
        },
    }
    assert item["executionReadiness"] == {
        "schemaVersion": "local-execution-readiness-projection.v1",
        "connected": False,
        "diagnosticsAvailable": False,
        "ready": False,
        "status": "unavailable",
        "reasonCode": "SSH_NOT_CONNECTED",
        "serverId": "",
        "generatedAt": "",
        "queue": {},
        "workers": {},
        "checks": {},
    }
    assert item["productionGovernance"]["schemaVersion"] == "production-governance-readiness.v1"
    assert item["productionGovernance"]["currentModeStatus"] == "ready"
    assert item["productionGovernance"]["publicMultiUserReady"] is False
    assert "multi-user-identity-rbac" in item["productionGovernance"]["publicMultiUserBlockingCheckIds"]
    assert item["stateCounts"] == {
        "localApiProcesses": 1,
        "remoteRunnerConnected": False,
        "activeSshSessions": 0,
    }


def test_service_info_projects_remote_execution_readiness_without_raw_diagnostics(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "desktop")

    class Runtime:
        def get_ssh_status(self):
            return {"connected": True, "serverId": "srv_ready"}

        def get_runner_execution_diagnostics(self, server_id):
            assert server_id == "srv_ready"
            return {
                "schemaVersion": "execution-diagnostics.v1",
                "generatedAt": "2026-07-01T00:00:00Z",
                "ok": True,
                "queueMetrics": {
                    "queuedJobs": 2,
                    "totalQueuedJobs": 3,
                    "scheduledQueuedJobs": 1,
                    "claimedJobs": 4,
                    "activeLeases": 5,
                    "resourceWaitJobs": 6,
                    "oldestQueuedAgeSeconds": 7,
                    "waitReasons": {"cpu": 6},
                },
                "workerHealth": {
                    "summary": {
                        "workerCount": 1,
                        "totalSlots": 2,
                        "runningSlots": 1,
                        "idleSlots": 1,
                        "workerStates": {"running": 1},
                        "slotStates": {"running": 1, "idle": 1},
                    },
                    "queueDepth": 2,
                    "claimedJobs": 4,
                    "workers": [
                        {
                            "workerId": "worker-secret-looking-id",
                            "sessionId": "session-should-not-surface",
                            "heartbeatAgeSeconds": 3,
                        }
                    ],
                },
                "readiness": {
                    "schemaVersion": "execution-readiness-policy.v1",
                    "ok": True,
                    "status": "ok",
                    "reasonCode": "",
                    "checks": {
                        "sqliteWal": True,
                        "sqliteBusyTimeout": True,
                        "executionInvariants": True,
                        "runWorkerAvailable": True,
                        "workerHeartbeatFresh": True,
                        "queueWaitWithinThreshold": True,
                        "resourceWaitWithinThreshold": True,
                    },
                },
                "recentEvents": [{"runId": "run_raw_should_not_surface"}],
            }

    monkeypatch.setattr("apps.api.route_utils.runtime_service", lambda: Runtime())

    payload = asyncio.run(system_service.service_info_from_request())

    item = payload["item"]
    assert item["readiness"]["status"] == "ready"
    assert item["readiness"]["checks"]["executionDiagnostics"] is True
    assert item["readiness"]["checks"]["executionReady"] is True
    assert item["stateCounts"]["queueDepth"] == 2
    assert item["stateCounts"]["runWorkerCount"] == 1
    assert item["stateCounts"]["runningWorkerSlots"] == 1
    assert item["executionReadiness"] == {
        "schemaVersion": "local-execution-readiness-projection.v1",
        "connected": True,
        "diagnosticsAvailable": True,
        "ready": True,
        "status": "ready",
        "reasonCode": "",
        "serverId": "srv_ready",
        "generatedAt": "2026-07-01T00:00:00Z",
        "queue": {
            "queuedJobs": 2,
            "totalQueuedJobs": 3,
            "scheduledQueuedJobs": 1,
            "claimedJobs": 4,
            "activeLeases": 5,
            "resourceWaitJobs": 6,
            "oldestQueuedAgeSeconds": 7,
            "waitReasons": {"cpu": 6},
        },
        "workers": {
            "workerCount": 1,
            "totalSlots": 2,
            "runningSlots": 1,
            "idleSlots": 1,
            "queueDepth": 2,
            "claimedJobs": 4,
            "workerStates": {"running": 1},
            "slotStates": {"running": 1, "idle": 1},
        },
        "checks": {
            "sqliteWal": True,
            "sqliteBusyTimeout": True,
            "executionInvariants": True,
            "runWorkerAvailable": True,
            "workerHeartbeatFresh": True,
            "queueWaitWithinThreshold": True,
            "resourceWaitWithinThreshold": True,
        },
    }
    serialized = str(item["executionReadiness"])
    assert "run_raw_should_not_surface" not in serialized
    assert "session-should-not-surface" not in serialized


def test_service_info_execution_diagnostics_failure_is_stable_and_redacted(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "desktop")

    class Runtime:
        def get_ssh_status(self):
            return {"connected": True, "serverId": "srv_failed"}

        def get_runner_execution_diagnostics(self, server_id):
            assert server_id == "srv_failed"
            raise RuntimeError("token=secret path=/home/lab/.h2ometa/runner/shared")

    monkeypatch.setattr("apps.api.route_utils.runtime_service", lambda: Runtime())

    payload = asyncio.run(system_service.service_info_from_request())

    item = payload["item"]
    assert item["readiness"]["status"] == "degraded"
    assert item["readiness"]["checks"]["remoteRunner"] is True
    assert item["readiness"]["checks"]["executionDiagnostics"] is False
    assert item["executionReadiness"]["reasonCode"] == "EXECUTION_DIAGNOSTICS_UNAVAILABLE"
    assert item["executionReadiness"]["serverId"] == "srv_failed"
    serialized = str(item["executionReadiness"])
    assert "token=secret" not in serialized
    assert "/home/lab" not in serialized


def test_service_info_production_governance_is_redacted(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "server-single-user")
    monkeypatch.setenv("H2OMETA_RUNNER_TOKEN", "runner-secret-value")
    monkeypatch.setenv("H2OMETA_DATABASE_URL", "postgresql://user:very-secret-password@example.invalid/h2ometa")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_ENDPOINT", "minio.internal:9000")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_BUCKET", "h2ometa-artifacts")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_ACCESS_KEY", "access-secret-value")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_SECRET_KEY", "s3-secret-value")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_PREFIX", "tenant-a")

    payload = asyncio.run(system_service.service_info_from_request())

    governance = payload["item"]["productionGovernance"]
    checks = {check["id"]: check for check in governance["checks"]}
    serialized = str(governance)
    assert governance["schemaVersion"] == "production-governance-readiness.v1"
    assert governance["currentModeStatus"] == "blocked"
    assert governance["currentModeBlockingCheckIds"] == ["postgres-control-plane"]
    assert checks["postgres-control-plane"]["reasonCode"] == "POSTGRES_UNSUPPORTED_SIGNAL_PRESENT"
    for check in governance["checks"]:
        assert "details" not in check
        assert "summary" not in check
    assert "very-secret-password" not in serialized
    assert "runner-secret-value" not in serialized
    assert "s3-secret-value" not in serialized
    assert "access-secret-value" not in serialized
    assert "minio.internal" not in serialized
    assert "h2ometa-artifacts" not in serialized


def test_service_info_requires_explicit_deployment_mode(monkeypatch) -> None:
    monkeypatch.delenv("H2OMETA_DEPLOYMENT_MODE", raising=False)

    with pytest.raises(DeploymentModeError, match="H2OMETA_DEPLOYMENT_MODE is required"):
        asyncio.run(system_service.service_info_from_request())


def test_service_info_rejects_unimplemented_multi_user(monkeypatch) -> None:
    monkeypatch.setenv("H2OMETA_DEPLOYMENT_MODE", "server-multi-user")

    with pytest.raises(UnsupportedDeploymentModeError, match="server-multi-user"):
        asyncio.run(system_service.service_info_from_request())
