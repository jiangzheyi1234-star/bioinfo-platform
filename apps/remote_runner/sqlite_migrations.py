from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from .sqlite_artifact_migrations import (
    ensure_artifact_cache,
    ensure_artifact_cache_pins,
    ensure_artifact_lifecycle,
    ensure_artifact_storage_columns,
    ensure_result_package_export_payload_mode,
    ensure_result_package_exports,
    migrate_artifact_cache_pin_schema,
    migrate_artifact_cache_schema,
    migrate_artifact_lifecycle_schema,
    migrate_result_package_payload_mode_schema,
    migrate_result_package_exports_schema,
)
from .sqlite_schema_contract import REQUIRED_INDEXES, REQUIRED_TABLES, REQUIRED_TRIGGERS
from .sqlite_trigger_migrations import ensure_scheduler_triggers
from .sqlite_trigger_inbox_migrations import (
    ensure_workflow_trigger_inbox_signature_metadata,
    migrate_workflow_trigger_inbox_schema,
    migrate_workflow_trigger_inbox_payload_schema,
    migrate_workflow_trigger_inbox_signature_metadata_schema,
)
from .storage_schema import SCHEMA_SQL
from .tool_prepare_reservations import json_object, tool_prepare_job_reservation

CURRENT_SCHEMA_VERSION = 12
BASELINE_MIGRATION_NAME = "001_baseline_remote_runner_schema"
RULE_LEVEL_RUN_STATE_MIGRATION_NAME = "002_rule_level_run_state"
SCHEDULER_TRIGGER_MIGRATION_NAME = "003_scheduler_triggers"
ARTIFACT_LIFECYCLE_MIGRATION_NAME = "004_artifact_lifecycle"
ARTIFACT_CACHE_MIGRATION_NAME = "005_artifact_cache"
BACKFILL_LAUNCH_MIGRATION_NAME = "006_backfill_launch"
RESULT_PACKAGE_EXPORT_MIGRATION_NAME = "007_result_package_exports"
RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME = "008_result_package_payload_mode"
WORKFLOW_TRIGGER_INBOX_MIGRATION_NAME = "009_workflow_trigger_inbox"
WORKFLOW_TRIGGER_INBOX_PAYLOAD_MIGRATION_NAME = "010_workflow_trigger_inbox_payload"
ARTIFACT_CACHE_PIN_MIGRATION_NAME = "011_artifact_cache_pins"
WORKFLOW_TRIGGER_INBOX_SIGNATURE_METADATA_MIGRATION_NAME = "012_workflow_trigger_inbox_signature_metadata"
DATABASE_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_DATABASE_MISSING"
SCHEMA_MIGRATION_REQUIRED_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_MIGRATION_REQUIRED"
SCHEMA_TOO_NEW_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_TOO_NEW"
SCHEMA_LEDGER_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_MISSING"
SCHEMA_LEDGER_CHECKSUM_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_CHECKSUM_MISMATCH"
SCHEMA_OBJECT_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_OBJECT_MISSING"
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
        version = read_schema_version(connection)
    if version == 3:
        migrate_artifact_lifecycle_schema(
            connection,
            record_migration=_record_migration,
            version=4,
            name=ARTIFACT_LIFECYCLE_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 4:
        migrate_artifact_cache_schema(
            connection,
            record_migration=_record_migration,
            version=5,
            name=ARTIFACT_CACHE_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 5:
        _migrate_from_v5_to_v6(connection)
        version = read_schema_version(connection)
    if version == 6:
        migrate_result_package_exports_schema(
            connection,
            record_migration=_record_migration,
            version=7,
            name=RESULT_PACKAGE_EXPORT_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 7:
        migrate_result_package_payload_mode_schema(
            connection, record_migration=_record_migration, version=8,
            name=RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 8:
        migrate_workflow_trigger_inbox_schema(
            connection, record_migration=_record_migration, version=9,
            name=WORKFLOW_TRIGGER_INBOX_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 9:
        migrate_workflow_trigger_inbox_payload_schema(
            connection, record_migration=_record_migration, version=10,
            name=WORKFLOW_TRIGGER_INBOX_PAYLOAD_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 10:
        migrate_artifact_cache_pin_schema(
            connection,
            record_migration=_record_migration,
            version=11,
            name=ARTIFACT_CACHE_PIN_MIGRATION_NAME,
        )
        version = read_schema_version(connection)
    if version == 11:
        migrate_workflow_trigger_inbox_signature_metadata_schema(
            connection,
            record_migration=_record_migration,
            version=12,
            name=WORKFLOW_TRIGGER_INBOX_SIGNATURE_METADATA_MIGRATION_NAME,
        )
        return
    if version != 0:
        raise RemoteRunnerSQLiteSchemaError(f"REMOTE_RUNNER_SQLITE_SCHEMA_MIGRATION_MISSING: {version}")

    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        _ensure_schema_migrations_table(connection)
        _apply_baseline_schema_migration(connection)
        _record_migration(connection, CURRENT_SCHEMA_VERSION, WORKFLOW_TRIGGER_INBOX_SIGNATURE_METADATA_MIGRATION_NAME)
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
    payload = (
        f"{CURRENT_SCHEMA_VERSION}:{WORKFLOW_TRIGGER_INBOX_SIGNATURE_METADATA_MIGRATION_NAME}:"
        f"{SCHEMA_SQL}:{REFERENCE_DATABASE_SCHEMA_SQL}"
    )
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
    missing.extend(f"table:{name}" for name in sorted(REQUIRED_TABLES) if ("table", name) not in existing)
    missing.extend(f"index:{name}" for name in sorted(REQUIRED_INDEXES) if ("index", name) not in existing)
    missing.extend(f"trigger:{name}" for name in sorted(REQUIRED_TRIGGERS) if ("trigger", name) not in existing)
    return missing

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _apply_baseline_schema_migration(connection: sqlite3.Connection) -> None:
    _ensure_adopted_output_edge_uniqueness(connection)
    _ensure_run_columns(connection)
    _ensure_run_event_columns(connection)
    _ensure_run_execution_columns(connection)
    _ensure_rule_level_run_state(connection)
    ensure_scheduler_triggers(connection, _ensure_columns)
    _ensure_backfill_launches(connection)
    _ensure_candidate_output_columns(connection)
    _ensure_tools_columns(connection)
    _ensure_tool_prepare_job_columns(connection)
    ensure_artifact_storage_columns(connection)
    ensure_artifact_lifecycle(connection)
    ensure_artifact_cache(connection)
    ensure_artifact_cache_pins(connection)
    ensure_result_package_exports(connection)
    ensure_result_package_export_payload_mode(connection)
    ensure_workflow_trigger_inbox_signature_metadata(connection)

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
        ensure_scheduler_triggers(connection, _ensure_columns)
        _record_migration(connection, 3, SCHEDULER_TRIGGER_MIGRATION_NAME)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

def _migrate_from_v5_to_v6(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        _ensure_backfill_launches(connection)
        _record_migration(connection, 6, BACKFILL_LAUNCH_MIGRATION_NAME)
        connection.execute("PRAGMA user_version = 6")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

def _ensure_backfill_launches(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_backfill_launches (
            launch_id TEXT PRIMARY KEY,
            trigger_id TEXT NOT NULL,
            preview_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'backfill',
            range_start TEXT NOT NULL,
            range_end TEXT NOT NULL,
            timezone TEXT NOT NULL,
            partition_unit TEXT NOT NULL,
            run_order TEXT NOT NULL,
            reprocess_behavior TEXT NOT NULL,
            partition_count INTEGER NOT NULL,
            state TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            payload_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(trigger_id, preview_id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_backfill_launches_trigger_created
        ON workflow_backfill_launches(trigger_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_backfill_launches_state
        ON workflow_backfill_launches(state, updated_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_backfill_partitions (
            partition_id TEXT PRIMARY KEY,
            launch_id TEXT NOT NULL,
            trigger_id TEXT NOT NULL,
            partition_key TEXT NOT NULL,
            partition_index INTEGER NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            cursor TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            trigger_event_id TEXT,
            run_id TEXT,
            state TEXT NOT NULL,
            run_spec_hash TEXT NOT NULL,
            run_spec_json TEXT NOT NULL,
            error_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(trigger_id, partition_id),
            UNIQUE(launch_id, partition_index)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_backfill_partitions_launch_state
        ON workflow_backfill_partitions(launch_id, state, partition_index)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_backfill_partitions_run
        ON workflow_backfill_partitions(run_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_backfill_partitions_event
        ON workflow_backfill_partitions(trigger_event_id)
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
