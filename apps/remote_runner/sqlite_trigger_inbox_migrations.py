from __future__ import annotations

import sqlite3
from collections.abc import Callable


def ensure_workflow_trigger_inbox(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_trigger_inbox_events (
            inbox_event_id TEXT PRIMARY KEY,
            trigger_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'webhook',
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            provider_event_id TEXT NOT NULL,
            correlation_id TEXT NOT NULL DEFAULT '',
            cursor TEXT NOT NULL DEFAULT '',
            dedupe_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_size_bytes INTEGER NOT NULL DEFAULT 0,
            signature_state TEXT NOT NULL DEFAULT 'unsupported',
            state TEXT NOT NULL,
            delivery_count INTEGER NOT NULL DEFAULT 1,
            trigger_event_id TEXT,
            run_id TEXT,
            failure_code TEXT NOT NULL DEFAULT '',
            error_json TEXT,
            received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            dead_lettered_at TEXT,
            UNIQUE(trigger_id, dedupe_key)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_inbox_trigger_received
        ON workflow_trigger_inbox_events(trigger_id, received_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_inbox_state
        ON workflow_trigger_inbox_events(state, updated_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_trigger_inbox_trigger_event
        ON workflow_trigger_inbox_events(trigger_event_id)
        """
    )


def migrate_workflow_trigger_inbox_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: Callable[[sqlite3.Connection, int, str], None],
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_workflow_trigger_inbox(connection)
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
