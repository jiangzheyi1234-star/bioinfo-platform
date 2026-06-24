from __future__ import annotations

import pytest

from apps.remote_runner.webhook_signature_policy import (
    WebhookTriggerSignaturePolicyError,
    resolve_webhook_trigger_signature_policy,
)


def test_supported_provider_policy_resolves_without_secret_ref_leak() -> None:
    policy = resolve_webhook_trigger_signature_policy(
        {
            "provider": " GitHub ",
            "signature": {
                "secretRef": "webhook://github/main",
            },
        }
    )

    assert policy.schema_version == "webhook-trigger-signature-policy.v1"
    assert policy.provider == "github"
    assert policy.mode == "required"
    assert policy.verification_provider == "github"
    assert policy.algorithm == "hmac-sha256"
    assert policy.signature_header == "X-Hub-Signature-256"
    assert policy.timestamp_header is None
    assert policy.tolerance_seconds is None
    assert policy.raw_body_required is True
    assert policy.replay_protection_required is False
    assert policy.secret_ref == "webhook://github/main"
    assert "webhook://github/main" not in repr(policy)
    assert "webhook://github/main" not in repr(policy.safe_details())


def test_signature_provider_supports_generic_source_label() -> None:
    policy = resolve_webhook_trigger_signature_policy(
        {
            "provider": "instrument-qc",
            "signature": {
                "provider": "stripe",
                "secretRef": "vault://webhooks/stripe/main",
            },
        }
    )

    assert policy.provider == "instrument-qc"
    assert policy.mode == "required"
    assert policy.verification_provider == "stripe"
    assert policy.signature_header == "Stripe-Signature"
    assert policy.timestamp_header == "Stripe-Signature:t"
    assert policy.tolerance_seconds == 300
    assert policy.replay_protection_required is True


def test_generic_provider_without_signature_policy_is_explicitly_unsupported() -> None:
    policy = resolve_webhook_trigger_signature_policy({"provider": "instrument-qc"})

    assert policy.safe_details() == {
        "schemaVersion": "webhook-trigger-signature-policy.v1",
        "mode": "unsupported",
        "provider": "instrument-qc",
        "verificationProvider": None,
        "algorithm": None,
        "signatureHeader": None,
        "timestampHeader": None,
        "toleranceSeconds": None,
        "replayProtectionRequired": False,
        "rawBodyRequired": False,
    }
    assert policy.secret_ref is None


@pytest.mark.parametrize("provider", ["slack", "stripe"])
def test_timestamped_provider_tolerance_defaults_and_accepts_decimal_string(provider: str) -> None:
    default_policy = resolve_webhook_trigger_signature_policy(
        {"provider": provider, "signature": {"secretRef": f"webhook://{provider}/main"}}
    )
    custom_policy = resolve_webhook_trigger_signature_policy(
        {
            "provider": provider,
            "signature": {
                "secretRef": f"webhook://{provider}/main",
                "toleranceSeconds": "120",
            },
        }
    )

    assert default_policy.tolerance_seconds == 300
    assert custom_policy.tolerance_seconds == 120


@pytest.mark.parametrize("value", [True, 0, -1, 3601, "abc", "1.5"])
def test_timestamped_provider_rejects_malformed_tolerance(value: object) -> None:
    _assert_error(
        {
            "provider": "slack",
            "signature": {
                "secretRef": "webhook://slack/main",
                "toleranceSeconds": value,
            },
        },
        {
            True: "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_MALFORMED",
            0: "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_OUT_OF_RANGE",
            -1: "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_OUT_OF_RANGE",
            3601: "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_OUT_OF_RANGE",
            "abc": "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_MALFORMED",
            "1.5": "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_MALFORMED",
        }[value],
    )


def test_github_rejects_tolerance_because_no_timestamp_header_is_verified() -> None:
    _assert_error(
        {
            "provider": "github",
            "signature": {
                "secretRef": "webhook://github/main",
                "toleranceSeconds": 300,
            },
        },
        "WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_UNSUPPORTED",
    )


@pytest.mark.parametrize("provider", ["github", "slack", "stripe"])
def test_supported_provider_requires_secret_ref(provider: str) -> None:
    _assert_error(
        {"provider": provider, "signature": {}},
        "WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_REQUIRED",
    )


def test_inline_secret_like_fields_are_forbidden_without_value_leak() -> None:
    secret_value = "super-secret-value"
    _assert_error(
        {
            "provider": "instrument-qc",
            "signature": {
                "provider": "github",
                "secretRef": "webhook://github/main",
            },
            "headers": {
                "signingSecret": secret_value,
            },
        },
        "WORKFLOW_TRIGGER_SIGNATURE_INLINE_SECRET_FORBIDDEN",
        forbidden_text=secret_value,
    )


def test_provider_conflict_and_unknown_explicit_provider_fail_loudly() -> None:
    _assert_error(
        {
            "provider": "github",
            "signature": {
                "provider": "slack",
                "secretRef": "webhook://github/main",
            },
        },
        "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_CONFLICT",
    )
    _assert_error(
        {
            "provider": "instrument-qc",
            "signature": {
                "provider": "unknown",
                "secretRef": "webhook://unknown/main",
            },
        },
        "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_UNSUPPORTED",
    )


@pytest.mark.parametrize(
    ("trigger_spec", "code"),
    [
        ({}, "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_REQUIRED"),
        ({"provider": ""}, "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_REQUIRED"),
        ({"provider": "github"}, "WORKFLOW_TRIGGER_SIGNATURE_POLICY_REQUIRED"),
        ({"provider": "github", "signature": []}, "WORKFLOW_TRIGGER_SIGNATURE_POLICY_REQUIRED"),
        (
            {"provider": "github", "signature": {"secretRef": "not-a-secret-ref"}},
            "WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_MALFORMED",
        ),
        (
            {"provider": "github", "signature": {"secretRef": "webhook://github/main", "extra": True}},
            "WORKFLOW_TRIGGER_SIGNATURE_POLICY_FIELD_UNSUPPORTED",
        ),
        (
            {"provider": "github", "signature": {"secretRef": "webhook://github/main", "required": False}},
            "WORKFLOW_TRIGGER_SIGNATURE_REQUIRED_CANNOT_BE_DISABLED",
        ),
    ],
)
def test_malformed_policy_config_fails_loudly(trigger_spec: dict[str, object], code: str) -> None:
    _assert_error(trigger_spec, code)


def _assert_error(
    trigger_spec: dict[str, object],
    code: str,
    *,
    forbidden_text: str | None = None,
) -> None:
    with pytest.raises(WebhookTriggerSignaturePolicyError) as exc_info:
        resolve_webhook_trigger_signature_policy(trigger_spec)
    error = exc_info.value
    assert error.code == code
    assert str(error) == code
    if forbidden_text:
        assert forbidden_text not in str(error)
        assert forbidden_text not in repr(error)
        assert forbidden_text not in repr(error.safe_details)
