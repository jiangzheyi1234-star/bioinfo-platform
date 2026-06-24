from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from .secret_provider import ResolvedSecret
from .webhook_signature_policy import WebhookTriggerSignaturePolicy
from .webhook_signature_verification import WebhookSignatureVerificationInput


WEBHOOK_RAW_BODY_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class WebhookRawRequestEnvelope:
    raw_body: bytes = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)
    received_at: datetime
    body_sha256: str
    body_size_bytes: int
    content_type: str | None
    header_names: tuple[str, ...]
    schema_version: Literal["webhook-raw-request-envelope.v1"] = "webhook-raw-request-envelope.v1"

    def safe_details(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "bodySha256": self.body_sha256,
            "bodySizeBytes": self.body_size_bytes,
            "contentType": self.content_type,
            "receivedAt": self.received_at.isoformat(),
            "headerNames": list(self.header_names),
        }


class WebhookRawRequestError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        safe_details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.safe_details = dict(safe_details or {})


HeaderInput = Mapping[object, object] | Iterable[tuple[object, object]]


def build_webhook_raw_request_envelope(
    *,
    raw_body: bytes | bytearray | memoryview,
    headers: HeaderInput,
    received_at: datetime,
    max_body_bytes: int = WEBHOOK_RAW_BODY_MAX_BYTES,
) -> WebhookRawRequestEnvelope:
    body = _raw_body_bytes(raw_body)
    _require_received_at(received_at)
    if headers is None:
        _raise("WEBHOOK_RAW_REQUEST_HEADERS_REQUIRED")
    if max_body_bytes < 1:
        _raise("WEBHOOK_RAW_REQUEST_BODY_LIMIT_INVALID")
    body_size = len(body)
    body_sha256 = hashlib.sha256(body).hexdigest()
    if body_size > max_body_bytes:
        _raise(
            "WEBHOOK_RAW_REQUEST_BODY_TOO_LARGE",
            body_sha256=body_sha256,
            body_size_bytes=body_size,
        )
    normalized_headers = _normalized_headers(headers)
    return WebhookRawRequestEnvelope(
        raw_body=body,
        headers=normalized_headers,
        received_at=received_at.astimezone(timezone.utc),
        body_sha256=body_sha256,
        body_size_bytes=body_size,
        content_type=_content_type(normalized_headers),
        header_names=tuple(_canonical_header_name(name) for name in sorted(normalized_headers)),
    )


def json_payload_from_envelope(envelope: WebhookRawRequestEnvelope) -> dict[str, Any]:
    try:
        decoded = envelope.raw_body.decode("utf-8")
    except UnicodeDecodeError:
        _raise(
            "WEBHOOK_RAW_REQUEST_BODY_UTF8_REQUIRED",
            body_sha256=envelope.body_sha256,
            body_size_bytes=envelope.body_size_bytes,
        )
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        _raise(
            "WEBHOOK_RAW_REQUEST_BODY_JSON_INVALID",
            body_sha256=envelope.body_sha256,
            body_size_bytes=envelope.body_size_bytes,
        )
    if not isinstance(payload, dict):
        _raise(
            "WEBHOOK_RAW_REQUEST_BODY_JSON_OBJECT_REQUIRED",
            body_sha256=envelope.body_sha256,
            body_size_bytes=envelope.body_size_bytes,
        )
    return payload


def webhook_verification_input_from_envelope(
    envelope: WebhookRawRequestEnvelope,
    *,
    policy: WebhookTriggerSignaturePolicy,
    secret: ResolvedSecret | bytes,
) -> WebhookSignatureVerificationInput:
    if policy is None:
        _raise("WEBHOOK_RAW_REQUEST_POLICY_REQUIRED")
    if policy.mode != "required" or not policy.verification_provider:
        _raise("WEBHOOK_RAW_REQUEST_SIGNATURE_POLICY_UNSUPPORTED")
    return WebhookSignatureVerificationInput(
        provider=policy.verification_provider,
        raw_body=envelope.raw_body,
        headers=envelope.headers,
        secret=secret.value if isinstance(secret, ResolvedSecret) else secret,
        received_at=envelope.received_at,
        tolerance_seconds=policy.tolerance_seconds,
    )


def _raw_body_bytes(raw_body: bytes | bytearray | memoryview) -> bytes:
    if raw_body is None:
        _raise("WEBHOOK_RAW_REQUEST_BODY_REQUIRED")
    if isinstance(raw_body, bytes):
        return raw_body
    if isinstance(raw_body, bytearray):
        return bytes(raw_body)
    if isinstance(raw_body, memoryview):
        return raw_body.tobytes()
    _raise("WEBHOOK_RAW_REQUEST_BODY_TYPE_UNSUPPORTED")


def _require_received_at(received_at: datetime) -> None:
    if not isinstance(received_at, datetime):
        _raise("WEBHOOK_RAW_REQUEST_RECEIVED_AT_REQUIRED")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        _raise("WEBHOOK_RAW_REQUEST_RECEIVED_AT_NAIVE")


def _normalized_headers(headers: HeaderInput) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, raw_value in _header_items(headers):
        key = str(raw_key or "").strip().lower()
        if not key:
            _raise("WEBHOOK_RAW_REQUEST_HEADER_NAME_MALFORMED")
        value = str(raw_value or "").strip()
        if "\r" in value or "\n" in value:
            _raise("WEBHOOK_RAW_REQUEST_HEADER_VALUE_MALFORMED", header=_canonical_header_name(key))
        if key in normalized and normalized[key] != value:
            _raise("WEBHOOK_RAW_REQUEST_HEADER_CONFLICT", header=_canonical_header_name(key))
        normalized[key] = value
    return normalized


def _header_items(headers: HeaderInput) -> Iterable[tuple[object, object]]:
    if isinstance(headers, Mapping):
        return headers.items()
    return headers


def _content_type(headers: Mapping[str, str]) -> str | None:
    value = str(headers.get("content-type") or "").strip()
    return value or None


def _canonical_header_name(name: str) -> str:
    if name == "etag":
        return "ETag"
    return "-".join(part.capitalize() for part in name.split("-"))


def _raise(
    code: str,
    *,
    header: str | None = None,
    body_sha256: str | None = None,
    body_size_bytes: int | None = None,
) -> None:
    details: dict[str, object] = {}
    if header:
        details["header"] = header
    if body_sha256:
        details["bodySha256"] = body_sha256
    if body_size_bytes is not None:
        details["bodySizeBytes"] = body_size_bytes
    raise WebhookRawRequestError(code, safe_details=details)
