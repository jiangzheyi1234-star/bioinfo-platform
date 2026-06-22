from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event, list_evidence_events
from .storage_core import get_connection


GOVERNANCE_AUDIT_EVENT_TYPE = "governance.operator_action.v1"
GOVERNANCE_AUDIT_SCHEMA_NAME = "GovernanceAuditEvent"
_FORBIDDEN_DETAIL_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "key",
    "password",
    "private",
    "secret",
    "token",
)
_ALLOWED_DECISIONS = {"allow", "deny", "error"}


def record_governance_audit_event(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    subject_kind: str,
    subject_id: str,
    actor: str = "remote-runner-api",
    decision: str = "allow",
    reason_code: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_details = _safe_details(details or {})
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in _ALLOWED_DECISIONS:
        raise ValueError("GOVERNANCE_AUDIT_DECISION_INVALID")
    payload = {
        "action": _required_text(action, "GOVERNANCE_AUDIT_ACTION_REQUIRED"),
        "actor": _required_text(actor, "GOVERNANCE_AUDIT_ACTOR_REQUIRED"),
        "decision": normalized_decision,
        "reasonCode": str(reason_code or "").strip(),
        "subjectKind": _required_text(
            subject_kind,
            "GOVERNANCE_AUDIT_SUBJECT_KIND_REQUIRED",
        ),
        "subjectId": _required_text(subject_id, "GOVERNANCE_AUDIT_SUBJECT_ID_REQUIRED"),
        "details": normalized_details,
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
            schema_name=GOVERNANCE_AUDIT_SCHEMA_NAME,
            subject_kind=payload["subjectKind"],
            subject_id=payload["subjectId"],
            payload=payload,
        )
        connection.commit()
    return _audit_event_from_evidence(event)


def list_governance_audit_events(
    cfg: RemoteRunnerConfig,
    *,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    requested_limit = min(500, max(1, int(limit)))
    requested_action = _optional_text(action)
    events = list_evidence_events(
        cfg,
        subject_kind=_optional_text(subject_kind),
        subject_id=_optional_text(subject_id),
        event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
        limit=500 if requested_action else requested_limit,
    )
    items = [_audit_event_from_evidence(event) for event in events]
    if requested_action:
        items = [item for item in items if item["action"] == requested_action]
    return {"items": items[:requested_limit]}


def _audit_event_from_evidence(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    return {
        "eventId": event["eventId"],
        "seq": event["seq"],
        "eventType": event["eventType"],
        "schema": event["schema"],
        "subjectKind": event["subjectKind"],
        "subjectId": event["subjectId"],
        "producer": event["producer"],
        "action": str(payload.get("action") or ""),
        "actor": str(payload.get("actor") or ""),
        "decision": str(payload.get("decision") or ""),
        "reasonCode": str(payload.get("reasonCode") or ""),
        "details": dict(details),
        "payloadHash": event["payloadHash"],
        "eventHash": event["eventHash"],
        "prevEventHash": event["prevEventHash"],
        "occurredAt": event["occurredAt"],
    }


def _safe_details(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("GOVERNANCE_AUDIT_DETAILS_MUST_BE_OBJECT")
    _reject_secret_detail_keys(value)
    return dict(value)


def _reject_secret_detail_keys(value: Any, *, path: str = "details") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key or "").lower().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_DETAIL_KEY_PARTS):
                raise ValueError(f"GOVERNANCE_AUDIT_SECRET_FIELD_FORBIDDEN: {path}.{key}")
            _reject_secret_detail_keys(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_detail_keys(item, path=f"{path}[{index}]")


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
