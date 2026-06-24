from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from .secret_provider import SecretProviderError, parse_secret_ref
from .webhook_signature_verification import WebhookSignatureProvider, WEBHOOK_SIGNATURE_TOLERANCE_SECONDS


WebhookTriggerSignaturePolicyMode = Literal["required", "unsupported"]
WebhookTriggerSignaturePolicyState = Literal["configured", "missing", "malformed", "unsupported"]
_ALGORITHM = "hmac-sha256"
_MAX_TOLERANCE_SECONDS = 3600
_SIGNATURE_FIELDS = frozenset({"provider", "secretRef", "toleranceSeconds", "required"})
_INLINE_SECRET_FIELD_TOKENS = frozenset(
    {
        "apikey",
        "clientsecret",
        "inlinesecret",
        "password",
        "privatekey",
        "secret",
        "secretvalue",
        "signingsecret",
        "token",
        "webhooksecret",
    }
)
_PROVIDER_HEADERS = {
    "github": ("X-Hub-Signature-256", None),
    "slack": ("X-Slack-Signature", "X-Slack-Request-Timestamp"),
    "stripe": ("Stripe-Signature", "Stripe-Signature:t"),
}
SUPPORTED_WEBHOOK_SIGNATURE_PROVIDERS = frozenset(_PROVIDER_HEADERS)


@dataclass(frozen=True)
class WebhookTriggerSignaturePolicy:
    provider: str
    mode: WebhookTriggerSignaturePolicyMode
    verification_provider: WebhookSignatureProvider | None
    algorithm: Literal["hmac-sha256"] | None
    signature_header: str | None
    timestamp_header: str | None
    tolerance_seconds: int | None
    replay_protection_required: bool = False
    raw_body_required: bool = False
    secret_ref: str | None = field(default=None, repr=False)
    schema_version: Literal["webhook-trigger-signature-policy.v1"] = "webhook-trigger-signature-policy.v1"

    def safe_details(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "mode": self.mode,
            "provider": self.provider,
            "verificationProvider": self.verification_provider,
            "algorithm": self.algorithm,
            "signatureHeader": self.signature_header,
            "timestampHeader": self.timestamp_header,
            "toleranceSeconds": self.tolerance_seconds,
            "replayProtectionRequired": self.replay_protection_required,
            "rawBodyRequired": self.raw_body_required,
        }


class WebhookTriggerSignaturePolicyError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        policy_state: WebhookTriggerSignaturePolicyState,
        safe_details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.policy_state = policy_state
        self.safe_details = dict(safe_details or {})


def resolve_webhook_trigger_signature_policy(trigger_spec: Mapping[str, Any]) -> WebhookTriggerSignaturePolicy:
    if not isinstance(trigger_spec, Mapping):
        _raise("WORKFLOW_TRIGGER_SIGNATURE_TRIGGER_SPEC_REQUIRED", state="missing", field="triggerSpec")
    _reject_inline_secret_fields(trigger_spec, path="triggerSpec")
    provider = _provider_label(trigger_spec.get("provider"))
    signature = _signature_mapping(trigger_spec, provider=provider)
    if signature is None:
        return WebhookTriggerSignaturePolicy(
            provider=provider,
            mode="unsupported",
            verification_provider=None,
            algorithm=None,
            signature_header=None,
            timestamp_header=None,
            tolerance_seconds=None,
        )

    _reject_unknown_signature_fields(signature)
    if signature.get("required", True) is not True:
        _raise("WORKFLOW_TRIGGER_SIGNATURE_REQUIRED_CANNOT_BE_DISABLED", state="malformed", field="signature.required")

    verification_provider = _verification_provider(provider=provider, value=signature.get("provider"))
    signature_header, timestamp_header = _PROVIDER_HEADERS[verification_provider]
    return WebhookTriggerSignaturePolicy(
        provider=provider,
        mode="required",
        verification_provider=verification_provider,
        algorithm=_ALGORITHM,
        secret_ref=_secret_ref(signature.get("secretRef")),
        signature_header=signature_header,
        timestamp_header=timestamp_header,
        tolerance_seconds=_tolerance_seconds(signature, timestamp_header=timestamp_header),
        replay_protection_required=timestamp_header is not None,
        raw_body_required=True,
    )


def _signature_mapping(trigger_spec: Mapping[str, Any], *, provider: str) -> Mapping[str, Any] | None:
    signature = trigger_spec.get("signature")
    if signature is None and provider not in SUPPORTED_WEBHOOK_SIGNATURE_PROVIDERS:
        return None
    if not isinstance(signature, Mapping):
        _raise("WORKFLOW_TRIGGER_SIGNATURE_POLICY_REQUIRED", state="missing", field="signature")
    return signature


def _provider_label(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _raise("WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_REQUIRED", state="missing", field="provider")
    return value.strip().lower()


def _verification_provider(*, provider: str, value: object) -> WebhookSignatureProvider:
    if value is None:
        if provider in SUPPORTED_WEBHOOK_SIGNATURE_PROVIDERS:
            return cast(WebhookSignatureProvider, provider)
        _raise("WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_REQUIRED", state="missing", field="signature.provider")
    if not isinstance(value, str) or not value.strip():
        _raise("WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_REQUIRED", state="missing", field="signature.provider")
    verification_provider = value.strip().lower()
    if verification_provider not in SUPPORTED_WEBHOOK_SIGNATURE_PROVIDERS:
        _raise(
            "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_UNSUPPORTED",
            state="unsupported",
            field="signature.provider",
            provider=verification_provider,
        )
    if provider in SUPPORTED_WEBHOOK_SIGNATURE_PROVIDERS and provider != verification_provider:
        _raise(
            "WORKFLOW_TRIGGER_SIGNATURE_PROVIDER_CONFLICT",
            state="malformed",
            field="signature.provider",
            provider=verification_provider,
        )
    return cast(WebhookSignatureProvider, verification_provider)


def _secret_ref(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _raise("WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_REQUIRED", state="missing", field="signature.secretRef")
    try:
        return parse_secret_ref(value, purpose="webhook-signing-secret").canonical_ref
    except SecretProviderError as exc:
        _raise(
            "WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_MALFORMED",
            state="malformed" if exc.state != "unsupported" else "unsupported",
            field="signature.secretRef",
        )


def _tolerance_seconds(signature: Mapping[str, Any], *, timestamp_header: str | None) -> int | None:
    if "toleranceSeconds" not in signature:
        return WEBHOOK_SIGNATURE_TOLERANCE_SECONDS if timestamp_header else None
    if timestamp_header is None:
        _raise("WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_UNSUPPORTED", state="malformed", field="signature.toleranceSeconds")
    raw = signature["toleranceSeconds"]
    if isinstance(raw, bool):
        _raise("WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_MALFORMED", state="malformed", field="signature.toleranceSeconds")
    if isinstance(raw, str):
        raw = raw.strip()
    if isinstance(raw, str) and raw.isdecimal():
        tolerance = int(raw)
    elif isinstance(raw, int):
        tolerance = raw
    else:
        _raise("WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_MALFORMED", state="malformed", field="signature.toleranceSeconds")
    if tolerance < 1 or tolerance > _MAX_TOLERANCE_SECONDS:
        _raise("WORKFLOW_TRIGGER_SIGNATURE_TOLERANCE_OUT_OF_RANGE", state="malformed", field="signature.toleranceSeconds")
    return tolerance


def _reject_unknown_signature_fields(signature: Mapping[str, Any]) -> None:
    unknown = sorted(str(key) for key in signature if str(key) not in _SIGNATURE_FIELDS)
    if unknown:
        _raise(
            "WORKFLOW_TRIGGER_SIGNATURE_POLICY_FIELD_UNSUPPORTED",
            state="unsupported",
            field=f"signature.{unknown[0]}",
        )


def _reject_inline_secret_fields(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if _secret_field_token(key) in _INLINE_SECRET_FIELD_TOKENS:
                _raise("WORKFLOW_TRIGGER_SIGNATURE_INLINE_SECRET_FORBIDDEN", state="malformed", field=child_path)
            _reject_inline_secret_fields(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_inline_secret_fields(child, path=f"{path}[{index}]")


def _secret_field_token(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())


def _raise(
    code: str,
    *,
    state: WebhookTriggerSignaturePolicyState,
    field: str,
    provider: str | None = None,
) -> None:
    details: dict[str, object] = {"field": field}
    if provider:
        details["provider"] = provider
    raise WebhookTriggerSignaturePolicyError(code, policy_state=state, safe_details=details)
