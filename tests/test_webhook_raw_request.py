from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json

import pytest

from apps.remote_runner.api_models import WorkflowTriggerInboxEventRequest
from apps.remote_runner.secret_provider import MappingSecretProvider, resolve_secret_ref
from apps.remote_runner.webhook_raw_request import (
    WebhookRawRequestError,
    build_webhook_raw_request_envelope,
    json_payload_from_envelope,
    webhook_verification_input_from_envelope,
)
from apps.remote_runner.webhook_signature_policy import resolve_webhook_trigger_signature_policy
from apps.remote_runner.webhook_signature_verification import verify_webhook_signature


RECEIVED_AT = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)


def test_raw_webhook_envelope_preserves_body_headers_time_and_safe_details() -> None:
    body = b'{\n  "source": "instrument-qc",\n  "eventId": "evt_001"\n}'
    signature = "sha256=" + "a" * 64

    envelope = build_webhook_raw_request_envelope(
        raw_body=bytearray(body),
        headers={
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
        received_at=RECEIVED_AT,
    )

    assert envelope.raw_body == body
    assert envelope.headers["x-hub-signature-256"] == signature
    assert envelope.body_sha256 == hashlib.sha256(body).hexdigest()
    assert envelope.body_size_bytes == len(body)
    assert envelope.content_type == "application/json"
    assert envelope.received_at == RECEIVED_AT
    assert envelope.header_names == ("Content-Type", "X-Hub-Signature-256")
    assert envelope.safe_details() == {
        "schemaVersion": "webhook-raw-request-envelope.v1",
        "bodySha256": hashlib.sha256(body).hexdigest(),
        "bodySizeBytes": len(body),
        "contentType": "application/json",
        "receivedAt": RECEIVED_AT.isoformat(),
        "headerNames": ["Content-Type", "X-Hub-Signature-256"],
    }
    assert signature not in repr(envelope)
    assert body.decode("utf-8") not in repr(envelope)
    assert signature not in repr(envelope.safe_details())
    assert body.decode("utf-8") not in repr(envelope.safe_details())


def test_raw_webhook_envelope_json_payload_feeds_inbox_model_without_reserializing_body() -> None:
    body = b'{\n  "eventType": "dataset.ready",\n  "source": "instrument-qc",\n  "eventId": "evt_001"\n}'
    envelope = build_webhook_raw_request_envelope(raw_body=body, headers={}, received_at=RECEIVED_AT)
    payload = json_payload_from_envelope(envelope)
    request = WorkflowTriggerInboxEventRequest.model_validate(payload)

    assert request.eventType == "dataset.ready"
    assert request.source == "instrument-qc"
    assert request.eventId == "evt_001"
    assert envelope.raw_body != json.dumps(payload, sort_keys=True).encode("utf-8")


def test_raw_webhook_envelope_accepts_non_json_body_for_slack_signature() -> None:
    body = b"token=ignored&team_id=T0001"
    secret = b"slack-secret"
    timestamp = "1700000000"
    signed = b"v0:" + timestamp.encode("utf-8") + b":" + body
    signature = "v0=" + hmac.new(secret, signed, hashlib.sha256).hexdigest()
    policy = resolve_webhook_trigger_signature_policy(
        {"provider": "slack", "signature": {"secretRef": "secret://webhooks/slack/main"}}
    )
    resolved_secret = resolve_secret_ref(
        MappingSecretProvider({"secret://webhooks/slack/main": secret}),
        policy.secret_ref,
        purpose="webhook-signing-secret",
    )
    envelope = build_webhook_raw_request_envelope(
        raw_body=memoryview(body),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Signature": signature,
            "X-Slack-Request-Timestamp": timestamp,
        },
        received_at=RECEIVED_AT,
    )

    verified = verify_webhook_signature(
        webhook_verification_input_from_envelope(envelope, policy=policy, secret=resolved_secret)
    )

    assert verified.signature_state == "verified"
    assert envelope.content_type == "application/x-www-form-urlencoded"
    with pytest.raises(WebhookRawRequestError, match="WEBHOOK_RAW_REQUEST_BODY_JSON_INVALID"):
        json_payload_from_envelope(envelope)


def test_raw_webhook_envelope_is_what_github_signature_verifier_uses() -> None:
    body = b'{\n  "id": "evt_123"\n}'
    reserialized_body = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode("utf-8")
    secret = b"github-secret"
    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    policy = resolve_webhook_trigger_signature_policy(
        {"provider": "github", "signature": {"secretRef": "secret://webhooks/github/main"}}
    )
    envelope = build_webhook_raw_request_envelope(
        raw_body=body,
        headers={"X-Hub-Signature-256": signature},
        received_at=RECEIVED_AT,
    )

    result = verify_webhook_signature(
        webhook_verification_input_from_envelope(envelope, policy=policy, secret=secret)
    )

    assert result.signature_state == "verified"
    assert envelope.raw_body != reserialized_body


def test_raw_webhook_envelope_accepts_duplicate_identical_headers_and_rejects_conflicts() -> None:
    envelope = build_webhook_raw_request_envelope(
        raw_body=b"{}",
        headers=[
            ("X-Hub-Signature-256", "sha256=same"),
            ("x-hub-signature-256", "sha256=same"),
        ],
        received_at=RECEIVED_AT,
    )

    assert envelope.headers["x-hub-signature-256"] == "sha256=same"
    _assert_raw_error(
        raw_body=b"{}",
        headers=[
            ("X-Hub-Signature-256", "sha256=one"),
            ("x-hub-signature-256", "sha256=two"),
        ],
        code="WEBHOOK_RAW_REQUEST_HEADER_CONFLICT",
        forbidden_text="sha256=two",
    )


@pytest.mark.parametrize(
    ("raw_body", "code"),
    [
        (None, "WEBHOOK_RAW_REQUEST_BODY_REQUIRED"),
        ("not-bytes", "WEBHOOK_RAW_REQUEST_BODY_TYPE_UNSUPPORTED"),
    ],
)
def test_raw_webhook_envelope_rejects_missing_or_invalid_body_without_leak(raw_body: object, code: str) -> None:
    _assert_raw_error(raw_body=raw_body, headers={}, code=code, forbidden_text=str(raw_body))


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b'{"source":"instrument-qc"', "WEBHOOK_RAW_REQUEST_BODY_JSON_INVALID"),
        (b'["not", "an", "object"]', "WEBHOOK_RAW_REQUEST_BODY_JSON_OBJECT_REQUIRED"),
        (b"\xff", "WEBHOOK_RAW_REQUEST_BODY_UTF8_REQUIRED"),
    ],
)
def test_json_payload_from_envelope_rejects_non_object_json_without_body_leak(body: bytes, code: str) -> None:
    envelope = build_webhook_raw_request_envelope(raw_body=body, headers={}, received_at=RECEIVED_AT)

    with pytest.raises(WebhookRawRequestError) as exc_info:
        json_payload_from_envelope(envelope)

    error = exc_info.value
    assert error.code == code
    assert str(error) == code
    assert repr(body) not in repr(error)
    assert repr(body) not in repr(error.safe_details)


def test_raw_webhook_envelope_rejects_oversized_body_without_payload_leak() -> None:
    raw_body = b'{"source":"instrument-qc","eventId":"' + (b"a" * 64) + b'"}'

    _assert_raw_error(
        raw_body=raw_body,
        headers={},
        code="WEBHOOK_RAW_REQUEST_BODY_TOO_LARGE",
        forbidden_text=raw_body.decode("utf-8"),
        max_body_bytes=10,
    )


def test_raw_webhook_envelope_rejects_naive_received_at_and_bad_header_values() -> None:
    _assert_raw_error(
        raw_body=b"{}",
        headers={},
        code="WEBHOOK_RAW_REQUEST_RECEIVED_AT_NAIVE",
        forbidden_text="",
        received_at=datetime.fromtimestamp(1_700_000_000),
    )
    _assert_raw_error(
        raw_body=b"{}",
        headers=[("", "value")],
        code="WEBHOOK_RAW_REQUEST_HEADER_NAME_MALFORMED",
        forbidden_text="value",
    )
    _assert_raw_error(
        raw_body=b"{}",
        headers=[("X-Slack-Signature", "v0=line\nbreak")],
        code="WEBHOOK_RAW_REQUEST_HEADER_VALUE_MALFORMED",
        forbidden_text="v0=line",
    )


def test_raw_webhook_envelope_rejects_unsupported_signature_policy() -> None:
    envelope = build_webhook_raw_request_envelope(raw_body=b"{}", headers={}, received_at=RECEIVED_AT)
    policy = resolve_webhook_trigger_signature_policy({"provider": "instrument-qc"})

    _assert_raw_error(
        raw_body=envelope.raw_body,
        headers=envelope.headers,
        code="WEBHOOK_RAW_REQUEST_SIGNATURE_POLICY_UNSUPPORTED",
        forbidden_text="",
        call=lambda: webhook_verification_input_from_envelope(envelope, policy=policy, secret=b"secret"),
    )


def _assert_raw_error(
    *,
    raw_body: object,
    headers: object,
    code: str,
    forbidden_text: str,
    received_at: object = RECEIVED_AT,
    max_body_bytes: int = 256 * 1024,
    call: object | None = None,
) -> None:
    def default_call() -> object:
        return build_webhook_raw_request_envelope(  # type: ignore[arg-type]
            raw_body=raw_body,
            headers=headers,
            received_at=received_at,  # type: ignore[arg-type]
            max_body_bytes=max_body_bytes,
        )

    with pytest.raises(WebhookRawRequestError) as exc_info:
        (call or default_call)()  # type: ignore[operator]
    error = exc_info.value
    assert error.code == code
    assert str(error) == code
    if forbidden_text:
        assert forbidden_text not in str(error)
        assert forbidden_text not in repr(error)
        assert forbidden_text not in repr(error.safe_details)
