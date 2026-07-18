"""Immutable, fail-closed effect budgets for AgentSession run submission."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from core.contracts.agent_effect_budget import (
    AgentSessionEffectBudgetGrantRequest,
    AgentSessionEffectBudgetRead,
    AgentSessionEffectBudgetReceipt,
    agent_effect_budget_command_hash,
    agent_effect_budget_receipt_hash,
)

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError, WorkflowDesignRevisionConflictError
from .storage_core import get_connection, now_iso


EFFECT_BUDGET_CONTRACT_VERSION = "agent-session-effect-budget.v1"
EFFECT_BUDGET_READ_CONTRACT_VERSION = "agent-session-effect-budget-read.v1"


class AgentEffectBudgetStorageConflictError(WorkflowDesignRevisionConflictError):
    """Raised when an effect-budget grant conflicts with durable state."""


class AgentEffectBudgetStorageNotFoundError(RemoteRunnerNotFoundError):
    """Raised when the target AgentSession does not exist."""


def read_agent_session_effect_budget(
    cfg: RemoteRunnerConfig,
    session_id: str,
) -> dict[str, Any]:
    """Return an authoritative 200-style absent/present projection."""

    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        _require_session(connection, normalized_session_id)
        receipt = fetch_agent_effect_budget_for_connection(connection, normalized_session_id)
    return _effect_budget_read(normalized_session_id, receipt)


def effective_agent_run_submission_limit(
    cfg: RemoteRunnerConfig,
    session_id: str,
) -> int:
    """Return the fail-closed effective limit; a missing row always means zero."""

    read = read_agent_session_effect_budget(cfg, session_id)
    budget = read.get("budget")
    return int(budget["maxRunSubmissions"]) if isinstance(budget, dict) else 0


def grant_agent_session_effect_budget(
    cfg: RemoteRunnerConfig,
    session_id: str,
    request: AgentSessionEffectBudgetGrantRequest | Mapping[str, object],
    *,
    actor: str,
) -> dict[str, Any]:
    """Grant one immutable run submission with replay before and inside the writer transaction."""

    normalized_session_id = _required_text(session_id, "AGENT_SESSION_ID_REQUIRED")
    normalized_actor = _required_text(actor, "AGENT_EFFECT_BUDGET_ACTOR_REQUIRED")
    normalized_request = AgentSessionEffectBudgetGrantRequest.model_validate(
        request.runtime_payload()
        if isinstance(request, AgentSessionEffectBudgetGrantRequest)
        else request
    )
    command_hash = agent_effect_budget_command_hash(
        normalized_session_id,
        normalized_actor,
        normalized_request,
    )

    # The first read keeps committed retries independent of current session state.
    with get_connection(cfg) as connection:
        replay = _resolve_effect_budget_replay(
            connection,
            session_id=normalized_session_id,
            idempotency_key=normalized_request.idempotencyKey,
            actor=normalized_actor,
            command_hash=command_hash,
        )
    if replay is not None:
        return replay

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            # A same-key request may have committed while the fast path was a miss.
            replay = _resolve_effect_budget_replay(
                connection,
                session_id=normalized_session_id,
                idempotency_key=normalized_request.idempotencyKey,
                actor=normalized_actor,
                command_hash=command_hash,
            )
            if replay is not None:
                connection.commit()
                return replay
            _require_effect_budget_admission(
                connection,
                session_id=normalized_session_id,
                expected_state_version=normalized_request.expectedStateVersion,
            )
            receipt = _new_effect_budget_receipt(
                session_id=normalized_session_id,
                actor=normalized_actor,
                request=normalized_request,
                command_hash=command_hash,
            )
            _insert_effect_budget_for_connection(connection, receipt)
            connection.commit()
            return receipt.runtime_payload()
        except Exception:
            connection.rollback()
            raise


def fetch_agent_effect_budget_for_connection(
    connection: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Read and verify the immutable receipt without opening another connection."""

    row = connection.execute(
        "SELECT * FROM agent_session_effect_budgets WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return None if row is None else agent_effect_budget_row_to_dict(row)


def agent_effect_budget_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "contractVersion": row["contract_version"],
        "sessionId": row["session_id"],
        "maxRunSubmissions": int(row["max_run_submissions"]),
        "actor": row["actor"],
        "requestId": row["request_id"],
        "idempotencyKey": row["idempotency_key"],
        "commandHash": row["command_hash"],
        "receiptHash": row["receipt_hash"],
        "createdAt": row["created_at"],
    }
    expected_hash = agent_effect_budget_receipt_hash(payload)
    if expected_hash != payload["receiptHash"]:
        raise AgentEffectBudgetStorageConflictError(
            "AGENT_EFFECT_BUDGET_STORED_RECEIPT_HASH_MISMATCH"
        )
    receipt = AgentSessionEffectBudgetReceipt.model_validate(payload)
    return receipt.runtime_payload()


def _resolve_effect_budget_replay(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    idempotency_key: str,
    actor: str,
    command_hash: str,
) -> dict[str, Any] | None:
    existing = fetch_agent_effect_budget_for_connection(connection, session_id)
    if existing is None:
        return None
    if (
        existing["idempotencyKey"] != idempotency_key
        or existing["actor"] != actor
        or existing["commandHash"] != command_hash
    ):
        raise AgentEffectBudgetStorageConflictError(
            "AGENT_EFFECT_BUDGET_ALREADY_GRANTED"
        )
    return existing


def _require_effect_budget_admission(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    expected_state_version: int,
) -> None:
    session = _require_session(connection, session_id)
    if (
        str(session["status"]) != "created"
        or int(session["state_version"]) != 1
        or int(session["plan_generation"]) != 0
    ):
        raise AgentEffectBudgetStorageConflictError(
            "AGENT_EFFECT_BUDGET_ADMISSION_CLOSED"
        )
    if int(session["state_version"]) != int(expected_state_version):
        raise AgentEffectBudgetStorageConflictError(
            "AGENT_EFFECT_BUDGET_STATE_VERSION_CONFLICT"
        )
    plan = connection.execute(
        "SELECT 1 FROM agent_plan_revisions WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()
    if plan is not None:
        raise AgentEffectBudgetStorageConflictError(
            "AGENT_EFFECT_BUDGET_ADMISSION_CLOSED"
        )


def _require_session(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM agent_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise AgentEffectBudgetStorageNotFoundError("AGENT_SESSION_NOT_FOUND")
    return row


def _new_effect_budget_receipt(
    *,
    session_id: str,
    actor: str,
    request: AgentSessionEffectBudgetGrantRequest,
    command_hash: str,
) -> AgentSessionEffectBudgetReceipt:
    payload: dict[str, object] = {
        "contractVersion": EFFECT_BUDGET_CONTRACT_VERSION,
        "sessionId": session_id,
        "maxRunSubmissions": request.maxRunSubmissions,
        "actor": actor,
        "requestId": request.requestId,
        "idempotencyKey": request.idempotencyKey,
        "commandHash": command_hash,
        "createdAt": now_iso(),
    }
    payload["receiptHash"] = agent_effect_budget_receipt_hash(payload)
    return AgentSessionEffectBudgetReceipt.model_validate(payload)


def _insert_effect_budget_for_connection(
    connection: sqlite3.Connection,
    receipt: AgentSessionEffectBudgetReceipt,
) -> None:
    connection.execute(
        """
        INSERT INTO agent_session_effect_budgets (
            session_id, contract_version, max_run_submissions, actor,
            request_id, idempotency_key, command_hash, receipt_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt.sessionId,
            receipt.contractVersion,
            receipt.maxRunSubmissions,
            receipt.actor,
            receipt.requestId,
            receipt.idempotencyKey,
            receipt.commandHash,
            receipt.receiptHash,
            receipt.createdAt,
        ),
    )


def _effect_budget_read(
    session_id: str,
    receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    read = AgentSessionEffectBudgetRead.model_validate(
        {
            "contractVersion": EFFECT_BUDGET_READ_CONTRACT_VERSION,
            "sessionId": session_id,
            "state": "present" if receipt is not None else "absent",
            "budget": receipt,
        }
    )
    return read.runtime_payload()


def _required_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)
    return value


__all__ = [
    "AgentEffectBudgetStorageConflictError",
    "AgentEffectBudgetStorageNotFoundError",
    "agent_effect_budget_row_to_dict",
    "effective_agent_run_submission_limit",
    "fetch_agent_effect_budget_for_connection",
    "grant_agent_session_effect_budget",
    "read_agent_session_effect_budget",
]
