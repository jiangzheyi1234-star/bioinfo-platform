from __future__ import annotations

import sqlite3
from collections.abc import Callable


RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_artifact_lifecycle_policies(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_lifecycle_policies (
            policy_id TEXT PRIMARY KEY,
            policy_version INTEGER NOT NULL,
            policy_json TEXT NOT NULL,
            policy_fingerprint TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            update_reason TEXT NOT NULL DEFAULT ''
        )
        """
    )


def migrate_artifact_lifecycle_policy_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_artifact_lifecycle_policies(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {int(version)}")
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
