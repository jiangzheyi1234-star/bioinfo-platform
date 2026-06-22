from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage_core import get_connection, now_iso


def upsert_run_rule_state(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    rule_name: str,
    status: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None = None,
    step_id: str = "",
    runtime_status_key: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
    exit_code: int | None = None,
    message: str = "",
    command_summary: str = "",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    wildcards: dict[str, Any] | None = None,
    logs: list[str] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    timestamp = occurred_at or now_iso()
    with get_connection(cfg) as connection:
        _require_current_attempt(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        attempt_row = connection.execute(
            "SELECT attempt_number FROM run_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        resolved_attempt_number = (
            attempt_number
            if attempt_number is not None
            else (int(attempt_row["attempt_number"]) if attempt_row else None)
        )
        rule_id = _run_rule_id(run_id, rule_name, attempt_id, lease_generation)
        connection.execute(
            """
            INSERT INTO run_rules (
                run_rule_id, run_id, rule_name, step_id, runtime_status_key, status,
                attempt_id, lease_generation, attempt_number, started_at, finished_at, exit_code,
                message, command_summary, inputs_json, outputs_json, wildcards_json, logs_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, rule_name, attempt_id, lease_generation) DO UPDATE SET
                step_id = excluded.step_id,
                runtime_status_key = excluded.runtime_status_key,
                status = excluded.status,
                attempt_number = excluded.attempt_number,
                started_at = COALESCE(excluded.started_at, run_rules.started_at),
                finished_at = excluded.finished_at,
                exit_code = excluded.exit_code,
                message = excluded.message,
                command_summary = excluded.command_summary,
                inputs_json = excluded.inputs_json,
                outputs_json = excluded.outputs_json,
                wildcards_json = excluded.wildcards_json,
                logs_json = excluded.logs_json,
                updated_at = excluded.updated_at
            """,
            (
                rule_id,
                _required_text(run_id, "RUN_ID_REQUIRED"),
                _required_text(rule_name, "RULE_NAME_REQUIRED"),
                _optional_text(step_id) or "",
                _optional_text(runtime_status_key) or "",
                _required_text(status, "RULE_STATUS_REQUIRED"),
                _required_text(attempt_id, "ATTEMPT_ID_REQUIRED"),
                int(lease_generation),
                int(resolved_attempt_number) if resolved_attempt_number is not None else None,
                started_at,
                finished_at,
                exit_code,
                str(message or ""),
                str(command_summary or ""),
                _json_list(inputs or []),
                _json_list(outputs or []),
                _json_object(wildcards or {}),
                _json_list(logs or []),
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM run_rules WHERE run_rule_id = ?", (rule_id,)).fetchone()
        connection.commit()
    return _rule_row_to_dict(row, []) if row is not None else {}


def append_run_rule_event(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    rule_name: str,
    event_type: str,
    status: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None = None,
    step_id: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    timestamp = occurred_at or now_iso()
    with get_connection(cfg) as connection:
        _require_current_attempt(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        rule_id = _run_rule_id(run_id, rule_name, attempt_id, lease_generation)
        row = connection.execute(
            "SELECT attempt_number FROM run_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        resolved_attempt_number = attempt_number if attempt_number is not None else (int(row["attempt_number"]) if row else None)
        event_id = f"rre_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO run_rule_events (
                rule_event_id, run_id, run_rule_id, rule_name, step_id, event_type,
                status, attempt_id, lease_generation, attempt_number, message, created_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                _required_text(run_id, "RUN_ID_REQUIRED"),
                rule_id,
                _required_text(rule_name, "RULE_NAME_REQUIRED"),
                _optional_text(step_id) or "",
                _required_text(event_type, "RULE_EVENT_TYPE_REQUIRED"),
                _required_text(status, "RULE_STATUS_REQUIRED"),
                _required_text(attempt_id, "ATTEMPT_ID_REQUIRED"),
                int(lease_generation),
                int(resolved_attempt_number) if resolved_attempt_number is not None else 0,
                str(message or ""),
                timestamp,
                _json_object(details or {}),
            ),
        )
        connection.commit()
    return {
        "ruleEventId": event_id,
        "runId": run_id,
        "ruleName": rule_name,
        "eventType": event_type,
        "status": status,
        "attemptId": attempt_id,
        "leaseGeneration": int(lease_generation),
        "createdAt": timestamp,
    }


def fetch_run_rules(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise RemoteRunnerNotFoundError("RUN_NOT_FOUND")
        rule_rows = connection.execute(
            """
            SELECT *
            FROM run_rules
            WHERE run_id = ?
            ORDER BY COALESCE(started_at, updated_at) ASC, rule_name ASC
            """,
            (run_id,),
        ).fetchall()
        event_rows = connection.execute(
            """
            SELECT *
            FROM run_rule_events
            WHERE run_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (run_id,),
        ).fetchall()
    events_by_rule = _events_by_rule(event_rows)
    return {
        "runId": run_id,
        "items": [_rule_row_to_dict(row, events_by_rule.get(str(row["run_rule_id"]), [])) for row in rule_rows],
    }


def _events_by_rule(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["run_rule_id"]), []).append(_event_row_to_dict(row))
    return grouped


def _rule_row_to_dict(row: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runRuleId": row["run_rule_id"],
        "runId": row["run_id"],
        "ruleName": row["rule_name"],
        "stepId": row["step_id"],
        "runtimeStatusKey": row["runtime_status_key"],
        "status": row["status"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": row["lease_generation"],
        "attemptNumber": row["attempt_number"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "exitCode": row["exit_code"],
        "message": row["message"],
        "commandSummary": row["command_summary"],
        "inputs": _loads_json(row["inputs_json"], []),
        "outputs": _loads_json(row["outputs_json"], []),
        "wildcards": _loads_json(row["wildcards_json"], {}),
        "logs": _loads_json(row["logs_json"], []),
        "updatedAt": row["updated_at"],
        "events": events,
    }


def _event_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "ruleEventId": row["rule_event_id"],
        "runId": row["run_id"],
        "runRuleId": row["run_rule_id"],
        "ruleName": row["rule_name"],
        "stepId": row["step_id"],
        "eventType": row["event_type"],
        "status": row["status"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": row["lease_generation"],
        "attemptNumber": row["attempt_number"],
        "message": row["message"],
        "createdAt": row["created_at"],
        "details": _loads_json(row["details_json"], {}),
    }


def _require_current_attempt(
    connection: Any,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> None:
    lease = connection.execute(
        "SELECT attempt_id, lease_generation, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if (
        lease is None
        or lease["attempt_id"] != attempt_id
        or int(lease["lease_generation"]) != int(lease_generation)
        or lease["state"] != "active"
    ):
        raise RuntimeError("RUN_RULE_EVENT_STALE_ATTEMPT")


def _run_rule_id(run_id: str, rule_name: str, attempt_id: str, lease_generation: int) -> str:
    source = f"{run_id}:{rule_name}:{attempt_id}:{int(lease_generation)}".encode("utf-8")
    return f"rr_{hashlib.sha256(source).hexdigest()[:16]}"


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _json_list(value: list[Any]) -> str:
    return json.dumps(value if isinstance(value, list) else [], sort_keys=True, separators=(",", ":"))


def _json_object(value: dict[str, Any]) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, sort_keys=True, separators=(",", ":"))


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, type(default)) else default
