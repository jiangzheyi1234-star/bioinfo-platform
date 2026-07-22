"""Strict connection-scoped storage for prepared Agent process intents."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from core.contracts.agent_fastq_qc_execution import agent_workflow_run_spec_hash
from core.contracts.agent_process_instance import (
    AgentProcessLaunchIntentV1,
    build_agent_process_launch_intent_v1,
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
from .errors import WorkflowDesignRevisionConflictError
from .event_contracts import RUN_EVENT_ID_PATTERN, verify_run_event_hash_chain


_PREPARED_NULL_FIELDS = (
    "process_pid",
    "process_group_id",
    "process_incarnation_json",
    "process_incarnation_hash",
    "started_event_id",
    "terminal_event_id",
    "exit_code",
    "exit_reason",
    "started_at",
    "finished_at",
)
_SPAWN_EVENT_TYPE = "agent_process_spawn_intent_recorded"
_SPAWN_EVENT_STAGE = "agent_process"
_SPAWN_EVENT_MESSAGE = "Agent process launch intent prepared."
_SPAWN_EVENT_ACTOR = "remote-runner"
_PROCESS_ROW_PROJECTION = """
    SELECT process.*, event.event_id AS linked_spawn_event_id,
           event.run_id AS linked_spawn_run_id,
           event.event_type AS linked_spawn_event_type,
           event.seq AS linked_spawn_sequence,
           event.schema_version AS linked_spawn_schema_version,
           event.command_id AS linked_spawn_command_id,
           event.correlation_id AS linked_spawn_correlation_id,
           event.actor AS linked_spawn_actor,
           event.payload_hash AS linked_spawn_payload_hash,
           event.event_hash AS linked_spawn_event_hash,
           event.prev_event_hash AS linked_spawn_prev_event_hash,
           event.created_at AS linked_spawn_created_at,
           event.details_json AS linked_spawn_details_json
    FROM agent_process_instances AS process
    LEFT JOIN run_events AS event
      ON event.event_id = process.spawn_intent_event_id
"""


class AgentProcessInstanceStorageConflictError(WorkflowDesignRevisionConflictError):
    """Raised when a prepared process intent is forged, reused, or corrupt."""


def fetch_agent_process_instance_by_id_for_connection(
    connection: sqlite3.Connection,
    process_instance_id: str,
) -> dict[str, Any] | None:
    return _fetch_validated_process_row(
        connection,
        _PROCESS_ROW_PROJECTION + " WHERE process.process_instance_id = ?",
        (process_instance_id,),
    )


def fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection(
    connection: sqlite3.Connection,
    *,
    attempt_id: str,
    lease_generation: int,
    process_ordinal: int,
) -> dict[str, Any] | None:
    return _fetch_validated_process_row(
        connection,
        _PROCESS_ROW_PROJECTION
        + " WHERE process.attempt_id = ? AND process.lease_generation = ?"
        + " AND process.process_ordinal = ?",
        (attempt_id, lease_generation, process_ordinal),
    )


def insert_prepared_agent_process_instance_for_connection(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1 | Mapping[str, object],
) -> dict[str, Any]:
    """Insert exactly one prepared intent in the caller's open transaction."""

    if not connection.in_transaction:
        raise RuntimeError("AGENT_PROCESS_INSTANCE_WRITER_TRANSACTION_REQUIRED")
    normalized = _normalize_intent(intent)
    _require_durable_dependencies(connection, normalized)
    try:
        connection.execute(
            """
            INSERT INTO agent_process_instances (
                process_instance_id, contract_version, run_id, authorization_id,
                attempt_id, lease_generation, logical_activity_id,
                process_ordinal, process_kind, workspace_proof_id,
                tool_assets_hash, launch_spec_hash, gate_token_hash,
                spawn_intent_event_id, spawn_intent_event_hash, state,
                process_pid, process_group_id, process_incarnation_json,
                process_incarnation_hash, started_event_id, terminal_event_id,
                exit_code, exit_reason, prepared_at, started_at, finished_at,
                launch_intent_hash
            ) VALUES (
                :process_instance_id, :contract_version, :run_id,
                :authorization_id, :attempt_id, :lease_generation,
                :logical_activity_id, :process_ordinal, :process_kind,
                :workspace_proof_id, :tool_assets_hash, :launch_spec_hash,
                :gate_token_hash, :spawn_intent_event_id,
                :spawn_intent_event_hash, :state, :process_pid,
                :process_group_id, :process_incarnation_json,
                :process_incarnation_hash, :started_event_id,
                :terminal_event_id, :exit_code, :exit_reason, :prepared_at,
                :started_at, :finished_at, :launch_intent_hash
            )
            """,
            _insert_parameters(normalized),
        )
    except sqlite3.IntegrityError as exc:
        raise AgentProcessInstanceStorageConflictError(
            _integrity_conflict_code(connection, normalized)
        ) from exc
    return normalized.runtime_payload()


def _fetch_validated_process_row(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> dict[str, Any] | None:
    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute("BEGIN")
    try:
        row = connection.execute(query, parameters).fetchone()
        return _validated_process_row(connection, row)
    finally:
        if owns_snapshot:
            connection.rollback()


def _validated_process_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = agent_process_instance_row_to_dict(row)
    try:
        intent = build_agent_process_launch_intent_v1(payload)
        _require_durable_dependencies(connection, intent)
    except AgentProcessInstanceStorageConflictError:
        raise
    except Exception as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_DURABLE_BINDING_INVALID"
        ) from exc
    return payload


def _require_durable_dependencies(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
) -> None:
    try:
        proof = fetch_agent_workspace_proof_by_id_for_connection(
            connection,
            intent.workspaceProofId,
        )
    except Exception as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_WORKSPACE_PROOF_INVALID"
        ) from exc
    expected_boundary = "pre_dry_run" if intent.processKind == "dry_run" else "pre_run"
    expected_proof = {
        "workspaceProofId": intent.workspaceProofId,
        "runId": intent.runId,
        "authorizationId": intent.authorizationId,
        "attemptId": intent.attemptId,
        "leaseGeneration": intent.leaseGeneration,
        "processBoundary": expected_boundary,
        "processOrdinal": intent.processOrdinal,
        "toolAssetsHash": intent.toolAssetsHash,
        "eventId": intent.spawnIntentEventId,
    }
    if proof is None or any(
        proof.get(field) != value for field, value in expected_proof.items()
    ):
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_WORKSPACE_PROOF_MISMATCH"
        )
    if proof.get("createdAt") != intent.preparedAt:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_PREPARED_TIME_MISMATCH"
        )
    request_id, state_version = _require_durable_input_authority(
        connection,
        intent,
    )
    _require_production_spawn_event(
        connection,
        intent,
        request_id=request_id,
        state_version=state_version,
    )
    try:
        integrity = verify_run_event_hash_chain(
            connection,
            intent.runId,
            allow_legacy_unsequenced=False,
        )
    except Exception as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_EVENT_CHAIN_INVALID"
        ) from exc
    if integrity.get("valid") is not True:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_EVENT_CHAIN_INVALID"
        )


def _require_durable_input_authority(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
) -> tuple[str, int]:
    try:
        authorization = fetch_agent_run_authorization_by_id_for_connection(
            connection,
            intent.authorizationId,
        )
        run = connection.execute(
            "SELECT request_id, run_spec_json FROM runs WHERE run_id = ?",
            (intent.runId,),
        ).fetchone()
        if authorization is None or run is None:
            raise ValueError("AGENT_PROCESS_INSTANCE_INPUT_AUTHORITY_MISSING")
        run_spec = json.loads(str(run["run_spec_json"]))
        if (
            not isinstance(run_spec, dict)
            or authorization.get("runId") != intent.runId
            or agent_workflow_run_spec_hash(run_spec)
            != authorization.get("runSpecHash")
        ):
            raise ValueError("AGENT_PROCESS_INSTANCE_RUN_SPEC_MISMATCH")
        request_id = run["request_id"]
        if (
            not isinstance(request_id, str)
            or not request_id
            or request_id != request_id.strip()
            or "\x00" in request_id
        ):
            raise ValueError("AGENT_PROCESS_INSTANCE_RUN_AUTHORITY_INVALID")
        expectation = read_agent_run_input_expectation_for_connection(
            connection,
            binding=authorization,
            run_spec=run_spec,
        )
        materialization = (
            require_unique_agent_run_input_materialization_event_for_connection(
                connection,
                run_id=intent.runId,
                request_id=request_id,
                expectation=expectation,
            )
        )
    except Exception as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_INPUT_AUTHORITY_INVALID"
        ) from exc
    return request_id, int(materialization["eventProof"]["stateVersion"])


def _require_production_spawn_event(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
    *,
    request_id: str,
    state_version: int,
) -> None:
    row = connection.execute(
        "SELECT * FROM run_events WHERE event_id = ?",
        (intent.spawnIntentEventId,),
    ).fetchone()
    if row is None:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH"
        )
    if (
        RUN_EVENT_ID_PATTERN.fullmatch(str(row["event_id"])) is None
        or row["run_id"] != intent.runId
        or row["event_type"] != _SPAWN_EVENT_TYPE
        or row["schema_version"] != "run-event.v2"
        or row["from_status"] is not None
        or row["to_status"] is not None
        or row["stage"] != _SPAWN_EVENT_STAGE
        or row["state_version"] != state_version
        or row["message"] != _SPAWN_EVENT_MESSAGE
        or row["request_id"] != request_id
        or row["command_id"] is not None
        or row["correlation_id"] is not None
        or row["actor"] != _SPAWN_EVENT_ACTOR
        or row["created_at"] != intent.preparedAt
        or row["event_hash"] != intent.spawnIntentEventHash
    ):
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH"
        )


def agent_process_instance_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Reconstruct and verify a prepared launch intent and its spawn event."""

    try:
        _require_prepared_shape(row)
        payload: dict[str, object] = {
            "processInstanceId": row["process_instance_id"],
            "contractVersion": row["contract_version"],
            "runId": row["run_id"],
            "authorizationId": row["authorization_id"],
            "attemptId": row["attempt_id"],
            "leaseGeneration": row["lease_generation"],
            "logicalActivityId": row["logical_activity_id"],
            "processOrdinal": row["process_ordinal"],
            "processKind": row["process_kind"],
            "workspaceProofId": row["workspace_proof_id"],
            "toolAssetsHash": row["tool_assets_hash"],
            "launchSpecHash": row["launch_spec_hash"],
            "gateTokenHash": row["gate_token_hash"],
            "spawnIntentEventId": row["spawn_intent_event_id"],
            "spawnIntentEventHash": row["spawn_intent_event_hash"],
            "preparedAt": row["prepared_at"],
            "launchIntentHash": row["launch_intent_hash"],
        }
        normalized = build_agent_process_launch_intent_v1(payload)
        _require_spawn_event_binding(row, normalized)
    except AgentProcessInstanceStorageConflictError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_STORED_PAYLOAD_INVALID"
        ) from exc
    return normalized.runtime_payload()


def _normalize_intent(
    intent: AgentProcessLaunchIntentV1 | Mapping[str, object],
) -> AgentProcessLaunchIntentV1:
    try:
        payload = (
            intent.runtime_payload()
            if isinstance(intent, AgentProcessLaunchIntentV1)
            else intent
        )
        return build_agent_process_launch_intent_v1(payload)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_INTENT_INVALID"
        ) from exc


def _insert_parameters(intent: AgentProcessLaunchIntentV1) -> dict[str, object]:
    return {
        "process_instance_id": intent.processInstanceId,
        "contract_version": intent.contractVersion,
        "run_id": intent.runId,
        "authorization_id": intent.authorizationId,
        "attempt_id": intent.attemptId,
        "lease_generation": intent.leaseGeneration,
        "logical_activity_id": intent.logicalActivityId,
        "process_ordinal": intent.processOrdinal,
        "process_kind": intent.processKind,
        "workspace_proof_id": intent.workspaceProofId,
        "tool_assets_hash": intent.toolAssetsHash,
        "launch_spec_hash": intent.launchSpecHash,
        "gate_token_hash": intent.gateTokenHash,
        "spawn_intent_event_id": intent.spawnIntentEventId,
        "spawn_intent_event_hash": intent.spawnIntentEventHash,
        "state": "prepared",
        "process_pid": None,
        "process_group_id": None,
        "process_incarnation_json": None,
        "process_incarnation_hash": None,
        "started_event_id": None,
        "terminal_event_id": None,
        "exit_code": None,
        "exit_reason": None,
        "prepared_at": intent.preparedAt,
        "started_at": None,
        "finished_at": None,
        "launch_intent_hash": intent.launchIntentHash,
    }


def _require_prepared_shape(row: sqlite3.Row) -> None:
    if row["state"] != "prepared" or any(
        row[field] is not None for field in _PREPARED_NULL_FIELDS
    ):
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_STORED_PREPARED_SHAPE_INVALID"
        )


def _require_spawn_event_binding(
    row: sqlite3.Row,
    intent: AgentProcessLaunchIntentV1,
) -> None:
    expected_columns = {
        "linked_spawn_event_id": intent.spawnIntentEventId,
        "linked_spawn_run_id": intent.runId,
        "linked_spawn_event_type": "agent_process_spawn_intent_recorded",
        "linked_spawn_schema_version": "run-event.v2",
        "linked_spawn_event_hash": intent.spawnIntentEventHash,
    }
    if any(row[column] != value for column, value in expected_columns.items()):
        raise AgentProcessInstanceStorageConflictError(
            "AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH"
        )

    sequence = row["linked_spawn_sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_SEQUENCE_INVALID")
    details = json.loads(row["linked_spawn_details_json"])
    if not isinstance(details, dict):
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_DETAILS_INVALID")
    payload = details.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_PAYLOAD_INVALID")
    expected_details = {
        "schema_version": row["linked_spawn_schema_version"],
        "occurred_at": row["linked_spawn_created_at"],
        "sequence": sequence,
        "command_id": row["linked_spawn_command_id"],
        "correlation_id": row["linked_spawn_correlation_id"],
        "actor": row["linked_spawn_actor"],
        "payload_hash": row["linked_spawn_payload_hash"],
        "event_hash": row["linked_spawn_event_hash"],
        "prev_event_hash": row["linked_spawn_prev_event_hash"],
    }
    if any(details.get(key) != value for key, value in expected_details.items()):
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_DETAILS_MISMATCH")
    expected_payload = {
        "attemptId": intent.attemptId,
        "leaseGeneration": intent.leaseGeneration,
        "processKind": intent.processKind,
        "processOrdinal": intent.processOrdinal,
        "workspaceProofId": intent.workspaceProofId,
        "launchSpecHash": intent.launchSpecHash,
        "gateTokenHash": intent.gateTokenHash,
    }
    if payload != expected_payload:
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_PAYLOAD_MISMATCH")
    payload_hash = _sha256(_stable_json(payload))
    if not hmac.compare_digest(payload_hash, row["linked_spawn_payload_hash"]):
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_PAYLOAD_HASH_MISMATCH")
    event_hash = _sha256(
        _stable_json(
            {
                "actor": row["linked_spawn_actor"],
                "command_id": row["linked_spawn_command_id"],
                "correlation_id": row["linked_spawn_correlation_id"],
                "event_type": row["linked_spawn_event_type"],
                "occurred_at": row["linked_spawn_created_at"],
                "payload_hash": payload_hash,
                "prev_event_hash": row["linked_spawn_prev_event_hash"],
                "run_id": row["linked_spawn_run_id"],
                "schema_version": row["linked_spawn_schema_version"],
                "sequence": sequence,
            }
        )
    )
    if not hmac.compare_digest(event_hash, intent.spawnIntentEventHash):
        raise ValueError("AGENT_PROCESS_INSTANCE_SPAWN_EVENT_HASH_MISMATCH")


def _integrity_conflict_code(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
) -> str:
    if _row_exists(
        connection,
        "process_instance_id = ? OR launch_intent_hash = ?",
        (intent.processInstanceId, intent.launchIntentHash),
    ):
        return "AGENT_PROCESS_INSTANCE_ALREADY_PREPARED"
    if _row_exists(
        connection,
        "logical_activity_id = ?",
        (intent.logicalActivityId,),
    ):
        return "AGENT_PROCESS_INSTANCE_LOGICAL_ACTIVITY_CONFLICT"
    if _row_exists(
        connection,
        "attempt_id = ? AND lease_generation = ? AND process_ordinal = ?",
        (intent.attemptId, intent.leaseGeneration, intent.processOrdinal),
    ):
        return "AGENT_PROCESS_INSTANCE_ORDINAL_CONFLICT"
    if _row_exists(connection, "gate_token_hash = ?", (intent.gateTokenHash,)):
        return "AGENT_PROCESS_INSTANCE_GATE_TOKEN_CONFLICT"
    return "AGENT_PROCESS_INSTANCE_STORAGE_CONFLICT"


def _row_exists(
    connection: sqlite3.Connection,
    predicate: str,
    parameters: tuple[object, ...],
) -> bool:
    return (
        connection.execute(
            f"SELECT 1 FROM agent_process_instances WHERE {predicate} LIMIT 1",
            parameters,
        ).fetchone()
        is not None
    )


def _stable_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AgentProcessInstanceStorageConflictError",
    "agent_process_instance_row_to_dict",
    "fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection",
    "fetch_agent_process_instance_by_id_for_connection",
    "insert_prepared_agent_process_instance_for_connection",
]
