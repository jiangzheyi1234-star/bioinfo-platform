from __future__ import annotations

import sqlite3


def ensure_artifact_storage_columns(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "artifacts",
        {
            "storage_backend": "TEXT NOT NULL DEFAULT 'local'",
            "storage_uri": "TEXT NOT NULL DEFAULT ''",
        },
    )


def ensure_artifact_lifecycle(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "artifacts",
        {
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "deleted_at": "TEXT",
            "gc_reason": "TEXT NOT NULL DEFAULT ''",
            "retention_until": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        "artifact_materializations",
        {
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "deleted_at": "TEXT",
            "gc_reason": "TEXT NOT NULL DEFAULT ''",
            "retention_until": "TEXT",
        },
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_artifacts_lifecycle
        ON artifacts(lifecycle_state, storage_backend, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_artifact_materializations_lifecycle
        ON artifact_materializations(lifecycle_state, storage_backend, created_at)
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
