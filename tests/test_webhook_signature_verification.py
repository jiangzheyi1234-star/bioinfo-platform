from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac

import pytest

from apps.remote_runner.webhook_signature_verification import (
    WebhookSignatureVerificationError,
    WebhookSignatureVerificationInput,
    verify_webhook_signature,
)


RECEIVED_AT = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


def test_github_webhook_signature_verifies_hmac_sha256_without_secret_leak() -> None:
    body = b'{"zen":"Keep it logically awesome."}'
    secret = b"github-secret"
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    result = verify_webhook_signature(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={"X-Hub-Signature-256": signature},
            raw_body=body,
            secret=secret,
            received_at=RECEIVED_AT,
        )
    )

    assert result.provider == "github"
    assert result.signature_state == "verified"
    assert result.algorithm == "hmac-sha256"
    assert result.signature_header == "X-Hub-Signature-256"
    assert result.timestamp is None
    assert result.signed_payload_sha256 == hashlib.sha256(body).hexdigest()
    assert "github-secret" not in repr(result)


def test_github_webhook_signature_rejects_mismatch_missing_and_sha1_fallback() -> None:
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
            raw_body=b"{}",
            secret=b"github-secret",
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_MISMATCH",
        "mismatch",
    )
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={},
            raw_body=b"{}",
            secret=b"github-secret",
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_HEADER_REQUIRED",
        "missing",
    )
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={"X-Hub-Signature": "sha1=bad", "X-Hub-Signature-256": "sha256=" + "0" * 64},
            raw_body=b"{}",
            secret=b"github-secret",
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_ALGORITHM_UNSUPPORTED",
        "malformed",
    )


def test_slack_webhook_signature_verifies_timestamped_body_and_rejects_replay() -> None:
    body = b"token=ignored&team_id=T0001"
    secret = b"slack-secret"
    timestamp = "1700000000"
    signed = b"v0:" + timestamp.encode("utf-8") + b":" + body
    signature = "v0=" + hmac.new(secret, signed, hashlib.sha256).hexdigest()

    result = verify_webhook_signature(
        WebhookSignatureVerificationInput(
            provider="slack",
            headers={"X-Slack-Signature": signature, "X-Slack-Request-Timestamp": timestamp},
            raw_body=body,
            secret=secret,
            received_at=RECEIVED_AT,
        )
    )

    assert result.signature_state == "verified"
    assert result.timestamp == 1_700_000_000
    assert result.tolerance_seconds == 300
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="slack",
            headers={"X-Slack-Signature": "v1=" + "0" * 64, "X-Slack-Request-Timestamp": timestamp},
            raw_body=body,
            secret=secret,
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_MALFORMED",
        "malformed",
    )
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="slack",
            headers={"X-Slack-Signature": signature, "X-Slack-Request-Timestamp": timestamp},
            raw_body=body,
            secret=secret,
            received_at=datetime.fromtimestamp(1_700_001_000, tz=timezone.utc),
        ),
        "WEBHOOK_SIGNATURE_TIMESTAMP_EXPIRED",
        "expired",
    )


def test_stripe_webhook_signature_accepts_any_v1_signature_and_rejects_stale_timestamp() -> None:
    body = b'{"id":"evt_123"}'
    secret = b"stripe-secret"
    timestamp = "1700000000"
    signed_payload = timestamp.encode("utf-8") + b"." + body
    valid = hmac.new(secret, signed_payload, hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1=bad,v1={valid}"

    result = verify_webhook_signature(
        WebhookSignatureVerificationInput(
            provider="stripe",
            headers={"Stripe-Signature": header},
            raw_body=body,
            secret=secret,
            received_at=RECEIVED_AT,
        )
    )

    assert result.provider == "stripe"
    assert result.signature_state == "verified"
    assert result.timestamp_header == "Stripe-Signature:t"
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="stripe",
            headers={"Stripe-Signature": f"t={timestamp},v0={valid}"},
            raw_body=body,
            secret=secret,
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_MALFORMED",
        "malformed",
    )
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="stripe",
            headers={"Stripe-Signature": header},
            raw_body=body,
            secret=secret,
            received_at=datetime.fromtimestamp(1_700_001_000, tz=timezone.utc),
        ),
        "WEBHOOK_SIGNATURE_TIMESTAMP_EXPIRED",
        "expired",
    )


def test_signature_verification_uses_raw_body_bytes_not_reserialized_json() -> None:
    compact = b'{"id":"evt_123"}'
    pretty = b'{\n  "id": "evt_123"\n}'
    secret = b"github-secret"
    signature = "sha256=" + hmac.new(secret, compact, hashlib.sha256).hexdigest()

    _assert_error(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={"X-Hub-Signature-256": signature},
            raw_body=pretty,
            secret=secret,
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_MISMATCH",
        "mismatch",
    )


def test_signature_verification_rejects_duplicate_conflicting_headers_without_secret_leak() -> None:
    input = WebhookSignatureVerificationInput(
        provider="github",
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "x-hub-signature-256": "sha256=" + "1" * 64},
        raw_body=b"secret-body",
        secret=b"secret-value",
        received_at=RECEIVED_AT,
    )

    _assert_error(input, "WEBHOOK_SIGNATURE_HEADER_CONFLICT", "malformed")


def test_signature_verification_fails_loudly_for_missing_secret_or_unknown_provider() -> None:
    _assert_error(
        WebhookSignatureVerificationInput(
            provider="github",
            headers={},
            raw_body=b"{}",
            secret=b"",
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_SECRET_REQUIRED",
        "missing",
    )

    _assert_error(
        WebhookSignatureVerificationInput(
            provider="unknown",
            headers={},
            raw_body=b"{}",
            secret=b"secret",
            received_at=RECEIVED_AT,
        ),
        "WEBHOOK_SIGNATURE_PROVIDER_UNSUPPORTED",
        "unsupported",
    )


def _assert_error(
    input: WebhookSignatureVerificationInput,
    code: str,
    signature_state: str,
) -> None:
    with pytest.raises(WebhookSignatureVerificationError) as exc_info:
        verify_webhook_signature(input)
    error = exc_info.value
    assert error.code == code
    assert error.signature_state == signature_state
    assert str(error) == code
    assert "secret-value" not in str(error)
    assert "secret-body" not in repr(error)
    assert "sha256=" not in str(error.safe_details)
