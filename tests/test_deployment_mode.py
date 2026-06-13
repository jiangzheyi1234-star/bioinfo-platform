from __future__ import annotations

import os
from unittest.mock import patch

from core.deployment_mode import (
    DeploymentMode,
    get_deployment_config,
    get_deployment_mode,
    validate_deployment_security,
)


def test_deployment_mode_enum_values():
    assert DeploymentMode.DESKTOP.value == "desktop"
    assert DeploymentMode.SERVER_SINGLE_USER.value == "server-single-user"
    assert DeploymentMode.SERVER_MULTI_USER.value == "server-multi-user"


def test_get_deployment_mode_default():
    with patch.dict(os.environ, {}, clear=True):
        mode = get_deployment_mode()
        assert mode == DeploymentMode.DESKTOP


def test_get_deployment_mode_from_env():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "server-single-user"}):
        mode = get_deployment_mode()
        assert mode == DeploymentMode.SERVER_SINGLE_USER


def test_get_deployment_mode_invalid_falls_back():
    with patch.dict(os.environ, {"H2OMETA_DEPLOYMENT_MODE": "invalid-mode"}):
        mode = get_deployment_mode()
        assert mode == DeploymentMode.DESKTOP


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


def test_validate_security_multi_user_missing_secret():
    with patch.dict(
        os.environ,
        {"H2OMETA_DEPLOYMENT_MODE": "server-multi-user"},
        clear=True,
    ):
        warnings = validate_deployment_security()
        assert any("H2OMETA_AUTH_SECRET" in w for w in warnings)


def test_validate_security_single_user_bind_all():
    with patch.dict(
        os.environ,
        {
            "H2OMETA_DEPLOYMENT_MODE": "server-single-user",
            "H2OMETA_API_HOST": "0.0.0.0",
            "H2OMETA_RUNNER_TOKEN": "test-token",
        },
        clear=True,
    ):
        warnings = validate_deployment_security()
        assert any("0.0.0.0" in w for w in warnings)
