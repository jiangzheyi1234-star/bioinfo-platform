from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Literal


WebhookSignatureProvider = Literal["github", "slack", "stripe"]
WebhookSignatureState = Literal["verified", "missing", "malformed", "expired", "mismatch", "unsupported"]
WEBHOOK_SIGNATURE_TOLERANCE_SECONDS = 300


@dataclass(frozen=True)
class WebhookSignatureVerificationInput:
    provider: str
    raw_body: bytes
    headers: Mapping[str, str]
    secret: bytes = field(repr=False)
    received_at: datetime
    tolerance_seconds: int | None = None


@dataclass(frozen=True)
class WebhookSignatureVerificationResult:
    provider: WebhookSignatureProvider
    signature_state: Literal["verified"]
    algorithm: Literal["hmac-sha256"]
    signature_header: str
    timestamp_header: str | None
    timestamp: int | None
    tolerance_seconds: int | None
    signed_payload_sha256: str


class WebhookSignatureVerificationError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        provider: str,
        signature_state: WebhookSignatureState,
        safe_details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.provider = provider
        self.signature_state = signature_state
        self.safe_details = dict(safe_details or {})


def verify_webhook_signature(input: WebhookSignatureVerificationInput) -> WebhookSignatureVerificationResult:
    if not input.secret:
        raise WebhookSignatureVerificationError(
            "WEBHOOK_SIGNATURE_SECRET_REQUIRED",
            provider=input.provider,
            signature_state="missing",
        )
    if input.provider == "github":
        return _verify_github(input)
    if input.provider == "slack":
        return _verify_slack(input)
    if input.provider == "stripe":
        return _verify_stripe(input)
    raise WebhookSignatureVerificationError(
        "WEBHOOK_SIGNATURE_PROVIDER_UNSUPPORTED",
        provider=str(input.provider),
        signature_state="unsupported",
    )


def _verify_github(input: WebhookSignatureVerificationInput) -> WebhookSignatureVerificationResult:
    if _optional_header(input.headers, "x-hub-signature", input=input):
        _raise("WEBHOOK_SIGNATURE_ALGORITHM_UNSUPPORTED", input=input, state="malformed", header="X-Hub-Signature")
    signature = _required_header(input.headers, "x-hub-signature-256", input=input)
    if not signature.startswith("sha256=") or len(signature) != len("sha256=") + 64:
        _raise("WEBHOOK_SIGNATURE_MALFORMED", input=input, state="malformed", header="X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(input.secret, input.raw_body, hashlib.sha256).hexdigest()
    _require_match(signature, expected, input=input, header="X-Hub-Signature-256")
    return _verified_result(input, signature_header="X-Hub-Signature-256", timestamp_header=None, timestamp=None)


def _verify_slack(input: WebhookSignatureVerificationInput) -> WebhookSignatureVerificationResult:
    signature = _required_header(input.headers, "x-slack-signature", input=input)
    timestamp_value = _required_header(input.headers, "x-slack-request-timestamp", input=input)
    timestamp = _verified_timestamp(timestamp_value, input=input)
    if not signature.startswith("v0=") or len(signature) != len("v0=") + 64:
        _raise("WEBHOOK_SIGNATURE_MALFORMED", input=input, state="malformed", header="X-Slack-Signature")
    base = b"v0:" + timestamp_value.encode("utf-8") + b":" + input.raw_body
    expected = "v0=" + hmac.new(input.secret, base, hashlib.sha256).hexdigest()
    _require_match(signature, expected, input=input, header="X-Slack-Signature")
    return _verified_result(
        input,
        signature_header="X-Slack-Signature",
        timestamp_header="X-Slack-Request-Timestamp",
        timestamp=timestamp,
    )


def _verify_stripe(input: WebhookSignatureVerificationInput) -> WebhookSignatureVerificationResult:
    signature = _required_header(input.headers, "stripe-signature", input=input)
    parts = _stripe_signature_parts(signature)
    timestamps = parts.get("t") or []
    signatures = parts.get("v1") or []
    unsupported_versions = sorted(key for key in parts if key not in {"t", "v1"})
    if unsupported_versions or len(timestamps) != 1 or not signatures:
        _raise("WEBHOOK_SIGNATURE_MALFORMED", input=input, state="malformed", header="Stripe-Signature")
    timestamp_value = timestamps[0]
    timestamp = _verified_timestamp(timestamp_value, input=input)
    signed_payload = timestamp_value.encode("utf-8") + b"." + input.raw_body
    expected = hmac.new(input.secret, signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(candidate, expected) for candidate in signatures):
        _raise("WEBHOOK_SIGNATURE_MISMATCH", input=input, state="mismatch", header="Stripe-Signature")
    return _verified_result(
        input,
        signature_header="Stripe-Signature",
        timestamp_header="Stripe-Signature:t",
        timestamp=timestamp,
    )


def _required_header(headers: Mapping[str, str], name: str, *, input: WebhookSignatureVerificationInput) -> str:
    value = _optional_header(headers, name, input=input)
    if not value:
        _raise("WEBHOOK_SIGNATURE_HEADER_REQUIRED", input=input, state="missing", header=_canonical_header(name))
    return value


def _optional_header(
    headers: Mapping[str, str],
    name: str,
    *,
    input: WebhookSignatureVerificationInput,
) -> str:
    lowered: dict[str, str] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key).lower()
        value = str(raw_value).strip()
        if key in lowered and lowered[key] != value:
            raise WebhookSignatureVerificationError(
                "WEBHOOK_SIGNATURE_HEADER_CONFLICT",
                provider=input.provider,
                signature_state="malformed",
                safe_details={"header": _canonical_header(name)},
            )
        lowered[key] = value
    return lowered.get(name.lower(), "")


def _verified_timestamp(timestamp_value: str, *, input: WebhookSignatureVerificationInput) -> int:
    try:
        timestamp = int(timestamp_value)
    except (TypeError, ValueError):
        _raise("WEBHOOK_SIGNATURE_TIMESTAMP_MALFORMED", input=input, state="malformed")
    received_at = input.received_at.astimezone(timezone.utc)
    tolerance_seconds = _tolerance(input)
    if abs(int(received_at.timestamp()) - timestamp) > tolerance_seconds:
        _raise("WEBHOOK_SIGNATURE_TIMESTAMP_EXPIRED", input=input, state="expired")
    return timestamp


def _tolerance(input: WebhookSignatureVerificationInput) -> int:
    if input.tolerance_seconds is None:
        return WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    return max(0, int(input.tolerance_seconds))


def _stripe_signature_parts(value: str) -> dict[str, list[str]]:
    parts: dict[str, list[str]] = {}
    for item in value.split(","):
        key, separator, raw = item.partition("=")
        if not separator:
            continue
        parts.setdefault(key.strip(), []).append(raw.strip())
    return parts


def _require_match(
    provided: str,
    expected: str,
    *,
    input: WebhookSignatureVerificationInput,
    header: str,
) -> None:
    if not hmac.compare_digest(provided, expected):
        _raise("WEBHOOK_SIGNATURE_MISMATCH", input=input, state="mismatch", header=header)


def _verified_result(
    input: WebhookSignatureVerificationInput,
    *,
    signature_header: str,
    timestamp_header: str | None,
    timestamp: int | None,
) -> WebhookSignatureVerificationResult:
    return WebhookSignatureVerificationResult(
        provider=input.provider,
        signature_state="verified",
        algorithm="hmac-sha256",
        signature_header=signature_header,
        timestamp_header=timestamp_header,
        timestamp=timestamp,
        tolerance_seconds=_tolerance(input) if timestamp is not None else None,
        signed_payload_sha256=hashlib.sha256(input.raw_body).hexdigest(),
    )


def _raise(
    code: str,
    *,
    input: WebhookSignatureVerificationInput,
    state: WebhookSignatureState,
    header: str | None = None,
) -> None:
    details = {"header": header} if header else {}
    raise WebhookSignatureVerificationError(
        code,
        provider=input.provider,
        signature_state=state,
        safe_details=details,
    )


def _canonical_header(name: str) -> str:
    return "-".join(part.capitalize() for part in name.split("-"))
