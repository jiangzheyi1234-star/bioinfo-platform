from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from .storage_schema import SCHEMA_SQL
from .tool_prepare_reservations import json_object, tool_prepare_job_reservation


CURRENT_SCHEMA_VERSION = 3
BASELINE_MIGRATION_NAME = "001_baseline_remote_runner_schema"
RULE_LEVEL_RUN_STATE_MIGRATION_NAME = "002_rule_level_run_state"
SCHEDULER_TRIGGER_MIGRATION_NAME = "003_scheduler_triggers"
DATABASE_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_DATABASE_MISSING"
SCHEMA_MIGRATION_REQUIRED_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_MIGRATION_REQUIRED"
SCHEMA_TOO_NEW_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_TOO_NEW"
SCHEMA_LEDGER_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_MISSING"
SCHEMA_LEDGER_CHECKSUM_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_CHECKSUM_MISMATCH"
SCHEMA_OBJECT_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_OBJECT_MISSING"

_REQUIRED_TABLES = {
    "artifact_blobs",
    "artifact_materializations",
    "artifacts",
    "candidate_outputs",
    "evidence_events",
    "evidence_schemas",
    "idempotency",
    "lineage_edges",
    "reconcile_queue",
    "reference_databases",
    "resource_events",
    "resources",
    "run_artifact_edges",
    "run_attempts",
    "run_commands",
    "run_events",
    "run_jobs",
    "run_leases",
    "run_rule_events",
    "run_rules",
    "run_resource_allocations",
    "run_worker_slots",
    "run_workers",
    "runs",
    "schema_migrations",
    "service_state",
    "tool_index",
    "tool_prepare_job_events",
    "tool_prepare_jobs",
    "tool_revisions",
    "tool_runtime_profiles",
    "tool_validation_results",
    "tools",
    "uploads",
    "workflow_design_drafts",
    "workflow_revisions",
    "workflow_trigger_dispatches",
    "workflow_trigger_events",
    "workflow_triggers",
}
_REQUIRED_INDEXES = {
    "idx_candidate_outputs_attempt_generation_key",
    "idx_evidence_events_chain",
    "idx_evidence_events_subject",
    "idx_evidence_events_type_seq",
    "idx_lineage_edges_object",
    "idx_lineage_edges_run",
    "idx_lineage_edges_subject",
    "idx_run_artifact_edges_adopted_output",
    "idx_run_artifact_edges_blob",
    "idx_run_artifact_edges_run",
    "idx_run_commands_run",
    "idx_run_events_hash_chain",
    "idx_run_events_run_seq",
    "idx_run_jobs_claimable",
    "idx_run_leases_active_expiry",
    "idx_run_rule_events_run_rule",
    "idx_run_rules_run_status",
    "idx_run_resource_allocations_active",
    "idx_run_workers_state_heartbeat",
    "idx_tool_index_search",
    "idx_tool_index_source_quality",
    "idx_tool_index_state_quality",
    "idx_tool_prepare_jobs_active_reservation",
    "idx_tool_runtime_profiles_hash",
    "idx_tool_runtime_profiles_revision",
    "idx_tool_validation_results_job",
    "idx_tool_validation_results_tool",
    "idx_workflow_trigger_dispatches_run",
    "idx_workflow_trigger_dispatches_state",
    "idx_workflow_trigger_events_external",
    "idx_workflow_trigger_events_trigger_created",
    "idx_workflow_triggers_source_enabled",
}
_REQUIRED_TRIGGERS = {"workflow_revisions_no_update"}


class RemoteRunnerSQLiteSchemaError(RuntimeError):
    pass


def initialize_or_migrate_runtime_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as connection:
        connection.row_factory = sqlite3.Row
        configure_runtime_connection(connection)
        migrate_runtime_schema(connection)


def configure_runtime_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")


def migrate_runtime_schema(connection: sqlite3.Connection) -> None:
    version = read_schema_version(connection)
    if version > CURRENT_SCHEMA_VERSION:
        raise RemoteRunnerSQLiteSchemaError(
            f"{SCHEMA_TOO_NEW_ERROR}: database version {version} is newer than supported {CURRENT_SCHEMA_VERSION}"
        )
    if version == CURRENT_SCHEMA_VERSION:
        _assert_current_schema_contract(connection)
        return
    if version == 1:
        _migrate_from_v1_to_v2(connection)
        version = read_schema_version(connection)
    if version == 2:
        _migrate_from_v2_to_v3(connection)
        return
    if version != 0:
        raise RemoteRunnerSQLiteSchemaError(f"REMOTE_RUNNER_SQLITE_SCHEMA_MIGRATION_MISSING: {version}")

    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        _ensure_schema_migrations_table(connection)
        _apply_baseline_schema_migration(connection)
        _record_migration(connection, CURRENT_SCHEMA_VERSION, SCHEDULER_TRIGGER_MIGRATION_NAME)
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def ensure_runtime_schema_current(connection: sqlite3.Connection) -> None:
    version = read_schema_version(connection)
    if version > CURRENT_SCHEMA_VERSION:
        raise RemoteRunnerSQLiteSchemaError(
            f"{SCHEMA_TOO_NEW_ERROR}: database version {version} is newer than supported {CURRENT_SCHEMA_VERSION}"
        )
    if version < CURRENT_SCHEMA_VERSION:
        raise RemoteRunnerSQLiteSchemaError(
            f"{SCHEMA_MIGRATION_REQUIRED_ERROR}: database version {version} requires explicit migration"
        )
    _assert_current_schema_contract(connection)


def read_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0] or 0)


def _ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _assert_current_schema_contract(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """
    ).fetchone()
    if row is None:
        raise RemoteRunnerSQLiteSchemaError(SCHEMA_LEDGER_MISSING_ERROR)
    migration = connection.execute(
        "SELECT checksum FROM schema_migrations WHERE version = ?",
        (CURRENT_SCHEMA_VERSION,),
    ).fetchone()
    if migration is None:
        raise RemoteRunnerSQLiteSchemaError(SCHEMA_LEDGER_MISSING_ERROR)
    if str(migration["checksum"] if isinstance(migration, sqlite3.Row) else migration[0]) != _baseline_checksum():
        raise RemoteRunnerSQLiteSchemaError(SCHEMA_LEDGER_CHECKSUM_ERROR)
    missing = _missing_required_schema_objects(connection)
    if missing:
        raise RemoteRunnerSQLiteSchemaError(f"{SCHEMA_OBJECT_MISSING_ERROR}: {missing[0]}")


def _record_migration(connection: sqlite3.Connection, version: int, name: str) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at)
        VALUES (?, ?, ?, ?)
        """,
        (version, name, _baseline_checksum(), _now_iso()),
    )


def _baseline_checksum() -> str:
    payload = f"{CURRENT_SCHEMA_VERSION}:{SCHEDULER_TRIGGER_MIGRATION_NAME}:{SCHEMA_SQL}:{REFERENCE_DATABASE_SCHEMA_SQL}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _missing_required_schema_objects(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger')
        """
    ).fetchall()
    existing = {(str(row["type"]), str(row["name"])) for row in rows}
    missing: list[str] = []
    missing.extend(f"table:{name}" for name in sorted(_REQUIRED_TABLES) if ("table", name) not in existing)
    missing.extend(f"index:{name}" for name in sorted(_REQUIRED_INDEXES) if ("index", name) not in existing)
    missing.extend(f"trigger:{name}" for name in sorted(_REQUIRED_TRIGGERS) if ("trigger", name) not in existing)
    return missing


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _apply_baseline_schema_migration(connection: sqlite3.Connection) -> None:
    _ensure_adopted_output_edge_uniqueness(connection)
    _ensure_run_columns(connection)
    _ensure_run_event_columns(connection)
    _ensure_run_execution_columns(connection)
    _ensure_rule_level_run_state(connection)
    _ensure_scheduler_triggers(connection)
    _ensure_candidate_output_columns(connection)
    _ensure_tools_columns(connection)
    _ensure_tool_prepare_job_columns(connection)
    _ensure_artifact_columns(connection)


def _migrate_from_v1_to_v2(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        _ensure_rule_level_run_state(connection)
        _record_migration(connection, 2, RULE_LEVEL_RUN_STATE_MIGRATION_NAME)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _migrate_from_v2_to_v3(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        _ensure_scheduler_triggers(connection)
        _record_migration(connection, CURRENT_SCHEMA_VERSION, SCHEDULER_TRIGGER_MIGRATION_NAME)
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _ensure_scheduler_triggers(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "runs",
        {
            "trigger_id": "TEXT",
            "trigger_event_id": "TEXT",
            "trigger_source": "TEXT NOT NULL DEFAULT ''",
            "trigger_cursor": "TEXT NOT NULL DEFAULT ''",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_triggers (
            trigger_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            server_id TEXT NOT NULL,
            pipeline_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            trigger_spec_json TEXT NOT NULL DEFAULT '{}',
            run_spec_template_json TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_triggers_source_enabled
        ON workflow_triggers(source_type, enabled, updated_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_trigger_events (
            trigger_event_id TEXT PRIMARY KEY,
            trigger_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            event_type TEXT NOT NULL,
            external_event_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            cursor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(trigger_id, idempotency_key)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_events_trigger_created
        ON workflow_trigger_events(trigger_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_trigger_events_external
        ON workflow_trigger_events(trigger_id, source_type, external_event_id)
        WHERE external_event_id <> ''
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_trigger_dispatches (
            dispatch_id TEXT PRIMARY KEY,
            trigger_event_id TEXT NOT NULL,
            trigger_id TEXT NOT NULL,
            state TEXT NOT NULL,
            run_id TEXT,
            request_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            error_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(trigger_event_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_dispatches_state
        ON workflow_trigger_dispatches(state, updated_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_dispatches_run
        ON workflow_trigger_dispatches(run_id)
        """
    )


def _ensure_rule_level_run_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_rules (
            run_rule_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            rule_name TEXT NOT NULL,
            step_id TEXT NOT NULL DEFAULT '',
            runtime_status_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            attempt_id TEXT NOT NULL DEFAULT '',
            lease_generation INTEGER NOT NULL DEFAULT 0,
            attempt_number INTEGER,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            message TEXT NOT NULL DEFAULT '',
            command_summary TEXT NOT NULL DEFAULT '',
            inputs_json TEXT NOT NULL DEFAULT '[]',
            outputs_json TEXT NOT NULL DEFAULT '[]',
            wildcards_json TEXT NOT NULL DEFAULT '{}',
            logs_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, rule_name, attempt_id, lease_generation)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_rules_run_status
        ON run_rules(run_id, status, updated_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_rule_events (
            rule_event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            run_rule_id TEXT NOT NULL,
            rule_name TEXT NOT NULL,
            step_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            lease_generation INTEGER NOT NULL,
            attempt_number INTEGER,
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_rule_events_run_rule
        ON run_rule_events(run_id, rule_name, created_at)
        """
    )


def _ensure_adopted_output_edge_uniqueness(connection: sqlite3.Connection) -> None:
    index_name = "idx_run_artifact_edges_adopted_output"
    if _index_exists(connection, index_name):
        return

    duplicate_groups = connection.execute(
        """
        SELECT run_id, port_name
        FROM run_artifact_edges
        WHERE role = 'output' AND port_name IS NOT NULL
        GROUP BY run_id, port_name
        HAVING COUNT(*) > 1
        ORDER BY run_id, port_name
        """
    ).fetchall()
    for group in duplicate_groups:
        duplicate_edges = connection.execute(
            """
            SELECT edge_id
            FROM run_artifact_edges
            WHERE run_id = ? AND role = 'output' AND port_name = ?
            ORDER BY created_at ASC, edge_id ASC
            """,
            (group["run_id"], group["port_name"]),
        ).fetchall()
        for edge in duplicate_edges[1:]:
            migrated_port_name = _legacy_output_port_name(
                connection,
                run_id=str(group["run_id"]),
                port_name=str(group["port_name"]),
                edge_id=str(edge["edge_id"]),
            )
            connection.execute(
                "UPDATE run_artifact_edges SET port_name = ? WHERE edge_id = ?",
                (migrated_port_name, edge["edge_id"]),
            )
    connection.execute(
        """
        CREATE UNIQUE INDEX idx_run_artifact_edges_adopted_output
        ON run_artifact_edges(run_id, role, port_name)
        WHERE role = 'output' AND port_name IS NOT NULL
        """
    )


def _legacy_output_port_name(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    port_name: str,
    edge_id: str,
) -> str:
    base = f"{port_name}#legacy-{edge_id}"
    candidate = base
    suffix = 2
    while connection.execute(
        """
        SELECT 1
        FROM run_artifact_edges
        WHERE run_id = ? AND role = 'output' AND port_name = ?
        LIMIT 1
        """,
        (run_id, candidate),
    ).fetchone():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _index_exists(connection: sqlite3.Connection, index_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        is not None
    )


def _ensure_run_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "runs",
        {
            "workflow_revision_id": "TEXT",
        },
    )


def _ensure_run_event_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(run_events)").fetchall()}
    column_definitions = {
        "seq": "INTEGER NOT NULL DEFAULT 0",
        "schema_version": "TEXT NOT NULL DEFAULT ''",
        "command_id": "TEXT",
        "correlation_id": "TEXT",
        "actor": "TEXT",
        "payload_hash": "TEXT NOT NULL DEFAULT ''",
        "event_hash": "TEXT NOT NULL DEFAULT ''",
        "prev_event_hash": "TEXT",
    }
    for column, definition in column_definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE run_events ADD COLUMN {column} {definition}")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_run_events_run_seq
        ON run_events(run_id, seq)
        WHERE seq > 0
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_hash_chain
        ON run_events(run_id, seq, event_hash)
        """
    )


def _ensure_run_execution_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "run_jobs",
        {
            "queue_name": "TEXT NOT NULL DEFAULT 'default'",
            "wait_reason_json": "TEXT NOT NULL DEFAULT '{}'",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "retry_policy_json": "TEXT NOT NULL DEFAULT '{}'",
            "timeout_policy_json": "TEXT NOT NULL DEFAULT '{}'",
            "dead_lettered_at": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        "run_attempts",
        {
            "attempt_number": "INTEGER NOT NULL DEFAULT 1",
            "session_id": "TEXT NOT NULL DEFAULT ''",
            "slot_id": "TEXT NOT NULL DEFAULT 'slot-0'",
            "process_pid": "INTEGER",
            "cancel_requested_at": "TEXT",
            "killed_at": "TEXT",
            "output_adoption_state": "TEXT NOT NULL DEFAULT 'pending'",
        },
    )
    _ensure_columns(
        connection,
        "run_leases",
        {
            "session_id": "TEXT NOT NULL DEFAULT ''",
            "slot_id": "TEXT NOT NULL DEFAULT 'slot-0'",
        },
    )
    _ensure_columns(
        connection,
        "run_workers",
        {
            "session_id": "TEXT NOT NULL DEFAULT ''",
            "pid": "INTEGER NOT NULL DEFAULT 0",
            "hostname": "TEXT NOT NULL DEFAULT ''",
            "state": "TEXT NOT NULL DEFAULT 'idle'",
            "queue_name": "TEXT NOT NULL DEFAULT 'default'",
            "concurrency_limit": "INTEGER NOT NULL DEFAULT 1",
            "current_attempt_id": "TEXT",
            "heartbeat_at": "TEXT NOT NULL DEFAULT ''",
            "last_error_json": "TEXT NOT NULL DEFAULT '{}'",
            "drain_requested_at": "TEXT",
            "started_at": "TEXT NOT NULL DEFAULT ''",
            "stopped_at": "TEXT",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_workers_state_heartbeat
        ON run_workers(state, heartbeat_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_worker_slots (
            worker_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            slot_id TEXT NOT NULL,
            state TEXT NOT NULL,
            current_attempt_id TEXT,
            heartbeat_at TEXT NOT NULL,
            last_error_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            stopped_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(worker_id, slot_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_resource_allocations (
            allocation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            slot_id TEXT NOT NULL,
            cpu INTEGER NOT NULL DEFAULT 1,
            memory_mb INTEGER NOT NULL DEFAULT 0,
            disk_mb INTEGER NOT NULL DEFAULT 0,
            gpu INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            released_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(attempt_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_resource_allocations_active
        ON run_resource_allocations(state, slot_id, worker_id)
        """
    )


def _ensure_candidate_output_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "candidate_outputs",
        {
            "lease_generation": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_outputs_attempt_generation_key
        ON candidate_outputs(run_id, attempt_id, lease_generation, output_key)
        """
    )


def _ensure_tools_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(tools)").fetchall()}
    if "tool_revision_id" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN tool_revision_id TEXT NOT NULL DEFAULT ''")
    if "revision" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
    if "rule_template_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN rule_template_json TEXT NOT NULL DEFAULT '{}'")
    if "rule_spec_draft_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN rule_spec_draft_json TEXT NOT NULL DEFAULT '{}'")
    if "capabilities_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN capabilities_json TEXT NOT NULL DEFAULT '[]'")
    if "snakemake_wrappers_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN snakemake_wrappers_json TEXT NOT NULL DEFAULT '[]'")
    if "contract_status_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN contract_status_json TEXT NOT NULL DEFAULT '{}'")
    if "published_at" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN published_at TEXT")


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_definitions: dict[str, str],
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column, definition in column_definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")


def _ensure_tool_prepare_job_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(tool_prepare_jobs)").fetchall()}
    column_definitions = {
        "reservation_key": "TEXT NOT NULL DEFAULT ''",
        "reservation_package_spec": "TEXT NOT NULL DEFAULT ''",
        "reservation_validation_target": "TEXT NOT NULL DEFAULT ''",
        "claimed_by": "TEXT NOT NULL DEFAULT ''",
        "claimed_until": "TEXT",
        "heartbeat_at": "TEXT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "max_attempts": "INTEGER NOT NULL DEFAULT 3",
        "next_attempt_at": "TEXT",
        "exhausted_at": "TEXT",
        "backoff_seconds": "INTEGER NOT NULL DEFAULT 30",
        "last_worker_error_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    added_columns = False
    for column, definition in column_definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE tool_prepare_jobs ADD COLUMN {column} {definition}")
            added_columns = True
    if added_columns or _tool_prepare_jobs_need_reservation_backfill(connection):
        _backfill_tool_prepare_job_reservations(connection)
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_prepare_jobs_active_reservation
        ON tool_prepare_jobs(reservation_key)
        WHERE status IN ('queued', 'running') AND reservation_key <> ''
        """
    )


def _tool_prepare_jobs_need_reservation_backfill(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM tool_prepare_jobs
        WHERE reservation_key = ''
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _backfill_tool_prepare_job_reservations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT job_id, tool_id, request_json
        FROM tool_prepare_jobs
        WHERE reservation_key = ''
        """
    ).fetchall()
    for row in rows:
        request = json_object(row["request_json"])
        reservation = tool_prepare_job_reservation(request, str(row["tool_id"] or ""))
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET reservation_key = ?,
                reservation_package_spec = ?,
                reservation_validation_target = ?
            WHERE job_id = ?
            """,
            (
                reservation["key"],
                reservation["packageSpec"],
                reservation["validationTarget"],
                row["job_id"],
            ),
        )


def _ensure_artifact_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(artifacts)").fetchall()}
    if "storage_backend" not in columns:
        connection.execute("ALTER TABLE artifacts ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local'")
    if "storage_uri" not in columns:
        connection.execute("ALTER TABLE artifacts ADD COLUMN storage_uri TEXT NOT NULL DEFAULT ''")
