from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import agent_run_authorization_schema
from apps.remote_runner.agent_run_authorization_schema import (
    AGENT_RUN_AUTHORIZATION_RESERVED_NAMESPACE_COLLISION,
    ensure_agent_run_authorization_schema,
)
from apps.remote_runner.sqlite_migrations import (
    AGENT_RUN_AUTHORIZATION_MIGRATION_NAME,
    AGENT_SESSION_MIGRATION_NAME,
    CURRENT_SCHEMA_VERSION,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.sqlite_schema_contract import missing_required_schema_objects
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_remote_runner_config


V19_TABLES = frozenset(
    {"agent_run_authorizations", "agent_session_effect_budgets"}
)
V19_INDEXES = frozenset(
    {
        "idx_agent_run_authorizations_run",
        "idx_agent_run_authorizations_session",
        "idx_agent_run_authorizations_session_idempotency",
        "idx_agent_session_effect_budgets_session_idempotency",
    }
)
V19_TRIGGERS = frozenset(
    {
        "agent_bound_runs_no_delete",
        "agent_run_authorizations_no_delete",
        "agent_run_authorizations_no_update",
        "agent_session_effect_budgets_no_delete",
        "agent_session_effect_budgets_no_update",
    }
)
V19_OBJECTS = V19_TABLES | V19_INDEXES | V19_TRIGGERS


def test_fresh_v19_records_v18_and_v19_and_enables_foreign_keys(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)

    initialize_or_migrate_runtime_db(cfg.db_path)

    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION == 19
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        ledger = connection.execute(
            "SELECT version, name FROM schema_migrations WHERE version IN (18, 19) ORDER BY version"
        ).fetchall()
        objects = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN ({})".format(
                    ",".join("?" for _ in V19_OBJECTS)
                ),
                tuple(sorted(V19_OBJECTS)),
            ).fetchall()
        }

    assert [tuple(row) for row in ledger] == [
        (18, AGENT_SESSION_MIGRATION_NAME),
        (19, AGENT_RUN_AUTHORIZATION_MIGRATION_NAME),
    ]
    assert objects == V19_OBJECTS


def test_v18_to_v19_schema_matches_fresh_schema(tmp_path: Path) -> None:
    fresh_cfg = make_remote_runner_config(tmp_path / "fresh")
    migrated_cfg = make_remote_runner_config(tmp_path / "migrated")
    initialize_or_migrate_runtime_db(fresh_cfg.db_path)
    initialize_or_migrate_runtime_db(migrated_cfg.db_path)
    _downgrade_to_v18(Path(migrated_cfg.db_path))

    initialize_or_migrate_runtime_db(migrated_cfg.db_path)

    with sqlite3.connect(fresh_cfg.db_path) as connection:
        fresh = _v19_schema_snapshot(connection)
    with sqlite3.connect(migrated_cfg.db_path) as connection:
        migrated = _v19_schema_snapshot(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        ledger = connection.execute(
            "SELECT version, name FROM schema_migrations WHERE version IN (18, 19) ORDER BY version"
        ).fetchall()

    assert migrated == fresh
    assert version == 19
    assert ledger == [
        (18, AGENT_SESSION_MIGRATION_NAME),
        (19, AGENT_RUN_AUTHORIZATION_MIGRATION_NAME),
    ]


@pytest.mark.parametrize("table_name", ["runs", "idempotency", "workflow_triggers"])
def test_v18_migration_rejects_reserved_namespace_collisions_atomically(
    tmp_path: Path,
    table_name: str,
) -> None:
    cfg = make_remote_runner_config(tmp_path / table_name)
    initialize_or_migrate_runtime_db(cfg.db_path)
    _downgrade_to_v18(Path(cfg.db_path))
    with sqlite3.connect(cfg.db_path) as connection:
        _insert_reserved_namespace_collision(connection, table_name)

    with pytest.raises(
        RuntimeError,
        match=rf"{AGENT_RUN_AUTHORIZATION_RESERVED_NAMESPACE_COLLISION}: {table_name}\.server_id",
    ):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 18
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 19"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_run_authorizations'"
        ).fetchone() is None
        assert connection.execute(
            f"SELECT 1 FROM {table_name} WHERE substr(server_id, 1, 20) = 'agent-control-plane.'"
        ).fetchone() is not None


def test_v18_migration_rolls_back_partial_schema_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    _downgrade_to_v18(Path(cfg.db_path))

    def fail_after_partial_ddl(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE v19_partial_write (value TEXT NOT NULL)")
        raise RuntimeError("forced v19 schema failure")

    monkeypatch.setattr(
        agent_run_authorization_schema,
        "ensure_agent_run_authorization_schema",
        fail_after_partial_ddl,
    )

    with pytest.raises(RuntimeError, match="forced v19 schema failure"):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 18
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 19"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'v19_partial_write'"
        ).fetchone() is None


def test_v19_constraints_foreign_keys_and_delete_guards_are_enforced(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)

    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            _insert_effect_budget(connection, suffix="missing")

        _insert_authorization_parents(connection, suffix="one")
        _insert_effect_budget(connection, suffix="one")
        _insert_authorization(connection, suffix="one")

        with pytest.raises(sqlite3.IntegrityError, match="AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_session_effect_budgets SET actor = 'changed' WHERE session_id = 'agent_one'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_SESSION_EFFECT_BUDGET_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_session_effect_budgets WHERE session_id = 'agent_one'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_RUN_AUTHORIZATION_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_run_authorizations SET actor = 'changed' WHERE authorization_id = 'auth_one'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_RUN_AUTHORIZATION_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_run_authorizations WHERE authorization_id = 'auth_one'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_BOUND_RUN_DELETE_FORBIDDEN"):
            connection.execute("DELETE FROM runs WHERE run_id = 'run_one'")

        _insert_authorization_parents(connection, suffix="two")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            _insert_effect_budget(connection, suffix="two", max_run_submissions=0)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            _insert_authorization(connection, suffix="two", run_id="run_one")

        _insert_authorization_parents(connection, suffix="three")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            _insert_authorization(connection, suffix="three", run_id="run_missing")


def test_current_schema_contract_detects_missing_v19_foreign_key(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute("DROP TABLE agent_session_effect_budgets")
        connection.execute(
            """
            CREATE TABLE agent_session_effect_budgets (
                session_id TEXT PRIMARY KEY,
                contract_version TEXT NOT NULL,
                max_run_submissions INTEGER NOT NULL,
                actor TEXT NOT NULL,
                request_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                command_hash TEXT NOT NULL,
                receipt_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        ensure_agent_run_authorization_schema(connection)
        missing = missing_required_schema_objects(connection)

    assert (
        "foreign-key:agent_session_effect_budgets.session_id->agent_sessions.session_id:RESTRICT"
        in missing
    )


def _downgrade_to_v18(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER agent_bound_runs_no_delete")
        connection.execute("DROP TABLE agent_run_authorizations")
        connection.execute("DROP TABLE agent_session_effect_budgets")
        connection.execute("DELETE FROM schema_migrations WHERE version = 19")
        connection.execute("PRAGMA user_version = 18")


def _v19_schema_snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    placeholders = ",".join("?" for _ in V19_OBJECTS)
    objects = [
        (str(row[0]), str(row[1]), " ".join(str(row[2]).split()))
        for row in connection.execute(
            f"SELECT type, name, sql FROM sqlite_master WHERE name IN ({placeholders}) ORDER BY type, name",
            tuple(sorted(V19_OBJECTS)),
        ).fetchall()
    ]
    foreign_keys = {
        table_name: sorted(
            (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
            for row in connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        )
        for table_name in V19_TABLES
    }
    return {"objects": objects, "foreignKeys": foreign_keys}


def _insert_reserved_namespace_collision(connection: sqlite3.Connection, table_name: str) -> None:
    server_id = "agent-control-plane.v1"
    if table_name == "runs":
        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
                status, stage, state_version, message, result_dir, last_updated_at,
                request_id, submitted_at, run_spec_json
            ) VALUES (
                'legacy_run', ?, 'project', 'pipeline', '1.0.0', '2026-04-21',
                'queued', 'queued', 1, 'queued', '', '2099-01-01T00:00:00Z',
                'legacy-request', '2099-01-01T00:00:00Z', '{}'
            )
            """,
            (server_id,),
        )
        return
    if table_name == "idempotency":
        connection.execute(
            """
            INSERT INTO idempotency (
                server_id, idempotency_key, canonical_payload_hash, run_id, status
            ) VALUES (?, 'legacy-idem', 'legacy-hash', 'legacy-run', 'accepted')
            """,
            (server_id,),
        )
        return
    connection.execute(
        """
        INSERT INTO workflow_triggers (
            trigger_id, name, source_type, server_id, pipeline_id,
            run_spec_template_json, created_at, updated_at
        ) VALUES (
            'legacy-trigger', 'legacy', 'schedule', ?, 'pipeline', '{}',
            '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z'
        )
        """,
        (server_id,),
    )


def _insert_authorization_parents(connection: sqlite3.Connection, *, suffix: str) -> None:
    session_id = f"agent_{suffix}"
    plan_revision_id = f"plan_{suffix}"
    workflow_revision_id = f"wfrev_{suffix}"
    run_id = f"run_{suffix}"
    timestamp = "2099-01-01T00:00:00Z"
    connection.execute(
        """
        INSERT INTO agent_sessions (
            session_id, contract_version, project_id, goal_json, constraints_json, budget_json,
            status, state_version, plan_generation, active_plan_hash, workflow_revision_id,
            creation_request_id, creation_request_hash, created_by, created_at, updated_at
        ) VALUES (?, 'agent-session.v1', 'project', '{}', '{}', '{}', 'ready_to_run',
                  4, 1, ?, ?, ?, ?, 'user', ?, ?)
        """,
        (
            session_id,
            f"plan-hash-{suffix}",
            workflow_revision_id,
            f"create-{suffix}",
            f"create-hash-{suffix}",
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_plan_revisions (
            plan_revision_id, contract_version, session_id, plan_generation, draft_id,
            draft_revision, plan_hash, proposal_json, validation_json, budget_json,
            created_by, created_at
        ) VALUES (?, 'agent-plan-revision.v1', ?, 1, ?, 1, ?, '{}', '{}', '{}', 'user', ?)
        """,
        (plan_revision_id, session_id, f"draft-{suffix}", f"plan-hash-{suffix}", timestamp),
    )
    connection.execute(
        """
        INSERT INTO workflow_revisions (
            workflow_revision_id, draft_id, draft_revision, content_hash, manifest_json,
            graph_snapshot_json, runtime_lock_json, compiler_json, created_by, created_at
        ) VALUES (?, ?, 1, ?, '{}', '{}', '{}', '{}', 'user', ?)
        """,
        (workflow_revision_id, f"draft-{suffix}", f"content-hash-{suffix}", timestamp),
    )
    connection.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
            workflow_revision_id, status, stage, state_version, message, result_dir,
            last_updated_at, request_id, submitted_at, run_spec_json
        ) VALUES (?, 'agent-control-plane.v1', 'project', 'pipeline', '1.0.0', '2026-04-21',
                  ?, 'queued', 'queued', 1, 'queued', '', ?, ?, ?, '{}')
        """,
        (run_id, workflow_revision_id, timestamp, f"run-request-{suffix}", timestamp),
    )


def _insert_effect_budget(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    max_run_submissions: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO agent_session_effect_budgets (
            session_id, contract_version, max_run_submissions, actor, request_id,
            idempotency_key, command_hash, receipt_hash, created_at
        ) VALUES (?, 'agent-session-effect-budget.v1', ?, 'user', ?, ?, ?, ?, '2099-01-01T00:00:00Z')
        """,
        (
            f"agent_{suffix}",
            max_run_submissions,
            f"budget-request-{suffix}",
            f"budget-idem-{suffix}",
            f"budget-command-{suffix}",
            f"budget-receipt-{suffix}",
        ),
    )


def _insert_authorization(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    run_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO agent_run_authorizations (
            authorization_id, contract_version, session_id, preview_hash, plan_revision_id,
            plan_generation, plan_hash, workflow_revision_id, expected_state_version,
            input_manifest_digest, run_spec_hash, execution_policy_id, execution_policy_hash,
            runtime_lock_hash, runtime_proof_hash, effect_budget_hash, run_id, scope,
            confirmation, actor, request_id, idempotency_key, command_hash, receipt_hash, created_at
        ) VALUES (
            ?, 'agent-run-authorization.v1', ?, ?, ?, 1, ?, ?, 4, ?, ?, ?, ?, ?, ?, ?, ?,
            'submit_workflow_run', 'authorize-workflow-run', 'user', ?, ?, ?, ?,
            '2099-01-01T00:00:00Z'
        )
        """,
        (
            f"auth_{suffix}",
            f"agent_{suffix}",
            f"preview-{suffix}",
            f"plan_{suffix}",
            f"plan-hash-{suffix}",
            f"wfrev_{suffix}",
            f"manifest-{suffix}",
            f"run-spec-{suffix}",
            "policy-v1",
            f"policy-hash-{suffix}",
            f"runtime-lock-{suffix}",
            f"runtime-proof-{suffix}",
            f"effect-budget-{suffix}",
            run_id or f"run_{suffix}",
            f"auth-request-{suffix}",
            f"auth-idem-{suffix}",
            f"auth-command-{suffix}",
            f"auth-receipt-{suffix}",
        ),
    )
