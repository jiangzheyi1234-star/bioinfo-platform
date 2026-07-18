from __future__ import annotations

import sqlite3
from collections.abc import Callable


AGENT_CONTROL_PLANE_NAMESPACE_PREFIX = "agent-control-plane."
AGENT_RUN_AUTHORIZATION_RESERVED_NAMESPACE_COLLISION = (
    "AGENT_RUN_AUTHORIZATION_RESERVED_NAMESPACE_COLLISION"
)

AGENT_RUN_AUTHORIZATION_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_session_effect_budgets (
        session_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL CHECK (
            contract_version = 'agent-session-effect-budget.v1'
        ),
        max_run_submissions INTEGER NOT NULL CHECK (max_run_submissions = 1),
        actor TEXT NOT NULL,
        request_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        command_hash TEXT NOT NULL,
        receipt_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_session_effect_budgets_session_idempotency
    ON agent_session_effect_budgets(session_id, idempotency_key)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_run_authorizations (
        authorization_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL CHECK (
            contract_version = 'agent-run-authorization.v1'
        ),
        session_id TEXT NOT NULL,
        preview_hash TEXT NOT NULL,
        plan_revision_id TEXT NOT NULL,
        plan_generation INTEGER NOT NULL CHECK (plan_generation >= 1),
        plan_hash TEXT NOT NULL,
        workflow_revision_id TEXT NOT NULL,
        expected_state_version INTEGER NOT NULL CHECK (expected_state_version >= 1),
        input_manifest_digest TEXT NOT NULL,
        run_spec_hash TEXT NOT NULL,
        execution_policy_id TEXT NOT NULL,
        execution_policy_hash TEXT NOT NULL,
        runtime_lock_hash TEXT NOT NULL,
        runtime_proof_hash TEXT NOT NULL,
        effect_budget_hash TEXT NOT NULL,
        run_id TEXT NOT NULL,
        scope TEXT NOT NULL CHECK (scope = 'submit_workflow_run'),
        confirmation TEXT NOT NULL CHECK (confirmation = 'authorize-workflow-run'),
        actor TEXT NOT NULL,
        request_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        command_hash TEXT NOT NULL,
        receipt_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id) ON DELETE RESTRICT,
        FOREIGN KEY (plan_revision_id) REFERENCES agent_plan_revisions(plan_revision_id) ON DELETE RESTRICT,
        FOREIGN KEY (workflow_revision_id) REFERENCES workflow_revisions(workflow_revision_id) ON DELETE RESTRICT,
        FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_run_authorizations_session
    ON agent_run_authorizations(session_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_run_authorizations_run
    ON agent_run_authorizations(run_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_run_authorizations_session_idempotency
    ON agent_run_authorizations(session_id, idempotency_key)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_session_effect_budgets_no_update
    BEFORE UPDATE ON agent_session_effect_budgets
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_session_effect_budgets_no_delete
    BEFORE DELETE ON agent_session_effect_budgets
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_run_authorizations_no_update
    BEFORE UPDATE ON agent_run_authorizations
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_RUN_AUTHORIZATION_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_run_authorizations_no_delete
    BEFORE DELETE ON agent_run_authorizations
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_RUN_AUTHORIZATION_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_bound_runs_no_delete
    BEFORE DELETE ON runs
    WHEN EXISTS (
        SELECT 1
        FROM agent_run_authorizations
        WHERE run_id = OLD.run_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_BOUND_RUN_DELETE_FORBIDDEN');
    END
    """,
)

AGENT_RUN_AUTHORIZATION_SCHEMA_SQL = "\n".join(
    f"{statement.strip()};" for statement in AGENT_RUN_AUTHORIZATION_SCHEMA_STATEMENTS
)

RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_agent_run_authorization_schema(connection: sqlite3.Connection) -> None:
    for statement in AGENT_RUN_AUTHORIZATION_SCHEMA_STATEMENTS:
        connection.execute(statement)


def migrate_agent_run_authorization_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int,
    name: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert_no_agent_control_plane_namespace_collisions(connection)
        _ensure_schema_migrations_table(connection)
        ensure_agent_run_authorization_schema(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def assert_no_agent_control_plane_namespace_collisions(
    connection: sqlite3.Connection,
) -> None:
    prefix = AGENT_CONTROL_PLANE_NAMESPACE_PREFIX
    for table_name in ("runs", "idempotency", "workflow_triggers"):
        collision = connection.execute(
            f"""
            SELECT 1
            FROM {table_name}
            WHERE substr(server_id, 1, ?) COLLATE BINARY = ?
            LIMIT 1
            """,
            (len(prefix), prefix),
        ).fetchone()
        if collision is not None:
            raise RuntimeError(
                f"{AGENT_RUN_AUTHORIZATION_RESERVED_NAMESPACE_COLLISION}: "
                f"{table_name}.server_id"
            )


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
