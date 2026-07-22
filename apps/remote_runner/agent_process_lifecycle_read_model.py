"""Strict read model and replay checks for Agent process lifecycles."""

from __future__ import annotations

import hmac
import json
import sqlite3
from collections.abc import Mapping
from typing import Any, Literal, NoReturn

from core.contracts.agent_process_instance import (
    AgentProcessLaunchIntentV1,
    build_agent_process_launch_intent_v1,
)
from core.contracts.agent_process_lifecycle import (
    WINDOWS_PROCESS_INCARNATION_SCHEMA,
    agent_process_incarnation_hash,
    require_agent_process_incarnation,
)
from core.contracts.linux_process_incarnation import (
    LINUX_PROCESS_INCARNATION_SCHEMA,
)

from .agent_process_lifecycle_reasons import (
    agent_process_lifecycle_reason_is_allowed,
)
from .errors import WorkflowDesignRevisionConflictError
from .event_contracts import RUN_EVENT_ID_PATTERN, verify_run_event_hash_chain


AGENT_PROCESS_LIFECYCLE_ACTOR = "remote-runner"
AGENT_PROCESS_LIFECYCLE_STAGE = "agent_process"
AGENT_PROCESS_LIFECYCLE_EVENT_MESSAGES = {
    "agent_process_spawn_intent_recorded": "Agent process launch intent prepared.",
    "agent_process_started": "Agent process started after authorization commit.",
    "agent_process_spawn_failed": "Agent process spawn failed before start.",
    "agent_process_exited": "Agent process exited and was reaped.",
    "agent_process_terminated": "Agent process termination confirmed.",
    "agent_process_lost": "Agent process identity lost.",
}
AgentProcessPlatform = Literal["linux", "windows"]

_PROCESS_PLATFORM_BY_INCARNATION_SCHEMA: dict[str, AgentProcessPlatform] = {
    LINUX_PROCESS_INCARNATION_SCHEMA: "linux",
    WINDOWS_PROCESS_INCARNATION_SCHEMA: "windows",
}


class AgentProcessLifecycleStorageConflictError(WorkflowDesignRevisionConflictError):
    """Raised when a lifecycle transition is stale, forged, or corrupt."""


def fetch_agent_process_lifecycle_for_connection(
    connection: sqlite3.Connection,
    process_instance_id: str,
) -> dict[str, Any] | None:
    """Return a strict lifecycle read model without requiring a live lease."""

    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute("BEGIN")
    try:
        row = connection.execute(
            "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
            (process_instance_id,),
        ).fetchone()
        return (
            None
            if row is None
            else validated_agent_process_lifecycle_read_model(connection, row)
        )
    finally:
        if owns_snapshot:
            connection.rollback()


def validated_agent_process_lifecycle_read_model(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    """Verify all immutable fields, lifecycle shape, and bound events."""

    try:
        intent = _intent_from_row(row)
        require_valid_agent_process_event_chain(connection, intent.runId)
        spawn = _require_bound_event(
            connection,
            row=row,
            event_id=intent.spawnIntentEventId,
            event_hash=intent.spawnIntentEventHash,
            event_type="agent_process_spawn_intent_recorded",
            occurred_at=intent.preparedAt,
            payload={
                "attemptId": intent.attemptId,
                "gateTokenHash": intent.gateTokenHash,
                "launchSpecHash": intent.launchSpecHash,
                "leaseGeneration": intent.leaseGeneration,
                "processKind": intent.processKind,
                "processOrdinal": intent.processOrdinal,
                "workspaceProofId": intent.workspaceProofId,
            },
        )
        model: dict[str, Any] = {
            **intent.runtime_payload(),
            "state": str(row["state"]),
            "processPid": row["process_pid"],
            "processGroupId": row["process_group_id"],
            "processPlatform": None,
            "processIncarnation": None,
            "processIncarnationHash": row["process_incarnation_hash"],
            "startedEventId": row["started_event_id"],
            "startedEventHash": None,
            "terminalEventId": row["terminal_event_id"],
            "terminalEventHash": None,
            "exitCode": row["exit_code"],
            "exitReason": row["exit_reason"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "terminalEvidenceHash": None,
        }
        state = model["state"]
        if state == "prepared":
            if row["process_incarnation_json"] is not None:
                raise ValueError
            _require_null_lifecycle_shape(model)
            return model
        if state == "spawn_failed":
            if row["process_incarnation_json"] is not None:
                raise ValueError
            _require_spawn_failed_shape(model)
            terminal = _require_bound_event(
                connection,
                row=row,
                event_id=str(model["terminalEventId"]),
                event_hash=None,
                event_type="agent_process_spawn_failed",
                occurred_at=str(model["finishedAt"]),
                payload={
                    **agent_process_lifecycle_common_payload(row),
                    "failureCode": model["exitReason"],
                    "launchSpecHash": intent.launchSpecHash,
                    "priorProcessEventHash": spawn["eventHash"],
                    "priorProcessEventId": spawn["eventId"],
                },
            )
            model["terminalEventHash"] = terminal["eventHash"]
            return model

        incarnation, _, incarnation_hash, process_platform = _stored_incarnation(row)
        model["processPlatform"] = process_platform
        model["processIncarnation"] = incarnation
        _require_started_identity_shape(model)
        if model["processIncarnationHash"] != incarnation_hash:
            raise ValueError
        started = _require_bound_event(
            connection,
            row=row,
            event_id=str(model["startedEventId"]),
            event_hash=None,
            event_type="agent_process_started",
            occurred_at=str(model["startedAt"]),
            payload={
                **agent_process_lifecycle_common_payload(row),
                "launchSpecHash": intent.launchSpecHash,
                "priorProcessEventHash": spawn["eventHash"],
                "priorProcessEventId": spawn["eventId"],
                "processGroupId": model["processGroupId"],
                "processIncarnationHash": incarnation_hash,
                "processPid": model["processPid"],
            },
        )
        model["startedEventHash"] = started["eventHash"]
        if state == "started":
            if any(
                model[field] is not None
                for field in (
                    "terminalEventId",
                    "exitCode",
                    "exitReason",
                    "finishedAt",
                )
            ):
                raise ValueError
            return model
        if state not in {"exited", "terminated", "lost"}:
            raise ValueError
        _require_terminal_shape(model)
        payload: dict[str, object] = {
            **agent_process_lifecycle_common_payload(row),
            "exitReason": model["exitReason"],
            "launchSpecHash": intent.launchSpecHash,
            "priorProcessEventHash": started["eventHash"],
            "priorProcessEventId": started["eventId"],
            "processIncarnationHash": incarnation_hash,
        }
        if state == "exited":
            payload["exitCode"] = model["exitCode"]
        terminal = _require_bound_event(
            connection,
            row=row,
            event_id=str(model["terminalEventId"]),
            event_hash=None,
            event_type=f"agent_process_{state}",
            occurred_at=str(model["finishedAt"]),
            payload=payload if state == "exited" else None,
        )
        if state != "exited":
            event_payload = terminal["payload"]
            evidence_hash = event_payload.get("evidenceHash")
            if not _is_sha256(evidence_hash):
                raise ValueError
            payload["evidenceHash"] = evidence_hash
            if event_payload != payload:
                raise ValueError
            model["terminalEvidenceHash"] = evidence_hash
        model["terminalEventHash"] = terminal["eventHash"]
        return model
    except AgentProcessLifecycleStorageConflictError:
        raise
    except Exception as exc:
        raise AgentProcessLifecycleStorageConflictError(
            "AGENT_PROCESS_LIFECYCLE_STORED_PAYLOAD_INVALID"
        ) from exc


def normalize_agent_process_incarnation(
    payload: object,
    *,
    expected_pid: object,
    expected_platform: object,
) -> tuple[dict[str, object], str, str]:
    """Normalize real OS evidence for one explicitly selected platform.

    Synthetic evidence is intentionally accepted by the shared core contract for
    isolated contract tests, but is never valid in this production lifecycle
    ledger.
    """

    try:
        platform = require_agent_process_platform(expected_platform)
        normalized = require_agent_process_incarnation(payload)
        if (
            normalized.get("pid") != _positive_integer(expected_pid)
            or _process_platform_for_incarnation(normalized) != platform
        ):
            raise ValueError
        canonical = stable_agent_process_json(normalized)
        digest = agent_process_incarnation_hash(normalized)
        return normalized, canonical, digest
    except AgentProcessLifecycleStorageConflictError:
        raise
    except Exception as exc:
        raise AgentProcessLifecycleStorageConflictError(
            "AGENT_PROCESS_INCARNATION_INVALID"
        ) from exc


def require_agent_process_started_replay(
    model: Mapping[str, object],
    *,
    process_pid: int,
    process_group_id: int,
    process_platform: AgentProcessPlatform,
    process_incarnation: Mapping[str, object],
    process_incarnation_hash: str,
) -> None:
    if (
        model.get("processPid") != process_pid
        or model.get("processGroupId") != process_group_id
        or model.get("processPlatform") != process_platform
    ):
        agent_process_lifecycle_conflict("AGENT_PROCESS_LIFECYCLE_REPLAY_CONFLICT")
    require_agent_process_exact_incarnation(
        model,
        process_incarnation,
        process_incarnation_hash,
    )


def require_agent_process_terminal_replay(
    model: Mapping[str, object],
    *,
    terminal_state: str,
    process_incarnation: Mapping[str, object],
    process_incarnation_hash: str,
    exit_code: int | None,
    exit_reason: str,
    evidence_hash: str | None,
) -> None:
    require_agent_process_exact_incarnation(
        model,
        process_incarnation,
        process_incarnation_hash,
    )
    if (
        model.get("state") != terminal_state
        or model.get("exitCode") != exit_code
        or model.get("exitReason") != exit_reason
        or model.get("terminalEvidenceHash") != evidence_hash
    ):
        agent_process_lifecycle_conflict("AGENT_PROCESS_LIFECYCLE_REPLAY_CONFLICT")


def require_agent_process_exact_incarnation(
    model: Mapping[str, object],
    incarnation: Mapping[str, object],
    incarnation_hash: str,
) -> None:
    stored_hash = model.get("processIncarnationHash")
    try:
        process_platform = _process_platform_for_incarnation(incarnation)
    except ValueError:
        agent_process_lifecycle_conflict("AGENT_PROCESS_INCARNATION_MISMATCH")
    if (
        not isinstance(stored_hash, str)
        or not hmac.compare_digest(stored_hash, incarnation_hash)
        or model.get("processIncarnation") != dict(incarnation)
        or model.get("processPlatform") != process_platform
    ):
        agent_process_lifecycle_conflict("AGENT_PROCESS_INCARNATION_MISMATCH")


def build_agent_process_lifecycle_transition_result(
    connection: sqlite3.Connection,
    model: Mapping[str, object],
    *,
    transaction_applied: bool,
) -> dict[str, Any]:
    """Return the transition observed inside the caller-owned transaction.

    ``transactionApplied`` only says this connection changed the row in its
    currently uncommitted transaction. It is not durable and is never permission
    to release a gated OS process. Use the commit-owning start wrapper for that.
    """

    event_id = (
        model.get("startedEventId")
        if model.get("state") == "started"
        else model.get("terminalEventId")
    )
    event = connection.execute(
        "SELECT event_id, event_hash, event_type, created_at, details_json "
        "FROM run_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if event is None:
        agent_process_lifecycle_conflict("AGENT_PROCESS_LIFECYCLE_EVENT_MISSING")
    details = json.loads(str(event["details_json"]))
    return {
        "transactionApplied": transaction_applied,
        "event": {
            "eventHash": str(event["event_hash"]),
            "eventId": str(event["event_id"]),
            "eventType": str(event["event_type"]),
            "occurredAt": str(event["created_at"]),
            "payload": dict(details["payload"]),
        },
        "process": dict(model),
    }


def agent_process_lifecycle_common_payload(
    row: sqlite3.Row,
) -> dict[str, object]:
    return {
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "processInstanceId": row["process_instance_id"],
        "processKind": row["process_kind"],
        "processOrdinal": int(row["process_ordinal"]),
    }


def require_valid_agent_process_event_chain(
    connection: sqlite3.Connection,
    run_id: str,
) -> None:
    integrity = verify_run_event_hash_chain(
        connection,
        run_id,
        allow_legacy_unsequenced=False,
    )
    if integrity.get("valid") is not True:
        agent_process_lifecycle_conflict("AGENT_PROCESS_EVENT_CHAIN_INVALID")


def stable_agent_process_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def agent_process_lifecycle_conflict(code: str) -> NoReturn:
    raise AgentProcessLifecycleStorageConflictError(code) from None


def _require_bound_event(
    connection: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    event_id: str,
    event_hash: str | None,
    event_type: str,
    occurred_at: str,
    payload: Mapping[str, object] | None,
) -> dict[str, Any]:
    event = connection.execute(
        "SELECT * FROM run_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if event is None:
        raise ValueError
    details = json.loads(str(event["details_json"]))
    observed_payload = details.get("payload") if isinstance(details, dict) else None
    run = connection.execute(
        "SELECT request_id FROM runs WHERE run_id = ?",
        (row["run_id"],),
    ).fetchone()
    if (
        RUN_EVENT_ID_PATTERN.fullmatch(str(event["event_id"])) is None
        or event["run_id"] != row["run_id"]
        or event["event_type"] != event_type
        or event["schema_version"] != "run-event.v2"
        or event["stage"] != AGENT_PROCESS_LIFECYCLE_STAGE
        or event["message"] != AGENT_PROCESS_LIFECYCLE_EVENT_MESSAGES[event_type]
        or event["actor"] != AGENT_PROCESS_LIFECYCLE_ACTOR
        or event["from_status"] is not None
        or event["to_status"] is not None
        or event["command_id"] is not None
        or event["correlation_id"] is not None
        or event["created_at"] != occurred_at
        or run is None
        or event["request_id"] != run["request_id"]
        or (event_hash is not None and event["event_hash"] != event_hash)
        or not isinstance(observed_payload, dict)
        or (payload is not None and observed_payload != dict(payload))
    ):
        raise ValueError
    return {
        "eventHash": str(event["event_hash"]),
        "eventId": str(event["event_id"]),
        "eventType": str(event["event_type"]),
        "occurredAt": str(event["created_at"]),
        "payload": dict(observed_payload),
    }


def _intent_from_row(row: sqlite3.Row) -> AgentProcessLaunchIntentV1:
    return build_agent_process_launch_intent_v1(
        {
            "attemptId": row["attempt_id"],
            "authorizationId": row["authorization_id"],
            "contractVersion": row["contract_version"],
            "gateTokenHash": row["gate_token_hash"],
            "launchIntentHash": row["launch_intent_hash"],
            "launchSpecHash": row["launch_spec_hash"],
            "leaseGeneration": row["lease_generation"],
            "logicalActivityId": row["logical_activity_id"],
            "preparedAt": row["prepared_at"],
            "processInstanceId": row["process_instance_id"],
            "processKind": row["process_kind"],
            "processOrdinal": row["process_ordinal"],
            "runId": row["run_id"],
            "spawnIntentEventHash": row["spawn_intent_event_hash"],
            "spawnIntentEventId": row["spawn_intent_event_id"],
            "toolAssetsHash": row["tool_assets_hash"],
            "workspaceProofId": row["workspace_proof_id"],
        }
    )


def _stored_incarnation(
    row: sqlite3.Row,
) -> tuple[dict[str, object], str, str, AgentProcessPlatform]:
    raw = row["process_incarnation_json"]
    if not isinstance(raw, str):
        raise ValueError
    payload = json.loads(raw)
    platform = _process_platform_for_incarnation(payload)
    normalized, canonical, digest = normalize_agent_process_incarnation(
        payload,
        expected_pid=row["process_pid"],
        expected_platform=platform,
    )
    if raw != canonical:
        raise ValueError
    stored_hash = row["process_incarnation_hash"]
    if not isinstance(stored_hash, str) or not hmac.compare_digest(
        stored_hash,
        digest,
    ):
        raise ValueError
    return normalized, canonical, digest, platform


def _require_null_lifecycle_shape(model: Mapping[str, object]) -> None:
    fields = (
        "processPid",
        "processGroupId",
        "processPlatform",
        "processIncarnationHash",
        "startedEventId",
        "terminalEventId",
        "exitCode",
        "exitReason",
        "startedAt",
        "finishedAt",
    )
    if any(model.get(field) is not None for field in fields):
        raise ValueError


def _require_spawn_failed_shape(model: Mapping[str, object]) -> None:
    if (
        any(
            model.get(field) is not None
            for field in (
                "processPid",
                "processGroupId",
                "processPlatform",
                "processIncarnationHash",
                "startedEventId",
                "startedAt",
                "exitCode",
            )
        )
        or not model.get("terminalEventId")
        or not agent_process_lifecycle_reason_is_allowed(
            "spawn_failed",
            model.get("exitReason"),
        )
        or not model.get("finishedAt")
    ):
        raise ValueError


def _require_started_identity_shape(model: Mapping[str, object]) -> None:
    if (
        not _is_positive_integer(model.get("processPid"))
        or not _is_positive_integer(model.get("processGroupId"))
        or model.get("processGroupId") != model.get("processPid")
        or model.get("processPlatform")
        not in _PROCESS_PLATFORM_BY_INCARNATION_SCHEMA.values()
        or not model.get("processIncarnationHash")
        or not model.get("startedEventId")
        or not model.get("startedAt")
    ):
        raise ValueError


def _require_terminal_shape(model: Mapping[str, object]) -> None:
    if (
        not model.get("startedEventId")
        or not model.get("terminalEventId")
        or not agent_process_lifecycle_reason_is_allowed(
            model.get("state"),
            model.get("exitReason"),
        )
        or not model.get("finishedAt")
        or (model.get("state") == "exited") != (model.get("exitCode") is not None)
    ):
        raise ValueError


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError
    return value


def require_agent_process_platform(value: object) -> AgentProcessPlatform:
    if value == "linux" or value == "windows":
        return value
    raise ValueError("AGENT_PROCESS_PLATFORM_INVALID")


def _process_platform_for_incarnation(
    incarnation: Mapping[str, object],
) -> AgentProcessPlatform:
    schema = incarnation.get("schemaVersion")
    if not isinstance(schema, str):
        raise ValueError("AGENT_PROCESS_INCARNATION_SCHEMA_INVALID")
    try:
        return _PROCESS_PLATFORM_BY_INCARNATION_SCHEMA[schema]
    except KeyError as exc:
        raise ValueError("AGENT_PROCESS_INCARNATION_PLATFORM_INVALID") from exc


def _is_positive_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "AGENT_PROCESS_LIFECYCLE_ACTOR",
    "AGENT_PROCESS_LIFECYCLE_EVENT_MESSAGES",
    "AGENT_PROCESS_LIFECYCLE_STAGE",
    "AgentProcessPlatform",
    "AgentProcessLifecycleStorageConflictError",
    "agent_process_lifecycle_common_payload",
    "agent_process_lifecycle_conflict",
    "build_agent_process_lifecycle_transition_result",
    "fetch_agent_process_lifecycle_for_connection",
    "normalize_agent_process_incarnation",
    "require_agent_process_platform",
    "require_agent_process_exact_incarnation",
    "require_agent_process_started_replay",
    "require_agent_process_terminal_replay",
    "require_valid_agent_process_event_chain",
    "stable_agent_process_json",
    "validated_agent_process_lifecycle_read_model",
]
