"""Durable AgentSession projection and append-only event ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from core.contracts.agent_session import (
    AGENT_SESSION_CONTRACT_VERSION,
    AGENT_SESSION_EVENT_CONTRACT_VERSION,
    AgentSessionBudget,
    AgentSessionConstraints,
    AgentSessionEvent,
    AgentSessionGoal,
    AgentSessionRecord,
    assert_agent_session_json_safe,
)

from .agent_session_schema import AGENT_SESSION_STATUSES
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError, WorkflowDesignRevisionConflictError
from .storage_core import get_connection, now_iso


_UNSET = object()


class AgentSessionStorageConflictError(WorkflowDesignRevisionConflictError):
    pass


class AgentSessionStorageNotFoundError(RemoteRunnerNotFoundError):
    pass


def create_agent_session(
    cfg: RemoteRunnerConfig,
    *,
    project_id: str,
    goal: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    budget: dict[str, Any],
    creation_request_id: str,
    created_by: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    normalized_project_id = _required_text(project_id, "AGENT_PROJECT_ID_REQUIRED")
    normalized_request_id = _required_text(creation_request_id, "AGENT_CREATION_REQUEST_ID_REQUIRED")
    normalized_created_by = _required_text(created_by, "AGENT_CREATED_BY_REQUIRED")
    normalized_goal = AgentSessionGoal.model_validate(goal).runtime_payload()
    normalized_constraints = AgentSessionConstraints.model_validate(constraints or {}).runtime_payload()
    normalized_budget = AgentSessionBudget.model_validate(budget).runtime_payload()
    request_payload = {
        "budget": normalized_budget,
        "contractVersion": AGENT_SESSION_CONTRACT_VERSION,
        "constraints": normalized_constraints,
        "createdBy": normalized_created_by,
        "goal": normalized_goal,
        "projectId": normalized_project_id,
    }
    creation_hash = _hash_json(request_payload)
    normalized_session_id = _optional_text(session_id) or f"ags_{uuid.uuid4().hex[:16]}"
    created_at = now_iso()

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM agent_sessions WHERE creation_request_id = ?",
                (normalized_request_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["creation_request_hash"]) != creation_hash:
                    raise AgentSessionStorageConflictError("AGENT_SESSION_CREATION_REQUEST_CONFLICT")
                connection.commit()
                return _session_row_to_dict(existing)
            connection.execute(
                """
                INSERT INTO agent_sessions (
                    session_id, contract_version, project_id, goal_json, constraints_json, budget_json,
                    status, state_version, plan_generation, creation_request_id,
                    creation_request_hash, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'created', 1, 0, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_session_id,
                    AGENT_SESSION_CONTRACT_VERSION,
                    normalized_project_id,
                    _stable_json(normalized_goal),
                    _stable_json(normalized_constraints),
                    _stable_json(normalized_budget),
                    normalized_request_id,
                    creation_hash,
                    normalized_created_by,
                    created_at,
                    created_at,
                ),
            )
            append_agent_event_record(
                connection,
                session_id=normalized_session_id,
                event_type="agent.session_created",
                from_status=None,
                to_status="created",
                state_version=1,
                plan_generation=0,
                actor=normalized_created_by,
                request_id=normalized_request_id,
                idempotency_key=f"create:{normalized_request_id}",
                command_hash=creation_hash,
                payload=request_payload,
                created_at=created_at,
            )
            row = _fetch_session_row(connection, normalized_session_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return _session_row_to_dict(row)


def fetch_agent_session(cfg: RemoteRunnerConfig, session_id: str) -> dict[str, Any] | None:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?",
            (normalized_session_id,),
        ).fetchone()
    return _session_row_to_dict(row) if row is not None else None


def require_agent_session(cfg: RemoteRunnerConfig, session_id: str) -> dict[str, Any]:
    session = fetch_agent_session(cfg, session_id)
    if session is None:
        raise AgentSessionStorageNotFoundError("AGENT_SESSION_NOT_FOUND")
    return session


def list_agent_sessions(
    cfg: RemoteRunnerConfig,
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    normalized_limit = max(1, min(int(limit), 500))
    normalized_project_id = _optional_text(project_id)
    with get_connection(cfg) as connection:
        if normalized_project_id:
            rows = connection.execute(
                """
                SELECT * FROM agent_sessions
                WHERE project_id = ?
                ORDER BY updated_at DESC, session_id ASC
                LIMIT ?
                """,
                (normalized_project_id, normalized_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM agent_sessions
                ORDER BY updated_at DESC, session_id ASC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
    return [_session_row_to_dict(row) for row in rows]


def transition_agent_session(
    cfg: RemoteRunnerConfig,
    session_id: str,
    *,
    expected_state_version: int,
    event_type: str,
    to_status: str,
    request_id: str,
    actor: str,
    idempotency_key: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    expected_plan_hash: str | None = None,
    expected_plan_generation: int | None = None,
    plan_generation: int | object = _UNSET,
    active_draft_id: str | None | object = _UNSET,
    active_draft_revision: int | None | object = _UNSET,
    active_plan_hash: str | None | object = _UNSET,
    workflow_revision_id: str | None | object = _UNSET,
    planner: dict[str, Any] | object = _UNSET,
    last_error_code: str | object = _UNSET,
) -> dict[str, Any]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    normalized_event_type = _required_text(event_type, "AGENT_EVENT_TYPE_REQUIRED")
    normalized_to_status = _required_text(to_status, "AGENT_STATUS_REQUIRED")
    if normalized_to_status not in AGENT_SESSION_STATUSES:
        raise ValueError(f"AGENT_STATUS_UNSUPPORTED: {normalized_to_status}")
    normalized_request_id = _required_text(request_id, "AGENT_REQUEST_ID_REQUIRED")
    normalized_actor = _required_text(actor, "AGENT_ACTOR_REQUIRED")
    normalized_idempotency_key = _required_text(idempotency_key, "AGENT_IDEMPOTENCY_KEY_REQUIRED")
    normalized_payload = _safe_object(payload, "AGENT_EVENT_PAYLOAD_OBJECT_REQUIRED")
    normalized_correlation_id = _optional_text(correlation_id)
    patch = _transition_patch(
        plan_generation=plan_generation,
        active_draft_id=active_draft_id,
        active_draft_revision=active_draft_revision,
        active_plan_hash=active_plan_hash,
        workflow_revision_id=workflow_revision_id,
        planner=planner,
        last_error_code=last_error_code,
    )
    command = {
        "actor": normalized_actor,
        "correlationId": normalized_correlation_id,
        "eventType": normalized_event_type,
        "expectedPlanGeneration": expected_plan_generation,
        "expectedPlanHash": _optional_text(expected_plan_hash),
        "expectedStateVersion": int(expected_state_version),
        "patch": patch,
        "payload": normalized_payload,
        "requestId": normalized_request_id,
        "sessionId": normalized_session_id,
        "toStatus": normalized_to_status,
    }
    command_hash = _hash_json(command)

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT * FROM agent_events
                WHERE session_id = ? AND idempotency_key = ?
                """,
                (normalized_session_id, normalized_idempotency_key),
            ).fetchone()
            if replay is not None:
                if str(replay["command_hash"]) != command_hash:
                    raise AgentSessionStorageConflictError("AGENT_COMMAND_IDEMPOTENCY_CONFLICT")
                session_row = _fetch_session_row(connection, normalized_session_id)
                connection.commit()
                return {"session": _session_row_to_dict(session_row), "event": _event_row_to_dict(replay), "replayed": True}

            current = _fetch_session_row(connection, normalized_session_id)
            current_state_version = int(current["state_version"])
            if current_state_version != int(expected_state_version):
                raise AgentSessionStorageConflictError("AGENT_SESSION_STATE_VERSION_CONFLICT")
            current_plan_generation = int(current["plan_generation"])
            if expected_plan_generation is not None and current_plan_generation != int(expected_plan_generation):
                raise AgentSessionStorageConflictError("AGENT_SESSION_PLAN_GENERATION_CONFLICT")
            normalized_expected_plan_hash = _optional_text(expected_plan_hash)
            if normalized_expected_plan_hash is not None and _optional_text(current["active_plan_hash"]) != normalized_expected_plan_hash:
                raise AgentSessionStorageConflictError("AGENT_SESSION_PLAN_HASH_CONFLICT")

            next_state_version = current_state_version + 1
            next_plan_generation = int(patch.get("planGeneration", current_plan_generation))
            updated_at = now_iso()
            values = _session_update_values(current, patch)
            cursor = connection.execute(
                """
                UPDATE agent_sessions
                SET status = ?, state_version = ?, plan_generation = ?,
                    active_draft_id = ?, active_draft_revision = ?, active_plan_hash = ?,
                    workflow_revision_id = ?, planner_json = ?, last_error_code = ?,
                    updated_at = ?, cancelled_at = ?
                WHERE session_id = ? AND state_version = ?
                """,
                (
                    normalized_to_status,
                    next_state_version,
                    next_plan_generation,
                    values["activeDraftId"],
                    values["activeDraftRevision"],
                    values["activePlanHash"],
                    values["workflowRevisionId"],
                    _stable_json(values["planner"]),
                    values["lastErrorCode"],
                    updated_at,
                    updated_at if normalized_to_status == "cancelled" else current["cancelled_at"],
                    normalized_session_id,
                    current_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise AgentSessionStorageConflictError("AGENT_SESSION_STATE_VERSION_CONFLICT")
            event = append_agent_event_record(
                connection,
                session_id=normalized_session_id,
                event_type=normalized_event_type,
                from_status=str(current["status"]),
                to_status=normalized_to_status,
                state_version=next_state_version,
                plan_generation=next_plan_generation,
                actor=normalized_actor,
                request_id=normalized_request_id,
                correlation_id=normalized_correlation_id,
                idempotency_key=normalized_idempotency_key,
                command_hash=command_hash,
                payload=normalized_payload,
                created_at=updated_at,
            )
            session_row = _fetch_session_row(connection, normalized_session_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"session": _session_row_to_dict(session_row), "event": event, "replayed": False}


def fetch_agent_events(cfg: RemoteRunnerConfig, session_id: str) -> list[dict[str, Any]]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM agent_events WHERE session_id = ? ORDER BY seq ASC",
            (normalized_session_id,),
        ).fetchall()
    return [_event_row_to_dict(row) for row in rows]


def verify_agent_event_hash_chain(cfg: RemoteRunnerConfig, session_id: str) -> dict[str, Any]:
    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM agent_events WHERE session_id = ? ORDER BY seq ASC",
            (normalized_session_id,),
        ).fetchall()
    previous_hash: str | None = None
    for expected_sequence, row in enumerate(rows, start=1):
        if int(row["seq"]) != expected_sequence:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "SEQUENCE_GAP"}
        payload = json.loads(row["payload_json"])
        if _hash_json(payload) != row["payload_hash"]:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "PAYLOAD_HASH_MISMATCH"}
        if _optional_text(row["prev_event_hash"]) != previous_hash:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "PREV_EVENT_HASH_MISMATCH"}
        expected_hash = _event_hash(
            session_id=str(row["session_id"]),
            event_type=str(row["event_type"]),
            sequence=int(row["seq"]),
            schema_version=str(row["schema_version"]),
            from_status=_optional_text(row["from_status"]),
            to_status=str(row["to_status"]),
            state_version=int(row["state_version"]),
            plan_generation=int(row["plan_generation"]),
            actor=str(row["actor"]),
            request_id=str(row["request_id"]),
            correlation_id=_optional_text(row["correlation_id"]),
            idempotency_key=str(row["idempotency_key"]),
            command_hash=str(row["command_hash"]),
            payload_hash=str(row["payload_hash"]),
            prev_event_hash=previous_hash,
            created_at=str(row["created_at"]),
        )
        if expected_hash != row["event_hash"]:
            return {"valid": False, "checked": expected_sequence - 1, "reason": "EVENT_HASH_MISMATCH"}
        previous_hash = str(row["event_hash"])
    return {"valid": True, "checked": len(rows), "reason": None}


def canonical_agent_plan_hash(plan: dict[str, Any]) -> str:
    return _hash_json(_safe_object(plan, "AGENT_PLAN_OBJECT_REQUIRED"))


def append_agent_event_record(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    event_type: str,
    from_status: str | None,
    to_status: str,
    state_version: int,
    plan_generation: int,
    actor: str,
    request_id: str,
    idempotency_key: str,
    command_hash: str,
    payload: dict[str, Any],
    created_at: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    sequence_row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM agent_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    sequence = int(sequence_row["next_seq"])
    previous = connection.execute(
        "SELECT event_hash FROM agent_events WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    prev_event_hash = str(previous["event_hash"]) if previous is not None else None
    payload_hash = _hash_json(payload)
    event_hash = _event_hash(
        session_id=session_id,
        event_type=event_type,
        sequence=sequence,
        schema_version=AGENT_SESSION_EVENT_CONTRACT_VERSION,
        from_status=from_status,
        to_status=to_status,
        state_version=state_version,
        plan_generation=plan_generation,
        actor=actor,
        request_id=request_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        command_hash=command_hash,
        payload_hash=payload_hash,
        prev_event_hash=prev_event_hash,
        created_at=created_at,
    )
    event_id = f"agev_{uuid.uuid4().hex[:16]}"
    connection.execute(
        """
        INSERT INTO agent_events (
            event_id, session_id, seq, schema_version, event_type, from_status,
            to_status, state_version, plan_generation, actor, request_id,
            correlation_id, idempotency_key, command_hash, payload_json,
            payload_hash, event_hash, prev_event_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            sequence,
            AGENT_SESSION_EVENT_CONTRACT_VERSION,
            event_type,
            from_status,
            to_status,
            int(state_version),
            int(plan_generation),
            actor,
            request_id,
            correlation_id,
            idempotency_key,
            command_hash,
            _stable_json(payload),
            payload_hash,
            event_hash,
            prev_event_hash,
            created_at,
        ),
    )
    row = connection.execute("SELECT * FROM agent_events WHERE event_id = ?", (event_id,)).fetchone()
    return _event_row_to_dict(row)


def _fetch_session_row(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise AgentSessionStorageNotFoundError("AGENT_SESSION_NOT_FOUND")
    return row


def _transition_patch(**values: Any) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    names = {
        "plan_generation": "planGeneration",
        "active_draft_id": "activeDraftId",
        "active_draft_revision": "activeDraftRevision",
        "active_plan_hash": "activePlanHash",
        "workflow_revision_id": "workflowRevisionId",
        "planner": "planner",
        "last_error_code": "lastErrorCode",
    }
    for source, target in names.items():
        value = values[source]
        if value is _UNSET:
            continue
        if target == "planGeneration":
            normalized = int(value)
            if normalized < 0:
                raise ValueError("AGENT_PLAN_GENERATION_INVALID")
            patch[target] = normalized
        elif target == "activeDraftRevision":
            patch[target] = None if value is None else int(value)
        elif target == "planner":
            patch[target] = _safe_object(value, "AGENT_PLANNER_OBJECT_REQUIRED")
        elif target == "lastErrorCode":
            patch[target] = str(value or "").strip()
        else:
            patch[target] = _optional_text(value)
    return patch


def _session_update_values(current: sqlite3.Row, patch: dict[str, Any]) -> dict[str, Any]:
    return {
        "activeDraftId": patch.get("activeDraftId", current["active_draft_id"]),
        "activeDraftRevision": patch.get("activeDraftRevision", current["active_draft_revision"]),
        "activePlanHash": patch.get("activePlanHash", current["active_plan_hash"]),
        "workflowRevisionId": patch.get("workflowRevisionId", current["workflow_revision_id"]),
        "planner": patch.get("planner", json.loads(current["planner_json"])),
        "lastErrorCode": patch.get("lastErrorCode", str(current["last_error_code"] or "")),
    }


def _session_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "sessionId": row["session_id"],
        "contractVersion": row["contract_version"],
        "projectId": row["project_id"],
        "goal": json.loads(row["goal_json"]),
        "constraints": json.loads(row["constraints_json"]),
        "budget": json.loads(row["budget_json"]),
        "status": row["status"],
        "stateVersion": int(row["state_version"]),
        "planGeneration": int(row["plan_generation"]),
        "activeDraftId": row["active_draft_id"],
        "activeDraftRevision": row["active_draft_revision"],
        "activePlanHash": row["active_plan_hash"],
        "workflowRevisionId": row["workflow_revision_id"],
        "planner": json.loads(row["planner_json"]),
        "lastErrorCode": row["last_error_code"],
        "creationRequestId": row["creation_request_id"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "cancelledAt": row["cancelled_at"],
    }
    AgentSessionRecord.model_validate(payload)
    return payload


def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "eventId": row["event_id"],
        "sessionId": row["session_id"],
        "sequence": int(row["seq"]),
        "schemaVersion": row["schema_version"],
        "eventType": row["event_type"],
        "fromStatus": row["from_status"],
        "toStatus": row["to_status"],
        "stateVersion": int(row["state_version"]),
        "planGeneration": int(row["plan_generation"]),
        "actor": row["actor"],
        "requestId": row["request_id"],
        "correlationId": row["correlation_id"],
        "idempotencyKey": row["idempotency_key"],
        "payload": json.loads(row["payload_json"]),
        "payloadHash": row["payload_hash"],
        "eventHash": row["event_hash"],
        "prevEventHash": row["prev_event_hash"],
        "createdAt": row["created_at"],
    }
    AgentSessionEvent.model_validate(payload)
    return payload


def _event_hash(**payload: Any) -> str:
    return _hash_json(payload)


def _safe_object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(code)
    _assert_safe_payload(value)
    return json.loads(_stable_json(value))


def _assert_safe_payload(value: Any) -> None:
    assert_agent_session_json_safe(value, path="agent.storage")


def _hash_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
