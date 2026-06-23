from __future__ import annotations

import sqlite3
from collections.abc import Callable


EnsureColumns = Callable[[sqlite3.Connection, str, dict[str, str]], None]


def ensure_scheduler_triggers(connection: sqlite3.Connection, ensure_columns: EnsureColumns) -> None:
    ensure_columns(
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
