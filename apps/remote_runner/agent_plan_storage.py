"""Immutable Agent plan revisions and durable human approvals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from core.contracts.agent_plan import (
    AGENT_APPROVAL_CONTRACT_VERSION,
    AGENT_PLAN_REVISION_CONTRACT_VERSION,
    AgentApprovalRecord,
    AgentPlanRevisionRecord,
)
from core.contracts.agent_session import (
    AgentPlanProposal,
    AgentSessionBudget,
    assert_agent_session_json_safe,
)
from core.contracts.workflow_design import normalize_workflow_design_draft

from .config import RemoteRunnerConfig
from .agent_session_storage import append_agent_event_record
from .errors import RemoteRunnerNotFoundError, WorkflowDesignRevisionConflictError
from .storage_core import get_connection, now_iso


class AgentPlanStorageConflictError(WorkflowDesignRevisionConflictError):
    pass


class AgentPlanStorageNotFoundError(RemoteRunnerNotFoundError):
    pass


def create_agent_plan_revision(
    cfg: RemoteRunnerConfig,
    *,
    session_id: str,
    plan_generation: int,
    draft_id: str,
    draft_revision: int,
    proposal: dict[str, Any],
    validation: dict[str, Any],
    budget: dict[str, Any],
    created_by: str,
    parent_plan_revision_id: str | None = None,
) -> dict[str, Any]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    normalized_generation = _positive_int(plan_generation, "AGENT_PLAN_GENERATION_INVALID")
    normalized_draft_id = _required_text(draft_id, "AGENT_PLAN_DRAFT_ID_REQUIRED")
    normalized_draft_revision = _positive_int(draft_revision, "AGENT_PLAN_DRAFT_REVISION_INVALID")
    normalized_created_by = _required_text(created_by, "AGENT_PLAN_CREATED_BY_REQUIRED")
    normalized_parent_id = _optional_text(parent_plan_revision_id)
    normalized_proposal = AgentPlanProposal.model_validate(proposal).runtime_payload()
    normalized_proposal["draft"] = normalize_workflow_design_draft(normalized_proposal["draft"])
    normalized_validation = _safe_json_object(validation, "AGENT_PLAN_VALIDATION_OBJECT_REQUIRED")
    normalized_budget = AgentSessionBudget.model_validate(budget).runtime_payload()
    plan_payload = {
        "budget": normalized_budget,
        "contractVersion": AGENT_PLAN_REVISION_CONTRACT_VERSION,
        "draftId": normalized_draft_id,
        "draftRevision": normalized_draft_revision,
        "parentPlanRevisionId": normalized_parent_id,
        "planGeneration": normalized_generation,
        "proposal": normalized_proposal,
        "sessionId": normalized_session_id,
        "validation": normalized_validation,
    }
    plan_hash = _hash_json(plan_payload)
    plan_revision_id = f"agpr_{uuid.uuid4().hex[:16]}"
    created_at = now_iso()

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM agent_plan_revisions
                WHERE session_id = ? AND plan_generation = ?
                """,
                (normalized_session_id, normalized_generation),
            ).fetchone()
            if existing is not None:
                if str(existing["plan_hash"]) != plan_hash:
                    raise AgentPlanStorageConflictError("AGENT_PLAN_GENERATION_ALREADY_COMMITTED")
                connection.commit()
                return _plan_row_to_dict(existing)
            session = _require_row(
                connection,
                "SELECT * FROM agent_sessions WHERE session_id = ?",
                (normalized_session_id,),
                "AGENT_SESSION_NOT_FOUND",
            )
            if str(session["status"]) != "planning":
                raise AgentPlanStorageConflictError(
                    f"AGENT_PLAN_SESSION_STATUS_INVALID: {session['status']}"
                )
            if int(session["plan_generation"]) != normalized_generation:
                raise AgentPlanStorageConflictError("AGENT_PLAN_GENERATION_CONFLICT")
            if json.loads(session["budget_json"]) != normalized_budget:
                raise AgentPlanStorageConflictError("AGENT_PLAN_BUDGET_CONFLICT")
            _validate_tool_constraints(session, normalized_proposal)
            _validate_parent(
                connection,
                session_id=normalized_session_id,
                plan_generation=normalized_generation,
                parent_plan_revision_id=normalized_parent_id,
            )
            _validate_draft_snapshot(
                connection,
                session=session,
                draft_id=normalized_draft_id,
                draft_revision=normalized_draft_revision,
                proposal=normalized_proposal,
            )
            connection.execute(
                """
                INSERT INTO agent_plan_revisions (
                    plan_revision_id, contract_version, session_id, plan_generation,
                    parent_plan_revision_id, draft_id, draft_revision, plan_hash,
                    proposal_json, validation_json, budget_json, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_revision_id,
                    AGENT_PLAN_REVISION_CONTRACT_VERSION,
                    normalized_session_id,
                    normalized_generation,
                    normalized_parent_id,
                    normalized_draft_id,
                    normalized_draft_revision,
                    plan_hash,
                    _stable_json(normalized_proposal),
                    _stable_json(normalized_validation),
                    _stable_json(normalized_budget),
                    normalized_created_by,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_plan_revisions WHERE plan_revision_id = ?",
                (plan_revision_id,),
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _plan_row_to_dict(row)


def fetch_agent_plan_revision(
    cfg: RemoteRunnerConfig,
    plan_revision_id: str,
) -> dict[str, Any] | None:
    normalized_id = _required_text(plan_revision_id, "AGENT_PLAN_REVISION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM agent_plan_revisions WHERE plan_revision_id = ?",
            (normalized_id,),
        ).fetchone()
    return _plan_row_to_dict(row) if row is not None else None


def require_agent_plan_revision(cfg: RemoteRunnerConfig, plan_revision_id: str) -> dict[str, Any]:
    plan = fetch_agent_plan_revision(cfg, plan_revision_id)
    if plan is None:
        raise AgentPlanStorageNotFoundError("AGENT_PLAN_REVISION_NOT_FOUND")
    return plan


def list_agent_plan_revisions(cfg: RemoteRunnerConfig, session_id: str) -> list[dict[str, Any]]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM agent_plan_revisions
            WHERE session_id = ?
            ORDER BY plan_generation ASC
            """,
            (normalized_session_id,),
        ).fetchall()
    return [_plan_row_to_dict(row) for row in rows]


def record_agent_approval(
    cfg: RemoteRunnerConfig,
    *,
    session_id: str,
    plan_revision_id: str,
    expected_state_version: int,
    expected_plan_hash: str,
    decision: str,
    actor: str,
    request_id: str,
    idempotency_key: str,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    normalized_plan_revision_id = _required_text(plan_revision_id, "AGENT_PLAN_REVISION_ID_REQUIRED")
    normalized_expected_version = _positive_int(
        expected_state_version,
        "AGENT_APPROVAL_EXPECTED_STATE_VERSION_INVALID",
    )
    normalized_plan_hash = _required_text(expected_plan_hash, "AGENT_APPROVAL_PLAN_HASH_REQUIRED")
    normalized_decision = _required_text(decision, "AGENT_APPROVAL_DECISION_REQUIRED")
    normalized_actor = _required_text(actor, "AGENT_APPROVAL_ACTOR_REQUIRED")
    normalized_request_id = _required_text(request_id, "AGENT_APPROVAL_REQUEST_ID_REQUIRED")
    normalized_idempotency = _required_text(idempotency_key, "AGENT_APPROVAL_IDEMPOTENCY_KEY_REQUIRED")
    normalized_reason = _optional_text(reason)
    approval_payload = {
        "actor": normalized_actor,
        "decision": normalized_decision,
        "expectedStateVersion": normalized_expected_version,
        "idempotencyKey": normalized_idempotency,
        "planHash": normalized_plan_hash,
        "planRevisionId": normalized_plan_revision_id,
        "reason": normalized_reason,
        "requestId": normalized_request_id,
        "scope": "compile_workflow_revision",
        "sessionId": normalized_session_id,
    }
    approval_hash = _hash_json(approval_payload)
    approval_id = f"agap_{uuid.uuid4().hex[:16]}"
    created_at = now_iso()

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT * FROM agent_approvals
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (normalized_session_id, normalized_idempotency),
            ).fetchone()
            if replay is not None:
                if str(replay["approval_hash"]) != approval_hash:
                    raise AgentPlanStorageConflictError("AGENT_APPROVAL_IDEMPOTENCY_CONFLICT")
                connection.commit()
                return _approval_row_to_dict(replay)
            event_collision = connection.execute(
                """
                SELECT event_id FROM agent_events
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (normalized_session_id, normalized_idempotency),
            ).fetchone()
            if event_collision is not None:
                raise AgentPlanStorageConflictError("AGENT_APPROVAL_IDEMPOTENCY_CONFLICT")
            session = _require_row(
                connection,
                "SELECT * FROM agent_sessions WHERE session_id = ?",
                (normalized_session_id,),
                "AGENT_SESSION_NOT_FOUND",
            )
            plan = _require_row(
                connection,
                "SELECT * FROM agent_plan_revisions WHERE plan_revision_id = ?",
                (normalized_plan_revision_id,),
                "AGENT_PLAN_REVISION_NOT_FOUND",
            )
            _validate_approval_target(
                connection=connection,
                session=session,
                plan=plan,
                expected_state_version=normalized_expected_version,
                expected_plan_hash=normalized_plan_hash,
            )
            effective_decision = connection.execute(
                """
                SELECT approval_id FROM agent_approvals
                WHERE session_id = ? AND plan_generation = ?
                    AND expected_state_version = ?
                """,
                (
                    normalized_session_id,
                    int(plan["plan_generation"]),
                    normalized_expected_version,
                ),
            ).fetchone()
            if effective_decision is not None:
                raise AgentPlanStorageConflictError(
                    "AGENT_APPROVAL_EFFECTIVE_DECISION_ALREADY_RECORDED"
                )
            candidate = {
                "contractVersion": AGENT_APPROVAL_CONTRACT_VERSION,
                "approvalId": approval_id,
                "sessionId": normalized_session_id,
                "planRevisionId": normalized_plan_revision_id,
                "planGeneration": int(plan["plan_generation"]),
                "planHash": normalized_plan_hash,
                "expectedStateVersion": normalized_expected_version,
                "decision": normalized_decision,
                "scope": "compile_workflow_revision",
                "actor": normalized_actor,
                "reason": normalized_reason,
                "requestId": normalized_request_id,
                "idempotencyKey": normalized_idempotency,
                "createdAt": created_at,
            }
            AgentApprovalRecord.model_validate(candidate)
            connection.execute(
                """
                INSERT INTO agent_approvals (
                    approval_id, contract_version, session_id, plan_revision_id,
                    plan_generation, plan_hash, expected_state_version, decision,
                    scope, actor, reason, request_id, idempotency_key,
                    approval_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    AGENT_APPROVAL_CONTRACT_VERSION,
                    normalized_session_id,
                    normalized_plan_revision_id,
                    int(plan["plan_generation"]),
                    normalized_plan_hash,
                    normalized_expected_version,
                    normalized_decision,
                    "compile_workflow_revision",
                    normalized_actor,
                    normalized_reason,
                    normalized_request_id,
                    normalized_idempotency,
                    approval_hash,
                    created_at,
                ),
            )
            if normalized_decision == "approve":
                append_agent_event_record(
                    connection,
                    session_id=normalized_session_id,
                    event_type="agent.approval_granted",
                    from_status="awaiting_approval",
                    to_status="awaiting_approval",
                    state_version=normalized_expected_version,
                    plan_generation=int(plan["plan_generation"]),
                    actor=normalized_actor,
                    request_id=normalized_request_id,
                    idempotency_key=normalized_idempotency,
                    command_hash=approval_hash,
                    payload={
                        "approvalId": approval_id,
                        "decision": normalized_decision,
                        "planHash": normalized_plan_hash,
                        "planRevisionId": normalized_plan_revision_id,
                        "scope": "compile_workflow_revision",
                    },
                    created_at=created_at,
                )
            row = connection.execute(
                "SELECT * FROM agent_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _approval_row_to_dict(row)


def list_agent_approvals(cfg: RemoteRunnerConfig, session_id: str) -> list[dict[str, Any]]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM agent_approvals
            WHERE session_id = ?
            ORDER BY created_at ASC, approval_id ASC
            """,
            (normalized_session_id,),
        ).fetchall()
    return [_approval_row_to_dict(row) for row in rows]


def _validate_parent(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    plan_generation: int,
    parent_plan_revision_id: str | None,
) -> None:
    if plan_generation == 1:
        if parent_plan_revision_id is not None:
            raise AgentPlanStorageConflictError("AGENT_PLAN_PARENT_REVISION_UNEXPECTED")
        return
    if parent_plan_revision_id is None:
        previous = connection.execute(
            """
            SELECT plan_revision_id FROM agent_plan_revisions
            WHERE session_id = ? AND plan_generation < ?
            ORDER BY plan_generation DESC LIMIT 1
            """,
            (session_id, plan_generation),
        ).fetchone()
        if previous is not None:
            raise AgentPlanStorageConflictError("AGENT_PLAN_PARENT_REVISION_REQUIRED")
        return
    parent = _require_row(
        connection,
        "SELECT * FROM agent_plan_revisions WHERE plan_revision_id = ?",
        (parent_plan_revision_id,),
        "AGENT_PLAN_PARENT_REVISION_NOT_FOUND",
    )
    if str(parent["session_id"]) != session_id or int(parent["plan_generation"]) != plan_generation - 1:
        raise AgentPlanStorageConflictError("AGENT_PLAN_PARENT_REVISION_CONFLICT")


def _validate_tool_constraints(
    session: sqlite3.Row,
    proposal: dict[str, Any],
) -> None:
    constraints = json.loads(session["constraints_json"])
    allowed = {
        str(item)
        for item in constraints.get("allowedToolRevisionIds", [])
        if str(item).strip()
    }
    if not allowed:
        return
    for node in proposal["draft"].get("nodes", []):
        tool_revision_id = str(node.get("toolRevisionId") or "")
        if tool_revision_id not in allowed:
            raise AgentPlanStorageConflictError(
                f"AGENT_PLAN_TOOL_REVISION_NOT_ALLOWED: {tool_revision_id}"
            )


def _validate_draft_snapshot(
    connection: sqlite3.Connection,
    *,
    session: sqlite3.Row,
    draft_id: str,
    draft_revision: int,
    proposal: dict[str, Any],
) -> None:
    draft = _require_row(
        connection,
        "SELECT * FROM workflow_design_drafts WHERE draft_id = ?",
        (draft_id,),
        "AGENT_PLAN_DRAFT_NOT_FOUND",
    )
    if int(draft["revision"]) != draft_revision:
        raise AgentPlanStorageConflictError("AGENT_PLAN_DRAFT_REVISION_CONFLICT")
    if str(draft["project_id"]) != str(session["project_id"]):
        raise AgentPlanStorageConflictError("AGENT_PLAN_DRAFT_PROJECT_CONFLICT")
    if json.loads(draft["draft_json"]) != proposal["draft"]:
        raise AgentPlanStorageConflictError("AGENT_PLAN_DRAFT_SNAPSHOT_CONFLICT")


def _validate_approval_target(
    *,
    connection: sqlite3.Connection,
    session: sqlite3.Row,
    plan: sqlite3.Row,
    expected_state_version: int,
    expected_plan_hash: str,
) -> None:
    if str(session["status"]) != "awaiting_approval":
        raise AgentPlanStorageConflictError(f"AGENT_APPROVAL_SESSION_STATUS_INVALID: {session['status']}")
    if int(session["state_version"]) != expected_state_version:
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_STATE_VERSION_CONFLICT")
    if str(session["session_id"]) != str(plan["session_id"]):
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_PLAN_SESSION_CONFLICT")
    if int(session["plan_generation"]) != int(plan["plan_generation"]):
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_PLAN_GENERATION_CONFLICT")
    if str(session["active_plan_hash"] or "") != expected_plan_hash:
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_ACTIVE_PLAN_HASH_CONFLICT")
    if str(plan["plan_hash"]) != expected_plan_hash:
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_PLAN_HASH_CONFLICT")
    if str(session["active_draft_id"] or "") != str(plan["draft_id"]):
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_DRAFT_CONFLICT")
    if int(session["active_draft_revision"] or 0) != int(plan["draft_revision"]):
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_DRAFT_REVISION_CONFLICT")
    live_draft = connection.execute(
        "SELECT revision, draft_json FROM workflow_design_drafts WHERE draft_id = ?",
        (str(plan["draft_id"]),),
    ).fetchone()
    if live_draft is None:
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_DRAFT_NOT_FOUND")
    proposal = json.loads(plan["proposal_json"])
    if int(live_draft["revision"]) != int(plan["draft_revision"]):
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_DRAFT_REVISION_CONFLICT")
    if json.loads(live_draft["draft_json"]) != proposal["draft"]:
        raise AgentPlanStorageConflictError("AGENT_APPROVAL_DRAFT_SNAPSHOT_CONFLICT")


def _plan_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "contractVersion": row["contract_version"],
        "planRevisionId": row["plan_revision_id"],
        "sessionId": row["session_id"],
        "planGeneration": int(row["plan_generation"]),
        "parentPlanRevisionId": row["parent_plan_revision_id"],
        "draftId": row["draft_id"],
        "draftRevision": int(row["draft_revision"]),
        "planHash": row["plan_hash"],
        "proposal": json.loads(row["proposal_json"]),
        "validation": json.loads(row["validation_json"]),
        "budget": json.loads(row["budget_json"]),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
    }
    AgentPlanRevisionRecord.model_validate(payload)
    hash_payload = {
        "budget": payload["budget"],
        "contractVersion": payload["contractVersion"],
        "draftId": payload["draftId"],
        "draftRevision": payload["draftRevision"],
        "parentPlanRevisionId": payload["parentPlanRevisionId"],
        "planGeneration": payload["planGeneration"],
        "proposal": payload["proposal"],
        "sessionId": payload["sessionId"],
        "validation": payload["validation"],
    }
    canonical_payload = _stable_json(hash_payload)
    if hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest() != payload["planHash"]:
        raise AgentPlanStorageConflictError("AGENT_PLAN_STORED_HASH_MISMATCH")
    payload["canonicalPayload"] = canonical_payload
    return payload


def _approval_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "contractVersion": row["contract_version"],
        "approvalId": row["approval_id"],
        "sessionId": row["session_id"],
        "planRevisionId": row["plan_revision_id"],
        "planGeneration": int(row["plan_generation"]),
        "planHash": row["plan_hash"],
        "expectedStateVersion": int(row["expected_state_version"]),
        "decision": row["decision"],
        "scope": row["scope"],
        "actor": row["actor"],
        "reason": row["reason"],
        "requestId": row["request_id"],
        "idempotencyKey": row["idempotency_key"],
        "createdAt": row["created_at"],
    }
    AgentApprovalRecord.model_validate(payload)
    return payload


def _require_row(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[Any, ...],
    code: str,
) -> sqlite3.Row:
    row = connection.execute(sql, parameters).fetchone()
    if row is None:
        raise AgentPlanStorageNotFoundError(code)
    return row


def _safe_json_object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(code)
    assert_agent_session_json_safe(value, path="agent.plan")
    return json.loads(_stable_json(value))


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _positive_int(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(code)
    return value


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
