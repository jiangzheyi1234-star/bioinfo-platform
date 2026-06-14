from __future__ import annotations

import sqlite3
import time

from .config import RemoteRunnerConfig, ensure_runtime_layout
from .storage_schema import SCHEMA_SQL
from .tool_prepare_reservations import json_object, tool_prepare_job_reservation


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_connection(cfg: RemoteRunnerConfig) -> sqlite3.Connection:
    ensure_runtime_layout(cfg)
    connection = sqlite3.connect(str(cfg.db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(SCHEMA_SQL)
    _ensure_adopted_output_edge_uniqueness(connection)
    _ensure_run_columns(connection)
    _ensure_run_event_columns(connection)
    _ensure_run_execution_columns(connection)
    _ensure_candidate_output_columns(connection)
    _ensure_tools_columns(connection)
    _ensure_tool_prepare_job_columns(connection)
    _ensure_artifact_columns(connection)
    connection.commit()
    return connection


def _ensure_adopted_output_edge_uniqueness(connection: sqlite3.Connection) -> None:
    index_name = "idx_run_artifact_edges_adopted_output"
    if _index_exists(connection, index_name):
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        if _index_exists(connection, index_name):
            connection.commit()
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
        connection.commit()
    except Exception:
        connection.rollback()
        raise


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
