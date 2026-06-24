from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac

import pytest

from apps.remote_runner.secret_provider import (
    EnvironmentSecretProvider,
    MappingSecretProvider,
    SecretProviderError,
    SecretProviderRecord,
    parse_secret_ref,
    resolve_secret_ref,
)
from apps.remote_runner.webhook_signature_policy import resolve_webhook_trigger_signature_policy
from apps.remote_runner.webhook_signature_verification import (
    WebhookSignatureVerificationInput,
    verify_webhook_signature,
)


def test_secret_ref_parses_safe_descriptor_without_raw_ref_leak() -> None:
    descriptor = parse_secret_ref(" Vault://webhooks/github/main ", purpose="webhook-signing-secret")

    assert descriptor.scheme == "vault"
    assert descriptor.provider_kind == "external-vault"
    assert descriptor.purpose == "webhook-signing-secret"
    assert descriptor.canonical_ref == "vault://webhooks/github/main"
    assert descriptor.ref_hash == hashlib.sha256(b"vault://webhooks/github/main").hexdigest()
    assert descriptor.safe_details() == {
        "schemaVersion": "remote-runner-secret-ref.v1",
        "refHash": descriptor.ref_hash,
        "scheme": "vault",
        "providerKind": "external-vault",
        "purpose": "webhook-signing-secret",
        "version": None,
    }
    assert "vault://webhooks/github/main" not in repr(descriptor)
    assert "webhooks/github/main" not in repr(descriptor.safe_details())


@pytest.mark.parametrize(
    ("ref", "scheme", "provider_kind"),
    [
        ("env://H2OMETA_WEBHOOK_SECRET", "env", "environment"),
        ("keyring://webhooks/github/main", "keyring", "os-keyring"),
        ("secret://webhooks/github/main", "secret", "remote-runner-secret"),
        ("vault://webhooks/github/main", "vault", "external-vault"),
    ],
)
def test_supported_secret_ref_schemes(ref: str, scheme: str, provider_kind: str) -> None:
    descriptor = parse_secret_ref(ref, purpose="webhook-signing-secret")

    assert descriptor.scheme == scheme
    assert descriptor.provider_kind == provider_kind


@pytest.mark.parametrize(
    ("ref", "code"),
    [
        ("", "SECRET_REF_REQUIRED"),
        ("plain-secret-value", "SECRET_REF_MALFORMED"),
        ("secret://webhooks/github/main?raw=1", "SECRET_REF_MALFORMED"),
        ("secret://webhooks/github/main#frag", "SECRET_REF_MALFORMED"),
        ("secret://white space", "SECRET_REF_MALFORMED"),
        ("env://lowercase_name", "SECRET_REF_MALFORMED"),
        ("inline://secret-value", "SECRET_REF_INLINE_VALUE_FORBIDDEN"),
        ("s3://bucket/key", "SECRET_REF_SCHEME_UNSUPPORTED"),
        (f"secret://{'a' * 256}", "SECRET_REF_TOO_LONG"),
    ],
)
def test_secret_ref_rejects_malformed_or_raw_refs_without_echo(ref: str, code: str) -> None:
    _assert_secret_error(ref, code, forbidden_text=ref)


def test_secret_ref_rejects_unsupported_purpose() -> None:
    with pytest.raises(SecretProviderError) as exc_info:
        parse_secret_ref("secret://webhooks/github/main", purpose="unknown-purpose")

    assert exc_info.value.code == "SECRET_PURPOSE_UNSUPPORTED"
    assert str(exc_info.value) == "SECRET_PURPOSE_UNSUPPORTED"


def test_mapping_secret_provider_resolves_bytes_without_value_or_ref_leak() -> None:
    provider = MappingSecretProvider(
        {
            "secret://webhooks/github/main": SecretProviderRecord(
                value=b"github-secret",
                version="v3",
            )
        }
    )

    resolved = resolve_secret_ref(
        provider,
        "secret://webhooks/github/main",
        purpose="webhook-signing-secret",
    )

    assert resolved.value == b"github-secret"
    assert resolved.descriptor.version == "v3"
    assert resolved.safe_details()["version"] == "v3"
    assert "github-secret" not in repr(resolved)
    assert "secret://webhooks/github/main" not in repr(resolved)
    assert "secret://webhooks/github/main" not in repr(resolved.safe_details())


def test_environment_secret_provider_resolves_env_refs_without_value_leak() -> None:
    provider = EnvironmentSecretProvider({"H2OMETA_WEBHOOK_SECRET": "github-secret"})

    resolved = resolve_secret_ref(provider, "env://H2OMETA_WEBHOOK_SECRET", purpose="webhook-signing-secret")

    assert resolved.value == b"github-secret"
    assert resolved.descriptor.scheme == "env"
    assert resolved.safe_details()["providerKind"] == "environment"
    assert "github-secret" not in repr(resolved)
    assert "H2OMETA_WEBHOOK_SECRET" not in repr(resolved.safe_details())


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (b"", "SECRET_VALUE_EMPTY"),
        ("", "SECRET_VALUE_EMPTY"),
        (object(), "SECRET_VALUE_TYPE_UNSUPPORTED"),
    ],
)
def test_secret_provider_rejects_empty_or_unsupported_values(value: object, code: str) -> None:
    provider = MappingSecretProvider({"secret://webhooks/github/main": value})  # type: ignore[arg-type]

    with pytest.raises(SecretProviderError) as exc_info:
        resolve_secret_ref(provider, "secret://webhooks/github/main", purpose="webhook-signing-secret")

    assert exc_info.value.code == code
    assert "secret://webhooks/github/main" not in repr(exc_info.value.safe_details)


def test_secret_provider_reports_missing_provider_and_missing_ref_safely() -> None:
    provider = MappingSecretProvider({})

    with pytest.raises(SecretProviderError) as exc_info:
        resolve_secret_ref(provider, "secret://webhooks/github/main", purpose="webhook-signing-secret")

    error = exc_info.value
    assert error.code == "SECRET_NOT_FOUND"
    assert "secret://webhooks/github/main" not in repr(error)
    assert "secret://webhooks/github/main" not in repr(error.safe_details)
    assert set(error.safe_details) == {"schemaVersion", "refHash", "scheme", "providerKind", "purpose", "version"}


def test_webhook_signature_policy_secret_ref_resolves_for_verifier_input() -> None:
    body = b'{"zen":"Keep it logically awesome."}'
    provider = MappingSecretProvider({"secret://webhooks/github/main": b"github-secret"})
    policy = resolve_webhook_trigger_signature_policy(
        {
            "provider": "github",
            "signature": {
                "secretRef": "secret://webhooks/github/main",
            },
        }
    )
    secret = resolve_secret_ref(provider, policy.secret_ref, purpose="webhook-signing-secret")
    signature = "sha256=" + hmac.new(secret.value, body, hashlib.sha256).hexdigest()

    verified = verify_webhook_signature(
        WebhookSignatureVerificationInput(
            provider=policy.verification_provider or "",
            raw_body=body,
            headers={"X-Hub-Signature-256": signature},
            secret=secret.value,
            received_at=datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
            tolerance_seconds=policy.tolerance_seconds,
        )
    )

    assert verified.signature_state == "verified"
    assert "secretRef" not in secret.safe_details()
    assert "github-secret" not in repr(secret.safe_details())
    assert "secret://webhooks/github/main" not in repr(secret.safe_details())


def _assert_secret_error(ref: str, code: str, *, forbidden_text: str) -> None:
    with pytest.raises(SecretProviderError) as exc_info:
        parse_secret_ref(ref, purpose="webhook-signing-secret")
    error = exc_info.value
    assert error.code == code
    assert str(error) == code
    if forbidden_text:
        assert forbidden_text not in str(error)
        assert forbidden_text not in repr(error)
        assert forbidden_text not in repr(error.safe_details)
