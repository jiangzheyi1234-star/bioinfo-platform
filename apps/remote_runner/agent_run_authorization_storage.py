"""Connection-scoped immutable storage for Agent-to-WorkflowRun bindings."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationRead,
    AgentRunAuthorizationReceipt,
    agent_run_authorization_receipt_hash,
)

from .errors import RemoteRunnerNotFoundError, WorkflowDesignRevisionConflictError


RUN_AUTHORIZATION_READ_CONTRACT_VERSION = "agent-run-authorization-read.v1"


class AgentRunAuthorizationStorageConflictError(WorkflowDesignRevisionConflictError):
    """Raised when an authorization binding conflicts with immutable storage."""


class AgentRunAuthorizationStorageNotFoundError(RemoteRunnerNotFoundError):
    """Raised when an authorization read targets an unknown AgentSession."""


def fetch_agent_run_authorization_by_session_for_connection(
    connection: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM agent_run_authorizations WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return None if row is None else agent_run_authorization_row_to_dict(row)


def fetch_agent_run_authorization_by_idempotency_for_connection(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM agent_run_authorizations
        WHERE session_id = ? AND idempotency_key = ?
        """,
        (session_id, idempotency_key),
    ).fetchone()
    return None if row is None else agent_run_authorization_row_to_dict(row)


def fetch_agent_run_authorization_by_run_for_connection(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM agent_run_authorizations WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return None if row is None else agent_run_authorization_row_to_dict(row)


def count_agent_run_authorizations_for_connection(
    connection: sqlite3.Connection,
    session_id: str,
) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM agent_run_authorizations WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row[0] if row is not None else 0)


def read_agent_run_authorization_for_connection(
    connection: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any]:
    """Return the strict 200-style absent/present binding projection."""

    session = connection.execute(
        "SELECT 1 FROM agent_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if session is None:
        raise AgentRunAuthorizationStorageNotFoundError("AGENT_SESSION_NOT_FOUND")
    receipt = fetch_agent_run_authorization_by_session_for_connection(
        connection,
        session_id,
    )
    read = AgentRunAuthorizationRead.model_validate(
        {
            "contractVersion": RUN_AUTHORIZATION_READ_CONTRACT_VERSION,
            "sessionId": session_id,
            "state": "present" if receipt is not None else "absent",
            "receipt": receipt,
        }
    )
    return read.runtime_payload()


def resolve_agent_run_authorization_replay_for_connection(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    idempotency_key: str,
    actor: str,
    command_hash: str,
) -> dict[str, Any] | None:
    """Resolve exact replay or reject any conflicting one-binding command."""

    existing = fetch_agent_run_authorization_by_idempotency_for_connection(
        connection,
        session_id=session_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing["actor"] != actor or existing["commandHash"] != command_hash:
            raise AgentRunAuthorizationStorageConflictError(
                "AGENT_RUN_AUTHORIZATION_IDEMPOTENCY_CONFLICT"
            )
        return existing
    binding = fetch_agent_run_authorization_by_session_for_connection(
        connection,
        session_id,
    )
    if binding is not None:
        raise AgentRunAuthorizationStorageConflictError(
            "AGENT_RUN_AUTHORIZATION_ALREADY_BOUND"
        )
    return None


def insert_agent_run_authorization_for_connection(
    connection: sqlite3.Connection,
    receipt: AgentRunAuthorizationReceipt | Mapping[str, object],
) -> dict[str, Any]:
    """Insert a verified binding into the caller's existing writer transaction."""

    if not connection.in_transaction:
        raise RuntimeError("AGENT_RUN_AUTHORIZATION_WRITER_TRANSACTION_REQUIRED")
    normalized = AgentRunAuthorizationReceipt.model_validate(
        receipt.runtime_payload()
        if isinstance(receipt, AgentRunAuthorizationReceipt)
        else receipt
    )
    _require_receipt_hash(normalized)
    try:
        connection.execute(
            """
            INSERT INTO agent_run_authorizations (
                authorization_id, contract_version, session_id, preview_hash,
                plan_revision_id, plan_generation, plan_hash,
                workflow_revision_id, expected_state_version,
                input_manifest_digest, run_spec_hash, execution_policy_id,
                execution_policy_hash, runtime_lock_hash, runtime_proof_hash,
                effect_budget_hash, run_id, scope, confirmation, actor,
                request_id, idempotency_key, command_hash, receipt_hash, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                normalized.authorizationId,
                normalized.contractVersion,
                normalized.sessionId,
                normalized.previewHash,
                normalized.planRevisionId,
                normalized.planGeneration,
                normalized.planHash,
                normalized.workflowRevisionId,
                normalized.expectedStateVersion,
                normalized.inputManifestDigest,
                normalized.runSpecHash,
                normalized.executionPolicyId,
                normalized.executionPolicyHash,
                normalized.runtimeLockHash,
                normalized.runtimeProofHash,
                normalized.effectBudgetHash,
                normalized.runId,
                normalized.scope,
                normalized.confirmation,
                normalized.actor,
                normalized.requestId,
                normalized.idempotencyKey,
                normalized.commandHash,
                normalized.receiptHash,
                normalized.createdAt,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AgentRunAuthorizationStorageConflictError(
            "AGENT_RUN_AUTHORIZATION_STORAGE_CONFLICT"
        ) from exc
    return normalized.runtime_payload()


def agent_run_authorization_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        "authorizationId": row["authorization_id"],
        "contractVersion": row["contract_version"],
        "sessionId": row["session_id"],
        "previewHash": row["preview_hash"],
        "planRevisionId": row["plan_revision_id"],
        "planGeneration": int(row["plan_generation"]),
        "planHash": row["plan_hash"],
        "workflowRevisionId": row["workflow_revision_id"],
        "expectedStateVersion": int(row["expected_state_version"]),
        "inputManifestDigest": row["input_manifest_digest"],
        "runSpecHash": row["run_spec_hash"],
        "executionPolicyId": row["execution_policy_id"],
        "executionPolicyHash": row["execution_policy_hash"],
        "runtimeLockHash": row["runtime_lock_hash"],
        "runtimeProofHash": row["runtime_proof_hash"],
        "effectBudgetHash": row["effect_budget_hash"],
        "runId": row["run_id"],
        "scope": row["scope"],
        "confirmation": row["confirmation"],
        "actor": row["actor"],
        "requestId": row["request_id"],
        "idempotencyKey": row["idempotency_key"],
        "commandHash": row["command_hash"],
        "receiptHash": row["receipt_hash"],
        "createdAt": row["created_at"],
    }
    expected_hash = agent_run_authorization_receipt_hash(payload)
    if expected_hash != payload["receiptHash"]:
        raise AgentRunAuthorizationStorageConflictError(
            "AGENT_RUN_AUTHORIZATION_STORED_RECEIPT_HASH_MISMATCH"
        )
    receipt = AgentRunAuthorizationReceipt.model_validate(payload)
    return receipt.runtime_payload()


def _require_receipt_hash(receipt: AgentRunAuthorizationReceipt) -> None:
    expected_hash = agent_run_authorization_receipt_hash(receipt.runtime_payload())
    if expected_hash != receipt.receiptHash:
        raise AgentRunAuthorizationStorageConflictError(
            "AGENT_RUN_AUTHORIZATION_STORED_RECEIPT_HASH_MISMATCH"
        )


__all__ = [
    "AgentRunAuthorizationStorageConflictError",
    "AgentRunAuthorizationStorageNotFoundError",
    "agent_run_authorization_row_to_dict",
    "count_agent_run_authorizations_for_connection",
    "fetch_agent_run_authorization_by_idempotency_for_connection",
    "fetch_agent_run_authorization_by_run_for_connection",
    "fetch_agent_run_authorization_by_session_for_connection",
    "insert_agent_run_authorization_for_connection",
    "read_agent_run_authorization_for_connection",
    "resolve_agent_run_authorization_replay_for_connection",
]
