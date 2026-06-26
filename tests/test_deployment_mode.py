from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.deployment_mode import (
    DeploymentMode,
    DeploymentModeError,
    UnsupportedDeploymentModeError,
    build_production_governance_readiness,
    get_deployment_config,
    get_deployment_mode,
    require_supported_deployment_mode,
    validate_deployment_security,
)


def test_deployment_mode_enum_values():
    assert DeploymentMode.DESKTOP.value == "desktop"
    assert DeploymentMode.SERVER_SINGLE_USER.value == "server-single-user"
    assert DeploymentMode.SERVER_MULTI_USER.value == "server-multi-user"


def test_get_deployment_mode_missing_fails_closed():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(DeploymentModeError, match="H2OMETA_DEPLOYMENT_MODE is required"):
            get_deployment_mode()


def test_get_deployment_mode_blank_fails_closed():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "  "}):
        with pytest.raises(DeploymentModeError, match="H2OMETA_DEPLOYMENT_MODE is required"):
            get_deployment_mode()


def test_get_deployment_mode_from_env():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"}):
        mode = get_deployment_mode()
        assert mode == DeploymentMode.SERVER_SINGLE_USER


def test_get_deployment_mode_invalid_fails_loudly():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "invalid-mode"}):
        with pytest.raises(DeploymentModeError, match="Invalid H2OMETA_DEPLOYMENT_MODE"):
            get_deployment_mode()


def test_deployment_config_desktop():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}):
        config = get_deployment_config()
        assert config.mode == DeploymentMode.DESKTOP
        assert config.requires_auth is False
        assert config.allows_public_network is False
        assert config.credential_storage == "os-keyring"
        assert config.is_single_user is True
        assert config.is_server_mode is False


def test_deployment_config_server_single_user():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"}):
        config = get_deployment_config()
        assert config.mode == DeploymentMode.SERVER_SINGLE_USER
        assert config.requires_auth is False
        assert config.allows_public_network is False
        assert config.credential_storage == "env-secret"
        assert config.is_single_user is True
        assert config.is_server_mode is True


def test_deployment_config_server_multi_user():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-multi-user"}):
        config = get_deployment_config()
        assert config.mode == DeploymentMode.SERVER_MULTI_USER
        assert config.requires_auth is True
        assert config.allows_public_network is True
        assert config.credential_storage == "database-encrypted"
        assert config.is_single_user is False
        assert config.is_server_mode is True


def test_require_supported_deployment_mode_rejects_unimplemented_multi_user():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-multi-user"}):
        with pytest.raises(UnsupportedDeploymentModeError, match="not implemented"):
            require_supported_deployment_mode()


def test_deployment_config_to_dict():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}):
        config = get_deployment_config()
        d = config.to_dict()
        assert d["mode"] == "desktop"
        assert d["requiresAuth"] is False
        assert d["allowsPublicNetwork"] is False
        assert d["credentialStorage"] == "os-keyring"
        assert d["isSingleUser"] is True
        assert d["isServerMode"] is False


def test_validate_network_binding_localhost():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}):
        config = get_deployment_config()
        config.validate_network_binding("127.0.0.1")


def test_validate_network_binding_rejects_external():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}):
        config = get_deployment_config()
        try:
            config.validate_network_binding("192.168.1.100")
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "does not allow binding" in str(exc)


def test_validate_network_binding_desktop_rejects_bind_all():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}):
        config = get_deployment_config()
        with pytest.raises(ValueError, match="Desktop mode does not allow binding"):
            config.validate_network_binding("0.0.0.0")


def test_validate_network_binding_single_user_rejects_bind_all():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"}):
        config = get_deployment_config()
        with pytest.raises(ValueError, match="server-single-user mode does not allow binding to 0.0.0.0"):
            config.validate_network_binding("0.0.0.0")


def test_validate_security_desktop_no_warnings():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}, clear=True):
        warnings = validate_deployment_security()
        assert len(warnings) == 0


def test_validate_security_single_user_missing_token():
    with patch.dict(
        os.environ,
        {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"},
        clear=True,
    ):
        warnings = validate_deployment_security()
        assert any("H2OMETA_RUNNER_TOKEN" in w for w in warnings)


def test_validate_security_single_user_with_token():
    with patch.dict(
        os.environ,
        {
            "H2OMETA_DEPLOYMENT_MODE": "server-single-user",
            "H2OMETA_RUNNER_TOKEN": "test-token-123",
        },
        clear=True,
    ):
        warnings = validate_deployment_security()
        token_warnings = [w for w in warnings if "H2OMETA_RUNNER_TOKEN" in w]
        assert len(token_warnings) == 0


def test_validate_security_multi_user_is_fail_closed():
    with patch.dict(
        os.environ,
        {"H2OMETA_DEPLOYMENT_MODE": "server-multi-user"},
        clear=True,
    ):
        with pytest.raises(UnsupportedDeploymentModeError, match="server-multi-user"):
            validate_deployment_security()


def test_validate_security_single_user_bind_all_fails_closed():
    with patch.dict(
        os.environ,
        {
            "H2OMETA_DEPLOYMENT_MODE": "server-single-user",
            "H2OMETA_API_HOST": "0.0.0.0",
            "H2OMETA_RUNNER_TOKEN": "test-token",
        },
        clear=True,
    ):
        with pytest.raises(ValueError, match="server-single-user mode does not allow binding to 0.0.0.0"):
            validate_deployment_security()


def test_production_governance_readiness_is_safe_for_desktop() -> None:
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "desktop"}, clear=True):
        report = build_production_governance_readiness()

    checks = {check["id"]: check for check in report["checks"]}
    serialized = str(report)
    assert report["schemaVersion"] == "production-governance-readiness.v1"
    assert report["currentModeStatus"] == "ready"
    assert report["publicMultiUserReady"] is False
    assert "multi-user-identity-rbac" in report["publicMultiUserBlockingCheckIds"]
    assert checks["remote-runner-machine-token"]["status"] == "not_applicable"
    assert "H2OMETA_RUNNER_TOKEN" not in serialized
    assert "DATABASE_URL" not in serialized
    assert "SECRET_KEY" not in serialized


def test_production_governance_readiness_blocks_single_user_without_token() -> None:
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"}, clear=True):
        report = build_production_governance_readiness()

    checks = {check["id"]: check for check in report["checks"]}
    assert report["currentModeStatus"] == "blocked"
    assert report["currentModeBlockingCheckIds"] == ["remote-runner-machine-token"]
    assert checks["remote-runner-machine-token"]["reasonCode"] == "REMOTE_RUNNER_TOKEN_REQUIRED"


def test_production_governance_readiness_reports_safe_storage_signals() -> None:
    with patch.dict(
        os.environ,
        {
            "H2OMETA_DEPLOYMENT_MODE": "server-single-user",
            "H2OMETA_RUNNER_TOKEN": "runner-secret-value",
            "H2OMETA_DATABASE_URL": "postgresql://user:very-secret-password@example.invalid/h2ometa",
            "H2OMETA_ARTIFACT_S3_ENDPOINT": "minio.internal:9000",
            "H2OMETA_ARTIFACT_S3_BUCKET": "h2ometa-artifacts",
            "H2OMETA_ARTIFACT_S3_ACCESS_KEY": "access-secret-value",
            "H2OMETA_ARTIFACT_S3_SECRET_KEY": "s3-secret-value",
            "H2OMETA_ARTIFACT_S3_PREFIX": "tenant-a",
        },
        clear=True,
    ):
        report = build_production_governance_readiness()

    checks = {check["id"]: check for check in report["checks"]}
    serialized = str(report)
    assert report["currentModeStatus"] == "blocked"
    assert report["currentModeBlockingCheckIds"] == ["postgres-control-plane"]
    assert checks["postgres-control-plane"]["reasonCode"] == "POSTGRES_UNSUPPORTED_SIGNAL_PRESENT"
    assert checks["postgres-control-plane"]["details"] == {
        "databaseUrlSignalPresent": True,
        "supportedBackend": "sqlite",
    }
    assert checks["s3-minio-artifact-storage"]["status"] == "pass"
    assert checks["s3-minio-artifact-storage"]["details"]["complete"] is True
    assert "very-secret-password" not in serialized
    assert "runner-secret-value" not in serialized
    assert "s3-secret-value" not in serialized
    assert "access-secret-value" not in serialized
    assert "minio.internal" not in serialized


def test_production_governance_readiness_keeps_insecure_s3_partial() -> None:
    with patch.dict(
        os.environ,
        {
            "H2OMETA_DEPLOYMENT_MODE": "desktop",
            "H2OMETA_ARTIFACT_S3_ENDPOINT": "minio.internal:9000",
            "H2OMETA_ARTIFACT_S3_BUCKET": "h2ometa-artifacts",
            "H2OMETA_ARTIFACT_S3_ACCESS_KEY": "access-secret-value",
            "H2OMETA_ARTIFACT_S3_SECRET_KEY": "s3-secret-value",
            "H2OMETA_ARTIFACT_S3_PREFIX": "tenant-a",
            "H2OMETA_ARTIFACT_S3_SECURE": "false",
        },
        clear=True,
    ):
        report = build_production_governance_readiness()

    s3 = {check["id"]: check for check in report["checks"]}["s3-minio-artifact-storage"]
    assert s3["status"] == "partial"
    assert s3["reasonCode"] == "S3_MINIO_SECURE_TRANSPORT_PENDING"
    assert "s3-minio-artifact-storage" in report["publicMultiUserBlockingCheckIds"]
