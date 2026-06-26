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
        },
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
