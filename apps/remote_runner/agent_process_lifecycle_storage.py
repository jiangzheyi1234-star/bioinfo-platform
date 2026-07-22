"""Atomic connection-scoped lifecycle storage for governed Agent processes."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Literal

from core.contracts.agent_fastq_qc_execution import agent_workflow_run_spec_hash
from core.contracts.agent_process_lifecycle import agent_process_gate_token_hash

from .agent_process_lifecycle_reasons import (
    AGENT_PROCESS_EXIT_REASONS,
    AGENT_PROCESS_LOSS_REASONS,
    AGENT_PROCESS_SPAWN_FAILURE_CODES,
    AGENT_PROCESS_TERMINATION_REASONS,
)
from .agent_process_lifecycle_read_model import (
    AGENT_PROCESS_LIFECYCLE_ACTOR as _ACTOR,
    AGENT_PROCESS_LIFECYCLE_EVENT_MESSAGES as _EVENT_MESSAGES,
    AGENT_PROCESS_LIFECYCLE_STAGE as _STAGE,
    AgentProcessPlatform,
    AgentProcessLifecycleStorageConflictError,
    agent_process_lifecycle_common_payload as _common_payload,
    agent_process_lifecycle_conflict as _conflict,
    build_agent_process_lifecycle_transition_result as _transition_result,
    fetch_agent_process_lifecycle_for_connection,
    normalize_agent_process_incarnation as _normalize_incarnation,
    require_agent_process_exact_incarnation as _require_exact_incarnation,
    require_agent_process_started_replay as _require_started_replay,
    require_agent_process_terminal_replay as _require_terminal_replay,
    require_valid_agent_process_event_chain as _require_valid_event_chain,
    stable_agent_process_json as _stable_json,
    validated_agent_process_lifecycle_read_model as _validated_read_model,
)
from .agent_run_authorization_storage import (
    fetch_agent_run_authorization_by_id_for_connection,
)
from .agent_run_input_materialization import (
    read_agent_run_input_expectation_for_connection,
    require_unique_agent_run_input_materialization_event_for_connection,
)
from .agent_workspace_proof_storage import (
    fetch_agent_workspace_proof_by_id_for_connection,
)
from .event_contracts import append_run_event_v2
from .execution_lease_time import execution_lease_expiry_is_future
from .sqlite_migrations import ensure_runtime_schema_current
from .workflow_revision_storage import fetch_workflow_revision_for_connection


AgentProcessTerminalState = Literal["exited", "terminated", "lost"]

_LOWER_SHA256 = frozenset("0123456789abcdef")
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_SAVEPOINT = "agent_process_lifecycle_write"


def mark_agent_process_started_for_connection(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    gate_token: bytes,
    expected_platform: AgentProcessPlatform,
    process_pid: int,
    process_group_id: int,
    process_incarnation: Mapping[str, object],
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Consume one gate token and CAS ``prepared`` to ``started``.

    This connection-scoped primitive never commits and never releases the gated
    process. ``transactionApplied`` only describes its current transaction.
    """

    _require_current_writer_schema(connection)
    pid = _positive_integer(process_pid, "AGENT_PROCESS_PID_INVALID")
    group_id = _positive_integer(
        process_group_id,
        "AGENT_PROCESS_GROUP_ID_INVALID",
    )
    if group_id != pid:
        _conflict("AGENT_PROCESS_CONTAINMENT_LEADER_INVALID")
    incarnation, incarnation_json, incarnation_hash = _normalize_incarnation(
        process_incarnation,
        expected_pid=pid,
        expected_platform=expected_platform,
    )
    with _lifecycle_savepoint(connection):
        row = _require_process_row(connection, process_instance_id)
        model = _validated_read_model(connection, row)
        _require_gate_token(row, gate_token)
        if model["state"] == "started":
            _require_started_replay(
                model,
                process_pid=pid,
                process_group_id=group_id,
                process_platform=expected_platform,
                process_incarnation=incarnation,
                process_incarnation_hash=incarnation_hash,
            )
            return _transition_result(
                connection,
                model,
                transaction_applied=False,
            )
        if model["state"] != "prepared":
            _conflict("AGENT_PROCESS_LIFECYCLE_STATE_CONFLICT")

        state_version, request_id = _require_live_start_authority(connection, row)
        payload = {
            **_common_payload(row),
            "launchSpecHash": row["launch_spec_hash"],
            "priorProcessEventHash": row["spawn_intent_event_hash"],
            "priorProcessEventId": row["spawn_intent_event_id"],
            "processGroupId": group_id,
            "processIncarnationHash": incarnation_hash,
            "processPid": pid,
        }
        event = _append_lifecycle_event(
            connection,
            row=row,
            event_type="agent_process_started",
            state_version=state_version,
            request_id=request_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        updated = connection.execute(
            """
            UPDATE agent_process_instances
            SET state = 'started', process_pid = ?, process_group_id = ?,
                process_incarnation_json = ?, process_incarnation_hash = ?,
                started_event_id = ?, started_at = ?
            WHERE process_instance_id = ? AND state = 'prepared'
              AND gate_token_hash = ?
            """,
            (
                pid,
                group_id,
                incarnation_json,
                incarnation_hash,
                event["eventId"],
                event["occurred_at"],
                row["process_instance_id"],
                row["gate_token_hash"],
            ),
        )
        _require_single_cas(updated)
        model = _require_read_back(connection, str(row["process_instance_id"]))
        _require_started_replay(
            model,
            process_pid=pid,
            process_group_id=group_id,
            process_platform=expected_platform,
            process_incarnation=incarnation,
            process_incarnation_hash=incarnation_hash,
        )
        return _transition_result(connection, model, transaction_applied=True)


def mark_agent_process_spawn_failed_for_connection(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    gate_token: bytes,
    failure_code: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Consume one gate token and atomically close a failed spawn attempt."""

    _require_current_writer_schema(connection)
    normalized_failure = _require_enum(
        failure_code,
        AGENT_PROCESS_SPAWN_FAILURE_CODES,
        "AGENT_PROCESS_FAILURE_CODE_INVALID",
    )
    with _lifecycle_savepoint(connection):
        row = _require_process_row(connection, process_instance_id)
        model = _validated_read_model(connection, row)
        _require_gate_token(row, gate_token)
        if model["state"] == "spawn_failed":
            if model["exitReason"] != normalized_failure:
                _conflict("AGENT_PROCESS_LIFECYCLE_REPLAY_CONFLICT")
            return _transition_result(
                connection,
                model,
                transaction_applied=False,
            )
        if model["state"] != "prepared":
            _conflict("AGENT_PROCESS_LIFECYCLE_STATE_CONFLICT")

        state_version, request_id = _run_event_context(connection, row)
        payload = {
            **_common_payload(row),
            "failureCode": normalized_failure,
            "launchSpecHash": row["launch_spec_hash"],
            "priorProcessEventHash": row["spawn_intent_event_hash"],
            "priorProcessEventId": row["spawn_intent_event_id"],
        }
        event = _append_lifecycle_event(
            connection,
            row=row,
            event_type="agent_process_spawn_failed",
            state_version=state_version,
            request_id=request_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        updated = connection.execute(
            """
            UPDATE agent_process_instances
            SET state = 'spawn_failed', terminal_event_id = ?,
                exit_reason = ?, finished_at = ?
            WHERE process_instance_id = ? AND state = 'prepared'
              AND gate_token_hash = ?
            """,
            (
                event["eventId"],
                normalized_failure,
                event["occurred_at"],
                row["process_instance_id"],
                row["gate_token_hash"],
            ),
        )
        _require_single_cas(updated)
        model = _require_read_back(connection, str(row["process_instance_id"]))
        if (
            model["state"] != "spawn_failed"
            or model["exitReason"] != normalized_failure
        ):
            _conflict("AGENT_PROCESS_LIFECYCLE_READ_BACK_INVALID")
        return _transition_result(connection, model, transaction_applied=True)


def mark_agent_process_exited_for_connection(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    process_incarnation: Mapping[str, object],
    exit_code: int,
    exit_reason: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Atomically record a normal observed process exit."""

    normalized_code = _sqlite_integer(exit_code, "AGENT_PROCESS_EXIT_CODE_INVALID")
    return _mark_terminal(
        connection,
        process_instance_id=process_instance_id,
        process_incarnation=process_incarnation,
        terminal_state="exited",
        exit_code=normalized_code,
        exit_reason=_require_enum(
            exit_reason,
            AGENT_PROCESS_EXIT_REASONS,
            "AGENT_PROCESS_EXIT_REASON_INVALID",
        ),
        evidence_hash=None,
        occurred_at=occurred_at,
    )


def mark_agent_process_terminated_for_connection(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    process_incarnation: Mapping[str, object],
    exit_reason: str,
    evidence_hash: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Atomically record a positively identified process termination."""

    return _mark_stopped(
        connection,
        process_instance_id=process_instance_id,
        process_incarnation=process_incarnation,
        terminal_state="terminated",
        exit_reason=_require_enum(
            exit_reason,
            AGENT_PROCESS_TERMINATION_REASONS,
            "AGENT_PROCESS_EXIT_REASON_INVALID",
        ),
        evidence_hash=evidence_hash,
        occurred_at=occurred_at,
    )


def mark_agent_process_lost_for_connection(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    process_incarnation: Mapping[str, object],
    exit_reason: str,
    evidence_hash: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Atomically record fail-closed loss of the exact process identity."""

    return _mark_stopped(
        connection,
        process_instance_id=process_instance_id,
        process_incarnation=process_incarnation,
        terminal_state="lost",
        exit_reason=_require_enum(
            exit_reason,
            AGENT_PROCESS_LOSS_REASONS,
            "AGENT_PROCESS_EXIT_REASON_INVALID",
        ),
        evidence_hash=evidence_hash,
        occurred_at=occurred_at,
    )


def _mark_stopped(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    process_incarnation: Mapping[str, object],
    terminal_state: Literal["terminated", "lost"],
    exit_reason: str,
    evidence_hash: str,
    occurred_at: str | None,
) -> dict[str, Any]:
    return _mark_terminal(
        connection,
        process_instance_id=process_instance_id,
        process_incarnation=process_incarnation,
        terminal_state=terminal_state,
        exit_code=None,
        exit_reason=exit_reason,
        evidence_hash=_require_sha256(
            evidence_hash,
            "AGENT_PROCESS_EVIDENCE_HASH_INVALID",
        ),
        occurred_at=occurred_at,
    )


def _mark_terminal(
    connection: sqlite3.Connection,
    *,
    process_instance_id: str,
    process_incarnation: Mapping[str, object],
    terminal_state: AgentProcessTerminalState,
    exit_code: int | None,
    exit_reason: str,
    evidence_hash: str | None,
    occurred_at: str | None,
) -> dict[str, Any]:
    _require_current_writer_schema(connection)
    with _lifecycle_savepoint(connection):
        row = _require_process_row(connection, process_instance_id)
        model = _validated_read_model(connection, row)
        normalized_incarnation, _, incarnation_hash = _normalize_incarnation(
            process_incarnation,
            expected_pid=model.get("processPid"),
            expected_platform=model.get("processPlatform"),
        )
        if model["state"] in {"exited", "terminated", "lost"}:
            _require_terminal_replay(
                model,
                terminal_state=terminal_state,
                process_incarnation=normalized_incarnation,
                process_incarnation_hash=incarnation_hash,
                exit_code=exit_code,
                exit_reason=exit_reason,
                evidence_hash=evidence_hash,
            )
            return _transition_result(
                connection,
                model,
                transaction_applied=False,
            )
        if model["state"] != "started":
            _conflict("AGENT_PROCESS_LIFECYCLE_STATE_CONFLICT")
        _require_exact_incarnation(model, normalized_incarnation, incarnation_hash)
        state_version, request_id = _run_event_context(connection, row)
        payload: dict[str, object] = {
            **_common_payload(row),
            "exitReason": exit_reason,
            "launchSpecHash": row["launch_spec_hash"],
            "priorProcessEventHash": model["startedEventHash"],
            "priorProcessEventId": model["startedEventId"],
            "processIncarnationHash": incarnation_hash,
        }
        if terminal_state == "exited":
            payload["exitCode"] = exit_code
        else:
            payload["evidenceHash"] = evidence_hash
        event = _append_lifecycle_event(
            connection,
            row=row,
            event_type=f"agent_process_{terminal_state}",
            state_version=state_version,
            request_id=request_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        updated = connection.execute(
            """
            UPDATE agent_process_instances
            SET state = ?, terminal_event_id = ?, exit_code = ?,
                exit_reason = ?, finished_at = ?
            WHERE process_instance_id = ? AND state = 'started'
              AND process_incarnation_hash = ?
            """,
            (
                terminal_state,
                event["eventId"],
                exit_code,
                exit_reason,
                event["occurred_at"],
                row["process_instance_id"],
                incarnation_hash,
            ),
        )
        _require_single_cas(updated)
        model = _require_read_back(connection, str(row["process_instance_id"]))
        _require_terminal_replay(
            model,
            terminal_state=terminal_state,
            process_incarnation=normalized_incarnation,
            process_incarnation_hash=incarnation_hash,
            exit_code=exit_code,
            exit_reason=exit_reason,
            evidence_hash=evidence_hash,
        )
        return _transition_result(connection, model, transaction_applied=True)


def _require_live_start_authority(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[int, str]:
    try:
        authorization = fetch_agent_run_authorization_by_id_for_connection(
            connection,
            str(row["authorization_id"]),
        )
        proof = fetch_agent_workspace_proof_by_id_for_connection(
            connection,
            str(row["workspace_proof_id"]),
        )
        run = connection.execute(
            "SELECT status, state_version, request_id, workflow_revision_id, "
            "run_spec_json FROM runs WHERE run_id = ?",
            (row["run_id"],),
        ).fetchone()
        attempt = connection.execute(
            "SELECT run_id, job_id, lease_generation, state, cancel_requested_at "
            "FROM run_attempts WHERE attempt_id = ?",
            (row["attempt_id"],),
        ).fetchone()
        if authorization is None or proof is None or run is None or attempt is None:
            raise ValueError
        job = connection.execute(
            "SELECT run_id, state FROM run_jobs WHERE job_id = ?",
            (attempt["job_id"],),
        ).fetchone()
        lease = connection.execute(
            "SELECT attempt_id, lease_generation, expires_at, state "
            "FROM run_leases WHERE run_id = ?",
            (row["run_id"],),
        ).fetchone()
        run_spec = json.loads(str(run["run_spec_json"]))
        if not isinstance(run_spec, dict):
            raise ValueError
        if (
            authorization["authorizationId"] != row["authorization_id"]
            or authorization["runId"] != row["run_id"]
            or authorization["workflowRevisionId"] != run["workflow_revision_id"]
            or authorization["runSpecHash"] != agent_workflow_run_spec_hash(run_spec)
            or run["status"] != "running"
            or attempt["run_id"] != row["run_id"]
            or int(attempt["lease_generation"]) != int(row["lease_generation"])
            or attempt["state"] != "running"
            or attempt["cancel_requested_at"] is not None
            or job is None
            or job["run_id"] != row["run_id"]
            or job["state"] != "claimed"
            or lease is None
            or lease["attempt_id"] != row["attempt_id"]
            or int(lease["lease_generation"]) != int(row["lease_generation"])
            or lease["state"] != "active"
            or not execution_lease_expiry_is_future(lease["expires_at"])
        ):
            raise ValueError
        _require_proof_binding(connection, row, proof, authorization)
        expectation = read_agent_run_input_expectation_for_connection(
            connection,
            binding=authorization,
            run_spec=run_spec,
        )
        require_unique_agent_run_input_materialization_event_for_connection(
            connection,
            run_id=str(row["run_id"]),
            request_id=str(run["request_id"]),
            expectation=expectation,
        )
        _require_valid_event_chain(connection, str(row["run_id"]))
        return int(run["state_version"]), _required_text(
            run["request_id"],
            "AGENT_PROCESS_REQUEST_ID_INVALID",
        )
    except AgentProcessLifecycleStorageConflictError:
        raise
    except Exception as exc:
        raise AgentProcessLifecycleStorageConflictError(
            "AGENT_PROCESS_START_AUTHORITY_INVALID"
        ) from exc


def _require_proof_binding(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    proof: Mapping[str, object],
    authorization: Mapping[str, object],
) -> None:
    boundary = "pre_dry_run" if row["process_kind"] == "dry_run" else "pre_run"
    expected = {
        "attemptId": row["attempt_id"],
        "authorizationId": row["authorization_id"],
        "createdAt": row["prepared_at"],
        "eventId": row["spawn_intent_event_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "processBoundary": boundary,
        "processOrdinal": int(row["process_ordinal"]),
        "runId": row["run_id"],
        "toolAssetsHash": row["tool_assets_hash"],
        "workspaceProofId": row["workspace_proof_id"],
    }
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ValueError
    if (
        proof.get("workflowRevisionId") != authorization.get("workflowRevisionId")
        or proof.get("runSpecHash") != authorization.get("runSpecHash")
        or proof.get("runtimeLockHash") != authorization.get("runtimeLockHash")
        or proof.get("runtimeProofHash") != authorization.get("runtimeProofHash")
        or proof.get("inputSnapshotHash")
        != str(authorization.get("inputManifestDigest") or "").removeprefix("sha256:")
    ):
        raise ValueError
    revision = fetch_workflow_revision_for_connection(
        connection,
        str(proof["workflowRevisionId"]),
    )
    if revision is None:
        raise ValueError
    manifest_hash = hashlib.sha256(
        _stable_json(revision["manifest"]).encode("utf-8")
    ).hexdigest()
    if revision["contentHash"] != proof.get(
        "workflowRevisionContentHash"
    ) or manifest_hash != proof.get("workflowRevisionManifestHash"):
        raise ValueError


def _append_lifecycle_event(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    event_type: str,
    state_version: int,
    request_id: str,
    payload: dict[str, object],
    occurred_at: str | None,
) -> dict[str, Any]:
    event = append_run_event_v2(
        connection,
        run_id=str(row["run_id"]),
        event_type=event_type,
        stage=_STAGE,
        state_version=state_version,
        message=_EVENT_MESSAGES[event_type],
        request_id=request_id,
        payload=payload,
        actor=_ACTOR,
        occurred_at=occurred_at,
    )
    _require_valid_event_chain(connection, str(row["run_id"]))
    return event


def _require_gate_token(row: sqlite3.Row, gate_token: bytes) -> None:
    try:
        observed = agent_process_gate_token_hash(gate_token)
    except Exception as exc:
        raise AgentProcessLifecycleStorageConflictError(
            "AGENT_PROCESS_GATE_TOKEN_INVALID"
        ) from exc
    stored = row["gate_token_hash"]
    if not isinstance(stored, str) or not hmac.compare_digest(stored, observed):
        _conflict("AGENT_PROCESS_GATE_TOKEN_MISMATCH")


def _run_event_context(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[int, str]:
    run = connection.execute(
        "SELECT state_version, request_id FROM runs WHERE run_id = ?",
        (row["run_id"],),
    ).fetchone()
    if run is None:
        _conflict("AGENT_PROCESS_RUN_NOT_FOUND")
    return int(run["state_version"]), _required_text(
        run["request_id"],
        "AGENT_PROCESS_REQUEST_ID_INVALID",
    )


def _require_read_back(
    connection: sqlite3.Connection,
    process_instance_id: str,
) -> dict[str, Any]:
    row = _require_process_row(connection, process_instance_id)
    return _validated_read_model(connection, row)


def _fetch_process_row(
    connection: sqlite3.Connection,
    process_instance_id: str,
) -> sqlite3.Row | None:
    normalized = _required_text(
        process_instance_id,
        "AGENT_PROCESS_INSTANCE_ID_INVALID",
    )
    return connection.execute(
        "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
        (normalized,),
    ).fetchone()


def _require_process_row(
    connection: sqlite3.Connection,
    process_instance_id: str,
) -> sqlite3.Row:
    row = _fetch_process_row(connection, process_instance_id)
    if row is None:
        _conflict("AGENT_PROCESS_INSTANCE_NOT_FOUND")
    return row


def _require_writer_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError("AGENT_PROCESS_LIFECYCLE_WRITER_TRANSACTION_REQUIRED")


def _require_current_writer_schema(connection: sqlite3.Connection) -> None:
    _require_writer_transaction(connection)
    try:
        connection.execute("UPDATE agent_process_instances SET state = state WHERE 0")
        ensure_runtime_schema_current(connection)
    except Exception as exc:
        raise AgentProcessLifecycleStorageConflictError(
            "AGENT_PROCESS_LIFECYCLE_SCHEMA_INVALID"
        ) from exc


@contextmanager
def _lifecycle_savepoint(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute(f"SAVEPOINT {_SAVEPOINT}")
    try:
        yield
    except BaseException as exc:
        connection.execute(f"ROLLBACK TO {_SAVEPOINT}")
        connection.execute(f"RELEASE {_SAVEPOINT}")
        if isinstance(exc, AgentProcessLifecycleStorageConflictError):
            raise
        if isinstance(exc, sqlite3.Error):
            raise AgentProcessLifecycleStorageConflictError(
                "AGENT_PROCESS_LIFECYCLE_STORAGE_CONFLICT"
            ) from exc
        raise
    else:
        connection.execute(f"RELEASE {_SAVEPOINT}")


def _require_single_cas(cursor: sqlite3.Cursor) -> None:
    if cursor.rowcount != 1:
        _conflict("AGENT_PROCESS_LIFECYCLE_CAS_CONFLICT")


def _positive_integer(value: object, code: str) -> int:
    normalized = _sqlite_integer(value, code)
    if normalized <= 0:
        _conflict(code)
    return normalized


def _sqlite_integer(value: object, code: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < -_MAX_SQLITE_INTEGER - 1
        or value > _MAX_SQLITE_INTEGER
    ):
        _conflict(code)
    return value


def _required_text(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > 500
    ):
        _conflict(code)
    return value


def _require_enum(
    value: object,
    allowed: frozenset[str],
    code: str,
) -> str:
    if not isinstance(value, str) or value not in allowed:
        _conflict(code)
    return value


def _require_sha256(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or not set(value) <= _LOWER_SHA256
    ):
        _conflict(code)
    return value


__all__ = [
    "AgentProcessLifecycleStorageConflictError",
    "AgentProcessTerminalState",
    "fetch_agent_process_lifecycle_for_connection",
    "mark_agent_process_exited_for_connection",
    "mark_agent_process_lost_for_connection",
    "mark_agent_process_spawn_failed_for_connection",
    "mark_agent_process_started_for_connection",
    "mark_agent_process_terminated_for_connection",
]
