from __future__ import annotations

import sqlite3
from collections.abc import Callable


RecordMigration = Callable[[sqlite3.Connection, int, str], None]


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


def ensure_artifact_cache(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_cache_entries (
            cache_entry_id TEXT PRIMARY KEY,
            cache_key TEXT NOT NULL UNIQUE,
            cache_key_schema TEXT NOT NULL,
            key_payload_json TEXT NOT NULL,
            workflow_revision_id TEXT NOT NULL,
            artifact_key TEXT NOT NULL,
            step_id TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'output',
            run_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            artifact_blob_id TEXT NOT NULL,
            materialization_id TEXT NOT NULL DEFAULT '',
            storage_backend TEXT NOT NULL,
            storage_uri TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            lifecycle_state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            hit_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_artifact_cache_entries_revision
        ON artifact_cache_entries(workflow_revision_id, artifact_key, step_id, role)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_artifact_cache_entries_blob
        ON artifact_cache_entries(artifact_blob_id, lifecycle_state, created_at)
        """
    )


def ensure_result_package_exports(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS result_package_exports (
            package_export_id TEXT PRIMARY KEY,
            result_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            workflow_revision_id TEXT NOT NULL,
            package_path TEXT NOT NULL,
            package_uri TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            evidence_event_id TEXT NOT NULL,
            artifact_ids_json TEXT NOT NULL DEFAULT '[]',
            lifecycle_state TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            UNIQUE(result_id, sha256, manifest_sha256)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_result_package_exports_run_lifecycle
        ON result_package_exports(run_id, lifecycle_state, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_result_package_exports_result_created
        ON result_package_exports(result_id, created_at)
        """
    )


def migrate_artifact_lifecycle_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_artifact_lifecycle(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def migrate_artifact_cache_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_artifact_cache(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def migrate_result_package_exports_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_result_package_exports(connection)
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
