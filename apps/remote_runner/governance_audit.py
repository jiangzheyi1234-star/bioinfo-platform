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
_CONTEXT_FIELDS = ("requestId", "correlationId", "projectId", "tenantId")


def record_governance_audit_event(
    cfg: RemoteRunnerConfig,
    *,
    action: str,
    subject_kind: str,
    subject_id: str,
    actor: str = "remote-runner-api",
    decision: str = "allow",
    reason_code: str = "",
    request_id: str = "",
    correlation_id: str = "",
    project_id: str = "",
    tenant_id: str = "",
    actor_roles: tuple[str, ...] | list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    roles = _audit_roles(actor_roles if actor_roles is not None else cfg.api_token_roles)
    with get_connection(cfg) as connection:
        event = append_governance_audit_event(
            connection,
            action=action,
            subject_kind=subject_kind,
            subject_id=subject_id,
            actor=actor,
            decision=decision,
            reason_code=reason_code,
            request_id=request_id,
            correlation_id=correlation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            actor_roles=roles,
            details=details,
        )
        connection.commit()
    return event


def append_governance_audit_event(
    connection,
    *,
    action: str,
    subject_kind: str,
    subject_id: str,
    actor: str = "remote-runner-api",
    decision: str = "allow",
    reason_code: str = "",
    request_id: str = "",
    correlation_id: str = "",
    project_id: str = "",
    tenant_id: str = "",
    actor_roles: tuple[str, ...] | list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_details = _safe_details(details or {})
    context = _audit_context(
        normalized_details,
        request_id=request_id,
        correlation_id=correlation_id,
        project_id=project_id,
        tenant_id=tenant_id,
    )
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in _ALLOWED_DECISIONS:
        raise ValueError("GOVERNANCE_AUDIT_DECISION_INVALID")
    payload = {
        "action": _required_text(action, "GOVERNANCE_AUDIT_ACTION_REQUIRED"),
        "actor": _required_text(actor, "GOVERNANCE_AUDIT_ACTOR_REQUIRED"),
        "decision": normalized_decision,
        "reasonCode": str(reason_code or "").strip(),
        "requestId": context["requestId"],
        "correlationId": context["correlationId"],
        "projectId": context["projectId"],
        "tenantId": context["tenantId"],
        "actorRoles": _audit_roles(actor_roles),
        "subjectKind": _required_text(
            subject_kind,
            "GOVERNANCE_AUDIT_SUBJECT_KIND_REQUIRED",
        ),
        "subjectId": _required_text(subject_id, "GOVERNANCE_AUDIT_SUBJECT_ID_REQUIRED"),
        "details": normalized_details,
    }
    event = append_evidence_event(
        connection,
        event_type=GOVERNANCE_AUDIT_EVENT_TYPE,
        schema_name=GOVERNANCE_AUDIT_SCHEMA_NAME,
        subject_kind=payload["subjectKind"],
        subject_id=payload["subjectId"],
        payload=payload,
    )
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
        "requestId": str(payload.get("requestId") or ""),
        "correlationId": str(payload.get("correlationId") or ""),
        "projectId": str(payload.get("projectId") or ""),
        "tenantId": str(payload.get("tenantId") or ""),
        "actorRoles": _audit_roles(payload.get("actorRoles") if isinstance(payload.get("actorRoles"), list) else ()),
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


def _audit_context(
    details: dict[str, Any],
    *,
    request_id: str = "",
    correlation_id: str = "",
    project_id: str = "",
    tenant_id: str = "",
) -> dict[str, str]:
    explicit = {
        "requestId": request_id,
        "correlationId": correlation_id,
        "projectId": project_id,
        "tenantId": tenant_id,
    }
    context = {key: _optional_text(explicit[key]) or _context_value(details, key) or "" for key in _CONTEXT_FIELDS}
    return context


def _context_value(details: dict[str, Any], key: str) -> str:
    direct = _context_text(details.get(key))
    if direct:
        return direct
    if key != "correlationId":
        return ""
    event_context = details.get("eventContext") if isinstance(details.get("eventContext"), dict) else {}
    return _context_text(event_context.get(key)) or ""


def _context_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return _optional_text(value) or ""


def _audit_roles(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    roles: list[str] = []
    for item in value:
        role = str(item or "").strip()
        if role and role not in roles:
            roles.append(role)
    return sorted(roles)


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
