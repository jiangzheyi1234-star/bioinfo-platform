from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from apps.remote_runner.event_contracts import append_run_event_v2


TIMESTAMP = "2099-01-01T00:00:00Z"


def connection(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def downgrade_process_schema(path: Path) -> None:
    with connection(path) as db:
        db.execute(
            "DROP TRIGGER IF EXISTS agent_process_instances_run_events_no_update"
        )
        db.execute(
            "DROP TRIGGER IF EXISTS agent_process_instances_run_events_no_delete"
        )
        db.execute("DROP TABLE IF EXISTS agent_process_instances")
        db.execute("DELETE FROM schema_migrations WHERE version IN (21, 22)")
        db.execute("PRAGMA user_version = 20")


def record_migration(db: sqlite3.Connection, version: int, name: str) -> None:
    db.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (?, ?, 'test-checksum', ?)",
        (version, name, TIMESTAMP),
    )


def foreign_keys(db: sqlite3.Connection) -> set[tuple[str, ...]]:
    return {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in db.execute("PRAGMA foreign_key_list(agent_process_instances)")
    }


def unique_column_sets(db: sqlite3.Connection) -> set[tuple[str, ...]]:
    return {
        tuple(
            str(column[2])
            for column in db.execute(f'PRAGMA index_info("{str(index[1])}")')
        )
        for index in db.execute("PRAGMA index_list(agent_process_instances)")
        if int(index[2]) == 1 and str(index[3]) == "u"
    }


def seed_intent(
    db: sqlite3.Connection,
    *,
    tag: str,
    process_kind: str = "dry_run",
    process_ordinal: int = 1,
    proof_boundary: str = "pre_dry_run",
    gate_token_hash: str | None = None,
) -> dict[str, str | int]:
    values: dict[str, str | int] = {
        "tag": tag,
        "session_id": f"session_{tag}",
        "plan_id": f"plan_{tag}",
        "revision_id": f"revision_{tag}",
        "run_id": f"run_{tag}",
        "authorization_id": f"authorization_{tag}",
        "attempt_id": f"attempt_{tag}",
        "workspace_proof_id": f"proof_{tag}",
        "process_instance_id": f"process_{tag}",
        "process_kind": process_kind,
        "process_ordinal": process_ordinal,
        "proof_boundary": proof_boundary,
        "tool_assets_hash": digest(f"tool-assets-{tag}"),
        "launch_spec_hash": digest(f"launch-spec-{tag}"),
        "gate_token_hash": gate_token_hash or digest(f"gate-token-{tag}"),
        "launch_intent_hash": digest(f"launch-intent-{tag}"),
    }
    _insert_authority_parents(db, values)
    spawn = append_process_event(
        db,
        values,
        event_type="agent_process_spawn_intent_recorded",
        payload=spawn_payload(values),
    )
    values["spawn_event_id"] = str(spawn["eventId"])
    values["spawn_event_hash"] = str(spawn["event_hash"])
    _insert_workspace_proof(db, values)
    return values


def append_process_event(
    db: sqlite3.Connection,
    intent: dict[str, str | int],
    *,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    is_spawn = event_type == "agent_process_spawn_intent_recorded"
    return append_run_event_v2(
        db,
        run_id=str(intent["run_id"]),
        event_type=event_type,
        stage="agent_process" if is_spawn else "process",
        state_version=2,
        message="Agent process launch intent prepared." if is_spawn else event_type,
        request_id=(
            f"run_request_{intent['tag']}"
            if is_spawn
            else f"request_{intent['tag']}_{event_type}"
        ),
        payload=payload or lifecycle_payload(intent),
        occurred_at=TIMESTAMP,
        actor="remote-runner" if is_spawn else None,
    )


def spawn_payload(intent: dict[str, str | int]) -> dict[str, object]:
    return {
        "attemptId": intent["attempt_id"],
        "leaseGeneration": 1,
        "processKind": intent["process_kind"],
        "processOrdinal": intent["process_ordinal"],
        "workspaceProofId": intent["workspace_proof_id"],
        "launchSpecHash": intent["launch_spec_hash"],
        "gateTokenHash": intent["gate_token_hash"],
    }


def lifecycle_payload(intent: dict[str, str | int]) -> dict[str, object]:
    return {
        "processInstanceId": intent["process_instance_id"],
        "attemptId": intent["attempt_id"],
        "leaseGeneration": 1,
        "processKind": intent["process_kind"],
        "processOrdinal": intent["process_ordinal"],
    }


def insert_prepared(
    db: sqlite3.Connection,
    intent: dict[str, str | int],
    **overrides: object,
) -> None:
    values: dict[str, object] = {
        "process_instance_id": intent["process_instance_id"],
        "run_id": intent["run_id"],
        "authorization_id": intent["authorization_id"],
        "attempt_id": intent["attempt_id"],
        "logical_activity_id": f"activity_{intent['tag']}",
        "process_ordinal": intent["process_ordinal"],
        "process_kind": intent["process_kind"],
        "workspace_proof_id": intent["workspace_proof_id"],
        "tool_assets_hash": intent["tool_assets_hash"],
        "launch_spec_hash": intent["launch_spec_hash"],
        "gate_token_hash": intent["gate_token_hash"],
        "spawn_event_id": intent["spawn_event_id"],
        "spawn_event_hash": intent["spawn_event_hash"],
        "process_pid": None,
        "prepared_at": TIMESTAMP,
        "launch_intent_hash": intent["launch_intent_hash"],
    }
    values.update(overrides)
    db.execute(
        """
        INSERT INTO agent_process_instances (
            process_instance_id, contract_version, run_id, authorization_id,
            attempt_id, lease_generation, logical_activity_id, process_ordinal,
            process_kind, workspace_proof_id, tool_assets_hash, launch_spec_hash,
            gate_token_hash, spawn_intent_event_id, spawn_intent_event_hash,
            state, process_pid, prepared_at, launch_intent_hash
        ) VALUES (?, 'agent-process-launch-intent.v1', ?, ?, ?, 1, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, 'prepared', ?, ?, ?)
        """,
        tuple(
            values[key]
            for key in (
                "process_instance_id",
                "run_id",
                "authorization_id",
                "attempt_id",
                "logical_activity_id",
                "process_ordinal",
                "process_kind",
                "workspace_proof_id",
                "tool_assets_hash",
                "launch_spec_hash",
                "gate_token_hash",
                "spawn_event_id",
                "spawn_event_hash",
                "process_pid",
                "prepared_at",
                "launch_intent_hash",
            )
        ),
    )


def start(
    db: sqlite3.Connection,
    intent: dict[str, str | int],
    *,
    event: dict[str, object] | None = None,
    incarnation_json: object = '{"pid":4242}',
    incarnation_hash: object | None = None,
) -> dict[str, object]:
    started = event or append_process_event(
        db, intent, event_type="agent_process_started"
    )
    db.execute(
        """
        UPDATE agent_process_instances
        SET state = 'started', process_pid = 4242, process_group_id = 4242,
            process_incarnation_json = ?, process_incarnation_hash = ?,
            started_event_id = ?, started_at = ?
        WHERE process_instance_id = ?
        """,
        (
            incarnation_json,
            incarnation_hash or digest(f"incarnation-{intent['tag']}"),
            started["eventId"],
            TIMESTAMP,
            intent["process_instance_id"],
        ),
    )
    return started


def finish(
    db: sqlite3.Connection,
    intent: dict[str, str | int],
    *,
    state: str,
    event: dict[str, object] | None = None,
) -> dict[str, object]:
    terminal = event or append_process_event(
        db, intent, event_type=f"agent_process_{state}"
    )
    exit_code = 0 if state == "exited" else None
    db.execute(
        """
        UPDATE agent_process_instances
        SET state = ?, terminal_event_id = ?, exit_code = ?,
            exit_reason = ?, finished_at = ?
        WHERE process_instance_id = ?
        """,
        (
            state,
            terminal["eventId"],
            exit_code,
            state,
            TIMESTAMP,
            intent["process_instance_id"],
        ),
    )
    return terminal


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _insert_authority_parents(
    db: sqlite3.Connection,
    values: dict[str, str | int],
) -> None:
    db.execute(
        "INSERT INTO workflow_revisions (workflow_revision_id, content_hash, "
        "manifest_json, graph_snapshot_json, runtime_lock_json, compiler_json, "
        "created_by, created_at) VALUES (?, ?, '{}', '{}', '{}', '{}', 'test', ?)",
        (values["revision_id"], digest(f"revision-content-{values['tag']}"), TIMESTAMP),
    )
    db.execute(
        """
        INSERT INTO agent_sessions (
            session_id, contract_version, project_id, goal_json, constraints_json,
            budget_json, status, state_version, plan_generation, active_plan_hash,
            workflow_revision_id, creation_request_id, creation_request_hash,
            created_by, created_at, updated_at
        ) VALUES (?, 'agent-session.v1', 'project', '{}', '{}', '{}',
            'ready_to_run', 4, 1, ?, ?, ?, ?, 'test', ?, ?)
        """,
        (
            values["session_id"],
            digest("plan"),
            values["revision_id"],
            f"request_{values['tag']}",
            digest(f"request-{values['tag']}"),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    db.execute(
        """
        INSERT INTO agent_plan_revisions (
            plan_revision_id, contract_version, session_id, plan_generation,
            draft_id, draft_revision, plan_hash, proposal_json, validation_json,
            budget_json, created_by, created_at
        ) VALUES (?, 'agent-plan-revision.v1', ?, 1, ?, 1, ?, '{}', '{}', '{}',
            'test', ?)
        """,
        (
            values["plan_id"],
            values["session_id"],
            f"draft_{values['tag']}",
            digest("plan"),
            TIMESTAMP,
        ),
    )
    db.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version,
            run_spec_version, workflow_revision_id, status, stage, state_version,
            message, result_dir, last_updated_at, request_id, submitted_at,
            run_spec_json
        ) VALUES (?, 'agent-control-plane.v1', 'project', 'generated-tool-run-v1',
            '1.0.0', '2026-04-21', ?, 'running', 'running', 2, 'running', '',
            ?, ?, ?, '{}')
        """,
        (
            values["run_id"],
            values["revision_id"],
            TIMESTAMP,
            f"run_request_{values['tag']}",
            TIMESTAMP,
        ),
    )
    db.execute(
        """
        INSERT INTO agent_run_authorizations (
            authorization_id, contract_version, session_id, preview_hash,
            plan_revision_id, plan_generation, plan_hash, workflow_revision_id,
            expected_state_version, input_manifest_digest, run_spec_hash,
            execution_policy_id, execution_policy_hash, runtime_lock_hash,
            runtime_proof_hash, effect_budget_hash, run_id, scope, confirmation,
            actor, request_id, idempotency_key, command_hash, receipt_hash, created_at
        ) VALUES (?, 'agent-run-authorization.v1', ?, ?, ?, 1, ?, ?, 4, ?, ?,
            'policy-v1', ?, ?, ?, ?, ?, 'submit_workflow_run',
            'authorize-workflow-run', 'test', ?, ?, ?, ?, ?)
        """,
        (
            values["authorization_id"],
            values["session_id"],
            digest(f"preview-{values['tag']}"),
            values["plan_id"],
            digest("plan"),
            values["revision_id"],
            f"sha256:{digest(f'input-{values["tag"]}')}",
            digest(f"run-spec-{values['tag']}"),
            digest("policy"),
            digest("runtime-lock"),
            digest("runtime-proof"),
            digest("budget"),
            values["run_id"],
            f"auth_request_{values['tag']}",
            f"auth_idempotency_{values['tag']}",
            digest(f"command-{values['tag']}"),
            digest(f"receipt-{values['tag']}"),
            TIMESTAMP,
        ),
    )
    db.execute(
        """
        INSERT INTO run_attempts (
            attempt_id, run_id, job_id, lease_generation, state, worker_id,
            work_dir, created_at, updated_at
        ) VALUES (?, ?, ?, 1, 'running', 'worker', ?, ?, ?)
        """,
        (
            values["attempt_id"],
            values["run_id"],
            f"job_{values['tag']}",
            f"work_{values['tag']}",
            TIMESTAMP,
            TIMESTAMP,
        ),
    )


def _insert_workspace_proof(
    db: sqlite3.Connection,
    values: dict[str, str | int],
) -> None:
    db.execute(
        """
        INSERT INTO agent_workspace_proofs (
            workspace_proof_id, contract_version, run_id, authorization_id,
            attempt_id, lease_generation, source_attempt_id, process_boundary,
            process_ordinal, workflow_revision_id, workflow_revision_content_hash,
            workflow_revision_manifest_hash, run_spec_hash, input_snapshot_hash,
            tool_assets_hash, runtime_lock_hash, runtime_proof_hash,
            immutable_manifest_json, immutable_manifest_hash,
            snakemake_manifest_json, snakemake_manifest_hash,
            previous_proof_hash, event_id, created_at, proof_hash
        ) VALUES (?, 'agent-workspace-proof.v1', ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, '[]', ?, '[]', ?, NULL, ?, ?, ?)
        """,
        (
            values["workspace_proof_id"],
            values["run_id"],
            values["authorization_id"],
            values["attempt_id"],
            values["proof_boundary"],
            values["process_ordinal"],
            values["revision_id"],
            digest(f"revision-content-{values['tag']}"),
            digest("revision-manifest"),
            digest(f"run-spec-{values['tag']}"),
            digest(f"input-{values['tag']}"),
            values["tool_assets_hash"],
            digest("runtime-lock"),
            digest("runtime-proof"),
            digest("immutable-manifest"),
            digest("snakemake-manifest"),
            values["spawn_event_id"],
            TIMESTAMP,
            digest(f"proof-{values['tag']}"),
        ),
    )
