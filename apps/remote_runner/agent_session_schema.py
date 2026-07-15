from __future__ import annotations

import sqlite3
from collections.abc import Callable


AGENT_SESSION_STATUSES = frozenset(
    {
        "created",
        "planning",
        "awaiting_approval",
        "plan_failed",
        "changes_requested",
        "ready_to_run",
        "cancelled",
    }
)

AGENT_SESSION_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_sessions (
        session_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL,
        project_id TEXT NOT NULL,
        goal_json TEXT NOT NULL,
        constraints_json TEXT NOT NULL,
        budget_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN (
                'created', 'planning', 'awaiting_approval', 'plan_failed',
                'changes_requested', 'ready_to_run', 'cancelled'
            )
        ),
        state_version INTEGER NOT NULL CHECK (state_version >= 1),
        plan_generation INTEGER NOT NULL DEFAULT 0 CHECK (plan_generation >= 0),
        active_draft_id TEXT,
        active_draft_revision INTEGER,
        active_plan_hash TEXT,
        workflow_revision_id TEXT,
        planner_json TEXT NOT NULL DEFAULT '{}',
        last_error_code TEXT NOT NULL DEFAULT '',
        creation_request_id TEXT NOT NULL UNIQUE,
        creation_request_hash TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        cancelled_at TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_sessions_status_updated
    ON agent_sessions(status, updated_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_sessions_project_updated
    ON agent_sessions(project_id, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_plan_revisions (
        plan_revision_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL,
        session_id TEXT NOT NULL,
        plan_generation INTEGER NOT NULL CHECK (plan_generation >= 1),
        parent_plan_revision_id TEXT,
        draft_id TEXT NOT NULL,
        draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
        plan_hash TEXT NOT NULL,
        proposal_json TEXT NOT NULL,
        validation_json TEXT NOT NULL,
        budget_json TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(session_id, plan_generation),
        UNIQUE(session_id, plan_hash)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_plan_revisions_session_generation
    ON agent_plan_revisions(session_id, plan_generation)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_plan_revisions_hash
    ON agent_plan_revisions(plan_hash)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_approvals (
        approval_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL,
        session_id TEXT NOT NULL,
        plan_revision_id TEXT NOT NULL,
        plan_generation INTEGER NOT NULL CHECK (plan_generation >= 1),
        plan_hash TEXT NOT NULL,
        expected_state_version INTEGER NOT NULL CHECK (expected_state_version >= 1),
        decision TEXT NOT NULL CHECK (decision IN ('approve', 'request_changes')),
        scope TEXT NOT NULL CHECK (scope = 'compile_workflow_revision'),
        actor TEXT NOT NULL,
        reason TEXT,
        request_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        approval_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(session_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_approvals_session_plan
    ON agent_approvals(session_id, plan_generation, created_at)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_approvals_effective_decision
    ON agent_approvals(session_id, plan_generation, expected_state_version)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_events (
        event_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        seq INTEGER NOT NULL CHECK (seq >= 1),
        schema_version TEXT NOT NULL,
        event_type TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        state_version INTEGER NOT NULL CHECK (state_version >= 1),
        plan_generation INTEGER NOT NULL CHECK (plan_generation >= 0),
        actor TEXT NOT NULL,
        request_id TEXT NOT NULL,
        correlation_id TEXT,
        idempotency_key TEXT NOT NULL,
        command_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        event_hash TEXT NOT NULL,
        prev_event_hash TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(session_id, seq)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_events_session_idempotency
    ON agent_events(session_id, idempotency_key)
    WHERE idempotency_key <> ''
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_events_hash_chain
    ON agent_events(session_id, seq, event_hash)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_events_no_update
    BEFORE UPDATE ON agent_events
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_EVENT_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_events_no_delete
    BEFORE DELETE ON agent_events
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_EVENT_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_plan_revisions_no_update
    BEFORE UPDATE ON agent_plan_revisions
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PLAN_REVISION_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_plan_revisions_no_delete
    BEFORE DELETE ON agent_plan_revisions
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PLAN_REVISION_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_approvals_no_update
    BEFORE UPDATE ON agent_approvals
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_APPROVAL_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_approvals_no_delete
    BEFORE DELETE ON agent_approvals
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_APPROVAL_IMMUTABLE');
    END
    """,
)

AGENT_SESSION_SCHEMA_SQL = "\n".join(f"{statement.strip()};" for statement in AGENT_SESSION_SCHEMA_STATEMENTS)

RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_agent_session_schema(connection: sqlite3.Connection) -> None:
    for statement in AGENT_SESSION_SCHEMA_STATEMENTS:
        connection.execute(statement)


def migrate_agent_session_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_agent_session_schema(connection)
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
