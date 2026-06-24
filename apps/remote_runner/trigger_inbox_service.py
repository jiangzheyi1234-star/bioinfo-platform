from __future__ import annotations

import json
from typing import Any

from .api_models import WorkflowTriggerEventRequest, WorkflowTriggerInboxEventRequest
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .route_utils import request_payload
from .secret_provider import (
    SecretProvider,
    SecretProviderError,
    default_webhook_secret_provider,
    resolve_secret_ref,
)
from .trigger_inbox_storage import (
    inbox_event_summary,
    list_workflow_trigger_inbox_events,
    mark_workflow_trigger_inbox_dead_lettered,
    mark_workflow_trigger_inbox_dispatching,
    mark_workflow_trigger_inbox_replay_failed,
    mark_workflow_trigger_inbox_submitted,
    record_workflow_trigger_inbox_event,
)
from .trigger_service import submit_workflow_trigger_event_from_request
from .trigger_storage import fetch_workflow_trigger_event_for_dedupe, require_workflow_trigger
from .webhook_raw_request import WebhookRawRequestEnvelope, webhook_verification_input_from_envelope
from .webhook_signature_policy import (
    WebhookTriggerSignaturePolicy,
    WebhookTriggerSignaturePolicyError,
    resolve_webhook_trigger_signature_policy,
)
from .webhook_signature_verification import (
    WebhookSignatureVerificationError,
    WebhookSignatureVerificationResult,
    verify_webhook_signature,
)


TRIGGER_EVENT_PAYLOAD_MAX_BYTES = 256 * 1024


def list_workflow_trigger_inbox_events_from_storage(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    require_workflow_trigger(cfg, trigger_id)
    return {"data": list_workflow_trigger_inbox_events(cfg, trigger_id, state=state, limit=limit)}


def submit_workflow_trigger_inbox_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    request: WorkflowTriggerInboxEventRequest,
    *,
    raw_envelope: WebhookRawRequestEnvelope | None = None,
    secret_provider: SecretProvider | None = None,
    signature_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type != "webhook":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {source_type}")
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    _enforce_payload_size(request_payload(request).get("payload") or {})
    if signature_metadata is None:
        signature_metadata = _signature_metadata_for_trigger(
            cfg,
            trigger,
            raw_envelope=raw_envelope,
            secret_provider=secret_provider,
        )
    inbox = _record_inbox_event(
        cfg,
        trigger=trigger,
        request=request,
        source=source,
        event_id=event_id,
        signature_metadata=signature_metadata,
    )
    try:
        mark_workflow_trigger_inbox_dispatching(cfg, inbox_event_id=str(inbox["inboxEventId"]))
        response = submit_workflow_trigger_event_from_request(cfg, trigger_id, _inbox_event_request(request))
        event = response["data"]["event"]
        run = response["data"]["run"]
        inbox = mark_workflow_trigger_inbox_submitted(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            trigger_event_id=str(event["triggerEventId"]),
            run_id=str(run["runId"]),
        )
        response["data"]["inbox"] = inbox_event_summary(inbox)
        return response
    except Exception as exc:
        _mark_inbox_dispatch_dead_lettered(cfg, trigger=trigger, request=request, inbox=inbox, exc=exc)
        raise


def find_workflow_trigger_inbox_trigger_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerInboxEventRequest,
) -> dict[str, Any] | None:
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    return fetch_workflow_trigger_event_for_dedupe(
        cfg,
        trigger_id=str(trigger["triggerId"]),
        idempotency_key=f"webhook:{source}:{event_id}",
        external_event_id=f"{source}:{event_id}",
    )


def _inbox_event_request(request: WorkflowTriggerInboxEventRequest) -> WorkflowTriggerEventRequest:
    source = _required_text(request.source, "WORKFLOW_TRIGGER_INBOX_SOURCE_REQUIRED")
    event_id = _required_text(request.eventId, "WORKFLOW_TRIGGER_INBOX_EVENT_ID_REQUIRED")
    correlation_id = str(request.correlationId or "").strip()
    actor = str(request.actor or "").strip()
    external_event_id = f"{source}:{event_id}"
    context = {
        "source": source,
        "eventId": event_id,
        **({"correlationId": correlation_id} if correlation_id else {}),
        **({"actor": actor} if actor else {}),
    }
    return WorkflowTriggerEventRequest(
        eventType=str(request.eventType or "webhook"),
        externalEventId=external_event_id,
        idempotencyKey=f"webhook:{source}:{event_id}",
        cursor=str(request.cursor or external_event_id),
        payload={"eventContext": context, "payload": request_payload(request).get("payload") or {}},
    )


def _inbox_dedupe_key(trigger: dict[str, Any], *, source: str, event_id: str) -> str:
    return f"webhook:{trigger['triggerId']}:{source}:{event_id}"


def verify_workflow_trigger_inbox_envelope_signature(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    envelope: WebhookRawRequestEnvelope,
    *,
    secret_provider: SecretProvider | None = None,
) -> dict[str, Any] | None:
    trigger = require_workflow_trigger(cfg, trigger_id)
    source_type = str(trigger.get("sourceType") or "")
    if source_type != "webhook":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {source_type}")
    return _signature_metadata_for_trigger(
        cfg,
        trigger,
        raw_envelope=envelope,
        secret_provider=secret_provider,
    )


def _record_inbox_event(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerInboxEventRequest,
    source: str,
    event_id: str,
    signature_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return record_workflow_trigger_inbox_event(
        cfg,
        trigger=trigger,
        source=source,
        event_type=str(request.eventType or "webhook"),
        provider_event_id=event_id,
        correlation_id=str(request.correlationId or "").strip(),
        cursor=str(request.cursor or "").strip(),
        dedupe_key=_inbox_dedupe_key(trigger, source=source, event_id=event_id),
        payload=request_payload(request),
        signature_metadata=signature_metadata,
    )


def _signature_metadata_for_trigger(
    cfg: RemoteRunnerConfig,
    trigger: dict[str, Any],
    *,
    raw_envelope: WebhookRawRequestEnvelope | None,
    secret_provider: SecretProvider | None,
) -> dict[str, Any] | None:
    base_metadata = _signature_metadata_from_envelope(raw_envelope)
    try:
        policy = resolve_webhook_trigger_signature_policy(trigger.get("triggerSpec") or {})
    except WebhookTriggerSignaturePolicyError as exc:
        _reject_signature(
            cfg,
            trigger,
            exc.code,
            verification_state=exc.policy_state,
            base_metadata=base_metadata,
            policy_state=exc.policy_state,
        )
    if policy.mode != "required":
        return base_metadata
    if raw_envelope is None:
        _reject_signature(
            cfg,
            trigger,
            "WORKFLOW_TRIGGER_SIGNATURE_RAW_ENVELOPE_REQUIRED",
            verification_state="missing",
            base_metadata=base_metadata,
            policy=policy,
        )
    provider = secret_provider or default_webhook_secret_provider()
    try:
        secret = resolve_secret_ref(provider, policy.secret_ref, purpose="webhook-signing-secret")
        result = verify_webhook_signature(
            webhook_verification_input_from_envelope(raw_envelope, policy=policy, secret=secret)
        )
    except SecretProviderError as exc:
        _reject_signature(
            cfg,
            trigger,
            "WORKFLOW_TRIGGER_SIGNATURE_SECRET_RESOLUTION_FAILED",
            verification_state=_secret_error_verification_state(exc),
            base_metadata=base_metadata,
            policy=policy,
        )
    except WebhookSignatureVerificationError as exc:
        _reject_signature(
            cfg,
            trigger,
            exc.code,
            verification_state=exc.signature_state,
            base_metadata=base_metadata,
            policy=policy,
            verification_error=exc.safe_details,
        )
    metadata = dict(base_metadata or {})
    metadata["signatureState"] = "verified"
    metadata["signatureDetails"] = _signature_details(
        "verified",
        policy=policy,
        verification=_verification_details(result),
        credential_ref=secret.safe_details(),
    )
    return metadata


def _signature_metadata_from_envelope(envelope: WebhookRawRequestEnvelope | None) -> dict[str, Any] | None:
    if envelope is None:
        return None
    return {
        "rawBodySha256": envelope.body_sha256,
        "rawBodySizeBytes": envelope.body_size_bytes,
        "rawContentType": envelope.content_type or "",
        "rawHeaderNames": list(envelope.header_names),
        "receivedAt": envelope.received_at.isoformat(),
    }


def _reject_signature(
    cfg: RemoteRunnerConfig,
    trigger: dict[str, Any],
    code: str,
    *,
    verification_state: str,
    base_metadata: dict[str, Any] | None,
    policy: WebhookTriggerSignaturePolicy | None = None,
    policy_state: str | None = None,
    verification_error: dict[str, Any] | None = None,
) -> None:
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.dispatch",
        actor=str(cfg.api_token_actor or "remote-runner-api"),
        subject_kind="workflow_trigger_event",
        subject_id=_rejected_delivery_subject_id(trigger, base_metadata),
        decision="deny",
        reason_code=code,
        details=_signature_rejection_audit_details(
            trigger,
            verification_state=verification_state,
            base_metadata=base_metadata,
            policy=policy,
            policy_state=policy_state,
            verification_error=verification_error,
        ),
    )
    raise ValueError(code)


def _rejected_delivery_subject_id(trigger: dict[str, Any], base_metadata: dict[str, Any] | None) -> str:
    body_hash = str((base_metadata or {}).get("rawBodySha256") or "").strip()
    suffix = body_hash[:12] if body_hash else "missing-envelope"
    return f"rejected:{trigger['triggerId']}:{suffix}"


def _signature_rejection_audit_details(
    trigger: dict[str, Any],
    *,
    verification_state: str,
    base_metadata: dict[str, Any] | None,
    policy: WebhookTriggerSignaturePolicy | None,
    policy_state: str | None,
    verification_error: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(base_metadata or {})
    details: dict[str, Any] = {
        "schemaVersion": "workflow-trigger-signature-rejection-audit.v1",
        "triggerId": str(trigger["triggerId"]),
        "failureStage": "webhook_signature_verification",
        "signatureState": verification_state,
    }
    for source_key, target_key in (
        ("rawBodySha256", "bodySha256"),
        ("rawBodySizeBytes", "bodySizeBytes"),
        ("rawContentType", "contentType"),
        ("receivedAt", "receivedAt"),
    ):
        value = metadata.get(source_key)
        if value not in (None, "", []):
            details[target_key] = value
    if policy is not None:
        safe_policy = policy.safe_details()
        details["provider"] = safe_policy.get("provider")
        details["policyMode"] = safe_policy.get("mode")
        details["verificationProvider"] = safe_policy.get("verificationProvider")
        details["algorithm"] = safe_policy.get("algorithm")
        details["replayProtectionRequired"] = safe_policy.get("replayProtectionRequired")
    if policy_state:
        details["policyState"] = policy_state
    if verification_error:
        header = verification_error.get("header")
        if header:
            details["header"] = header
    return details


def _signature_details(
    signature_state: str,
    *,
    policy: WebhookTriggerSignaturePolicy | None = None,
    verification: dict[str, Any] | None = None,
    credential_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "signatureState": signature_state,
        **({"policy": policy.safe_details()} if policy else {}),
        **({"verification": verification} if verification else {}),
        **({"credentialRef": credential_ref} if credential_ref else {}),
    }


def _verification_details(result: WebhookSignatureVerificationResult) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "algorithm": result.algorithm,
        "signatureHeader": result.signature_header,
        "timestampHeader": result.timestamp_header,
        "timestamp": result.timestamp,
        "toleranceSeconds": result.tolerance_seconds,
        "signedPayloadSha256": result.signed_payload_sha256,
    }


def _secret_error_verification_state(exc: SecretProviderError) -> str:
    if exc.state in {"missing", "malformed", "unsupported"}:
        return exc.state
    return "missing"


def _mark_inbox_dispatch_dead_lettered(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    request: WorkflowTriggerInboxEventRequest,
    inbox: dict[str, Any],
    exc: Exception,
) -> None:
    event = find_workflow_trigger_inbox_trigger_event(cfg, trigger=trigger, request=request)
    error = {"errorType": exc.__class__.__name__, "message": str(exc)}
    if event is None:
        mark_workflow_trigger_inbox_dead_lettered(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            failure_code="WORKFLOW_TRIGGER_INBOX_DISPATCH_FAILED",
            error=error,
        )
        return
    mark_workflow_trigger_inbox_replay_failed(
        cfg,
        inbox_event_id=str(inbox["inboxEventId"]),
        trigger_event_id=str(event["triggerEventId"]),
        failure_code="WORKFLOW_TRIGGER_INBOX_DISPATCH_FAILED",
        error=error,
    )


def _enforce_payload_size(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > TRIGGER_EVENT_PAYLOAD_MAX_BYTES:
        raise ValueError("WORKFLOW_TRIGGER_EVENT_PAYLOAD_TOO_LARGE")


def _required_text(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    return text
