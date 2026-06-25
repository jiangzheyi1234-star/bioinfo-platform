from __future__ import annotations

import sqlite3
from collections.abc import Callable


RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_artifact_ledger_invalidation(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "run_artifact_edges",
        {
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "invalidated_at": "TEXT",
            "invalidation_reason": "TEXT NOT NULL DEFAULT ''",
            "invalidation_event_id": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        "lineage_edges",
        {
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "invalidated_at": "TEXT",
            "invalidation_reason": "TEXT NOT NULL DEFAULT ''",
            "invalidation_event_id": "TEXT",
        },
    )
    connection.execute("DROP INDEX IF EXISTS idx_run_artifact_edges_adopted_output")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_run_artifact_edges_adopted_output
        ON run_artifact_edges(run_id, role, port_name)
        WHERE role = 'output' AND port_name IS NOT NULL AND lifecycle_state = 'active'
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_artifact_edges_lifecycle
        ON run_artifact_edges(run_id, lifecycle_state, role, step_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lineage_edges_lifecycle
        ON lineage_edges(run_id, lifecycle_state, created_at)
        """
    )


def migrate_artifact_ledger_invalidation_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_artifact_ledger_invalidation(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


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


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    column_definitions: dict[str, str],
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column, definition in column_definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
