from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.api.models import SSHHostKeyAcceptRequest, SSHHostKeyScanRequest
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator


def _service() -> RuntimeService:
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    return service


def _runtime_cfg() -> dict:
    return {
        "ssh": {
            "auth_mode": "key_file",
            "host": "192.0.2.10",
            "port": 2222,
            "user": "tester",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 7,
        }
    }


def _scan_result(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        ok=True,
        message="SSH host key scanned",
        key_type="ssh-ed25519",
        fingerprint_sha256="SHA256:test-fingerprint",
        known_hosts_path=str(tmp_path / "known_hosts"),
    )


def test_scan_ssh_host_key_returns_explicit_confirmation_payload(monkeypatch, tmp_path: Path) -> None:
    service = _service()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", _runtime_cfg)
    monkeypatch.setattr("core.app_runtime.service.scan_remote_ssh_host_key", lambda *args, **kwargs: _scan_result(tmp_path))

    payload = service.scan_ssh_host_key_for_request()["data"]

    assert payload["serverId"].startswith("srv_")
    assert payload["host"] == "192.0.2.10"
    assert payload["port"] == 2222
    assert payload["hostKeyTrusted"] is False
    assert payload["hostKeyType"] == "ssh-ed25519"
    assert payload["hostKeyFingerprintSha256"] == "SHA256:test-fingerprint"
    assert payload["knownHostsPath"] == str(tmp_path / "known_hosts")


def test_accept_ssh_host_key_requires_confirmed_fingerprint(monkeypatch, tmp_path: Path) -> None:
    service = _service()
    calls: dict[str, object] = {}
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", _runtime_cfg)
    monkeypatch.setattr("core.app_runtime.service.scan_remote_ssh_host_key", lambda *args, **kwargs: _scan_result(tmp_path))

    server_id = service.scan_ssh_host_key_for_request()["data"]["serverId"]

    def trust(ip: str, port: int, timeout: int, *, expected_fingerprint_sha256: str):
        calls.update(
            {
                "ip": ip,
                "port": port,
                "timeout": timeout,
                "expected_fingerprint_sha256": expected_fingerprint_sha256,
            }
        )
        return SimpleNamespace(
            ok=True,
            message="SSH host key trusted",
            key_type="ssh-ed25519",
            fingerprint_sha256="SHA256:test-fingerprint",
            known_hosts_path=str(tmp_path / "known_hosts"),
            code="",
        )

    monkeypatch.setattr("core.app_runtime.service.trust_ssh_host_key", trust)
    request = SSHHostKeyAcceptRequest(
        auth_mode="key_file",
        host="192.0.2.10",
        port=2222,
        user="tester",
        timeout_sec=7,
        confirmation="trust-ssh-host-key",
        fingerprintSha256="SHA256:test-fingerprint",
    )

    accepted = service.accept_server_host_key(server_id, request.model_dump())["data"]

    assert calls["ip"] == "192.0.2.10"
    assert calls["port"] == 2222
    assert calls["timeout"] == 7
    assert calls["expected_fingerprint_sha256"] == "SHA256:test-fingerprint"
    assert accepted["hostKeyTrusted"] is True
    assert accepted["hostKeyFingerprintSha256"] == "SHA256:test-fingerprint"


def test_accept_ssh_host_key_blocks_fingerprint_mismatch(monkeypatch, tmp_path: Path) -> None:
    service = _service()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", _runtime_cfg)
    monkeypatch.setattr("core.app_runtime.service.scan_remote_ssh_host_key", lambda *args, **kwargs: _scan_result(tmp_path))
    server_id = service.scan_ssh_host_key_for_request()["data"]["serverId"]
    monkeypatch.setattr(
        "core.app_runtime.service.trust_ssh_host_key",
        lambda *args, **kwargs: SimpleNamespace(
            ok=False,
            message="SSH host key fingerprint changed; refusing to trust this host key.",
            code="SSH_HOST_KEY_FINGERPRINT_MISMATCH",
            fingerprint_sha256="SHA256:actual",
        ),
    )

    request = SSHHostKeyAcceptRequest(
        auth_mode="key_file",
        host="192.0.2.10",
        port=2222,
        user="tester",
        confirmation="trust-ssh-host-key",
        fingerprintSha256="SHA256:expected",
    )

    with pytest.raises(RuntimeServiceError) as exc_info:
        service.accept_server_host_key(server_id, request.model_dump())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reasonCode"] == "SSH_HOST_KEY_FINGERPRINT_MISMATCH"
    assert exc_info.value.detail["hostKeyFingerprintSha256"] == "SHA256:actual"


def test_ssh_host_key_accept_request_rejects_implicit_trust_payloads() -> None:
    with pytest.raises(ValidationError) as missing:
        SSHHostKeyAcceptRequest.model_validate({"host": "192.0.2.10", "port": 2222, "user": "tester"})
    with pytest.raises(ValidationError) as wrong_confirmation:
        SSHHostKeyAcceptRequest.model_validate(
            {
                "host": "192.0.2.10",
                "port": 2222,
                "user": "tester",
                "confirmation": "accept",
                "fingerprintSha256": "SHA256:test-fingerprint",
            }
        )

    assert any(error["loc"] == ("confirmation",) for error in missing.value.errors())
    assert any(error["type"] == "literal_error" for error in wrong_confirmation.value.errors())


def test_ssh_host_key_requests_reject_secret_bearing_payloads() -> None:
    for model in (SSHHostKeyScanRequest, SSHHostKeyAcceptRequest):
        payload = {
            "host": "192.0.2.10",
            "port": 2222,
            "user": "tester",
            "password": "secret",
        }
        if model is SSHHostKeyAcceptRequest:
            payload.update(
                {
                    "confirmation": "trust-ssh-host-key",
                    "fingerprintSha256": "SHA256:test-fingerprint",
                }
            )
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate(payload)
        assert any(error["loc"] == ("password",) and error["type"] == "extra_forbidden" for error in exc_info.value.errors())


def test_runtime_accept_ssh_host_key_requires_confirmation_token(monkeypatch, tmp_path: Path) -> None:
    service = _service()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", _runtime_cfg)
    monkeypatch.setattr("core.app_runtime.service.scan_remote_ssh_host_key", lambda *args, **kwargs: _scan_result(tmp_path))
    server_id = service.scan_ssh_host_key_for_request()["data"]["serverId"]

    with pytest.raises(RuntimeServiceError) as exc_info:
        service.accept_server_host_key(
            server_id,
            {
                "host": "192.0.2.10",
                "port": 2222,
                "user": "tester",
                "fingerprintSha256": "SHA256:test-fingerprint",
            },
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["reasonCode"] == "SSH_HOST_KEY_CONFIRMATION_REQUIRED"


def test_runtime_host_key_target_rejects_secret_or_auth_artifact_fields(monkeypatch) -> None:
    service = _service()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", _runtime_cfg)

    for field in ("password", "password_ref", "identity_ref"):
        with pytest.raises(RuntimeServiceError) as exc_info:
            service.scan_ssh_host_key_for_request(
                {
                    "host": "192.0.2.10",
                    "port": 2222,
                    "user": "tester",
                    field: "secret",
                }
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["reasonCode"] == "SSH_HOST_KEY_UNSUPPORTED_FIELD"
        assert exc_info.value.detail["field"] == field
