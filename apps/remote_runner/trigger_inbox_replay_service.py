from __future__ import annotations

from typing import Any

from .api_models import WorkflowTriggerInboxEventRequest, WorkflowTriggerInboxReplayRequest
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .trigger_inbox_storage import (
    fetch_workflow_trigger_inbox_event,
    fetch_workflow_trigger_inbox_payload,
    inbox_event_summary,
    mark_workflow_trigger_inbox_dispatching,
    mark_workflow_trigger_inbox_replay_failed,
    mark_workflow_trigger_inbox_submitted,
)
from .trigger_inbox_service import enforce_workflow_trigger_inbox_event_match, find_workflow_trigger_inbox_trigger_event
from .trigger_service import _dispatch_recorded_trigger_event
from .trigger_storage import require_workflow_trigger
from .webhook_signature_policy import (
    WebhookTriggerSignaturePolicy,
    resolve_webhook_trigger_signature_policy,
)


INBOX_REPLAY_CONFIRMATION = "replay-dead-lettered-inbox-event"


def replay_workflow_trigger_inbox_event_from_request(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
    inbox_event_id: str,
    request: WorkflowTriggerInboxReplayRequest,
) -> dict[str, Any]:
    if request.confirmation != INBOX_REPLAY_CONFIRMATION:
        raise ValueError("WORKFLOW_TRIGGER_INBOX_REPLAY_CONFIRMATION_REQUIRED")
    trigger = require_workflow_trigger(cfg, trigger_id)
    if str(trigger.get("sourceType") or "") != "webhook":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_SOURCE_MISMATCH: {trigger.get('sourceType')}")
    if not trigger.get("enabled"):
        raise ValueError("WORKFLOW_TRIGGER_DISABLED")
    inbox = fetch_workflow_trigger_inbox_event(cfg, inbox_event_id)
    if str(inbox.get("triggerId") or "") != str(trigger["triggerId"]):
        raise ValueError("WORKFLOW_TRIGGER_INBOX_TRIGGER_MISMATCH")
    if str(inbox.get("state") or "") != "dead_lettered":
        raise ValueError(f"WORKFLOW_TRIGGER_INBOX_REPLAY_STATE_UNSUPPORTED: {inbox.get('state') or 'unknown'}")
    actor = str(request.actor or "remote-runner-api").strip() or "remote-runner-api"
    reason = str(request.reason or "").strip()
    _enforce_replay_signature_policy(cfg, trigger=trigger, inbox=inbox, actor=actor, reason=reason)
    payload = fetch_workflow_trigger_inbox_payload(cfg, str(inbox["inboxEventId"]))
    inbox_request = WorkflowTriggerInboxEventRequest(**payload)
    enforce_workflow_trigger_inbox_event_match(cfg, trigger=trigger, request=inbox_request, actor=actor)
    event = find_workflow_trigger_inbox_trigger_event(cfg, trigger=trigger, request=inbox_request)
    if event is None:
        raise ValueError("WORKFLOW_TRIGGER_INBOX_REPLAY_EVENT_NOT_FOUND")
    mark_workflow_trigger_inbox_dispatching(cfg, inbox_event_id=str(inbox["inboxEventId"]))
    try:
        response = _dispatch_recorded_trigger_event(
            cfg,
            trigger_id=str(trigger["triggerId"]),
            trigger=trigger,
            event=event,
            source_type="webhook",
        )
        event = response["data"]["event"]
        run = response["data"]["run"]
        inbox = mark_workflow_trigger_inbox_submitted(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            trigger_event_id=str(event["triggerEventId"]),
            run_id=str(run["runId"]),
        )
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.inbox_replay",
            actor=actor,
            subject_kind="workflow_trigger_inbox_event",
            subject_id=str(inbox["inboxEventId"]),
            details={
                "triggerId": trigger["triggerId"],
                "triggerEventId": event["triggerEventId"],
                "runId": run["runId"],
                "reason": reason,
                "dispatchReplayed": bool(response["data"]["replayed"]),
            },
        )
        response["data"] = {
            "schemaVersion": "workflow-trigger-inbox-replay.v1",
            "inbox": inbox_event_summary(inbox),
            "event": event,
            "run": run,
            "replayed": bool(response["data"]["replayed"]),
        }
        return response
    except Exception as exc:
        mark_workflow_trigger_inbox_replay_failed(
            cfg,
            inbox_event_id=str(inbox["inboxEventId"]),
            trigger_event_id=str(event["triggerEventId"]),
            failure_code="WORKFLOW_TRIGGER_INBOX_REPLAY_FAILED",
            error={"errorType": exc.__class__.__name__, "message": str(exc)},
        )
        record_governance_audit_event(
            cfg,
            action="workflow_trigger.inbox_replay",
            actor=actor,
            subject_kind="workflow_trigger_inbox_event",
            subject_id=str(inbox["inboxEventId"]),
            decision="error",
            reason_code="WORKFLOW_TRIGGER_INBOX_REPLAY_FAILED",
            details={
                "triggerId": trigger["triggerId"],
                "triggerEventId": event["triggerEventId"],
                "reason": reason,
                "errorType": exc.__class__.__name__,
            },
        )
        raise


def _enforce_replay_signature_policy(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    inbox: dict[str, Any],
    actor: str,
    reason: str,
) -> None:
    policy = resolve_webhook_trigger_signature_policy(trigger.get("triggerSpec") or {})
    if policy.mode != "required":
        return
    signature_state = str(inbox.get("signatureState") or "unsupported")
    if signature_state == "verified":
        return
    _record_signature_replay_deny(
        cfg,
        trigger=trigger,
        inbox=inbox,
        actor=actor,
        reason=reason,
        policy=policy,
        signature_state=signature_state,
    )
    raise ValueError("WORKFLOW_TRIGGER_INBOX_REPLAY_SIGNATURE_NOT_VERIFIED")


def _record_signature_replay_deny(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    inbox: dict[str, Any],
    actor: str,
    reason: str,
    policy: WebhookTriggerSignaturePolicy,
    signature_state: str,
) -> None:
    safe_policy = policy.safe_details()
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.inbox_replay",
        actor=actor,
        subject_kind="workflow_trigger_inbox_event",
        subject_id=str(inbox["inboxEventId"]),
        decision="deny",
        reason_code="WORKFLOW_TRIGGER_INBOX_REPLAY_SIGNATURE_NOT_VERIFIED",
        details={
            "triggerId": trigger["triggerId"],
            "reason": reason,
            "failureStage": "webhook_signature_replay_preflight",
            "signatureState": signature_state,
            "policyMode": safe_policy["mode"],
            "provider": safe_policy["provider"],
            "verificationProvider": safe_policy["verificationProvider"],
            "algorithm": safe_policy["algorithm"],
            "rawBodyRequired": safe_policy["rawBodyRequired"],
        },
    )
