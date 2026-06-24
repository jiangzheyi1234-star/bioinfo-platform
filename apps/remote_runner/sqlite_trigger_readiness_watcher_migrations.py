from __future__ import annotations

import sqlite3
from typing import Callable


WORKFLOW_TRIGGER_READINESS_WATCHER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_trigger_readiness_observations (
    trigger_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_uri TEXT NOT NULL DEFAULT '',
    watcher_adapter TEXT NOT NULL,
    observation_hash TEXT NOT NULL,
    observed_version TEXT NOT NULL,
    observed_checksum TEXT NOT NULL DEFAULT '',
    observed_state TEXT NOT NULL,
    dispatch_state TEXT NOT NULL DEFAULT '',
    trigger_event_id TEXT,
    run_id TEXT,
    error_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_trigger_readiness_observations_state
ON workflow_trigger_readiness_observations(observed_state, updated_at);

CREATE INDEX IF NOT EXISTS idx_workflow_trigger_readiness_observations_event
ON workflow_trigger_readiness_observations(trigger_event_id);
"""


def ensure_workflow_trigger_readiness_watcher(connection: sqlite3.Connection) -> None:
    connection.executescript(WORKFLOW_TRIGGER_READINESS_WATCHER_SCHEMA_SQL)


def migrate_workflow_trigger_readiness_watcher_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: Callable[[sqlite3.Connection, int, str], None],
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        ensure_workflow_trigger_readiness_watcher(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
