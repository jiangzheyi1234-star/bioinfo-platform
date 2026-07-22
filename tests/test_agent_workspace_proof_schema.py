from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import agent_workspace_proof_schema
from apps.remote_runner.agent_workspace_proof_schema import (
    AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH,
    ensure_agent_workspace_proof_schema,
)
from apps.remote_runner.sqlite_migrations import (
    AGENT_PROCESS_INSTANCE_MIGRATION_NAME,
    AGENT_RUN_AUTHORIZATION_MIGRATION_NAME,
    AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_NAME,
    AGENT_WORKSPACE_PROOF_MIGRATION_NAME,
    CURRENT_SCHEMA_MIGRATION_NAME,
    CURRENT_SCHEMA_VERSION,
    ensure_runtime_schema_current,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.sqlite_schema_contract import missing_required_schema_objects
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_remote_runner_config


V20_OBJECTS = frozenset(
    {
        "agent_workspace_proofs",
        "idx_agent_workspace_proofs_authorization",
        "idx_agent_workspace_proofs_run_boundary",
        "agent_workspace_proofs_no_delete",
        "agent_workspace_proofs_no_update",
    }
)


def test_fresh_current_records_agent_migrations_and_exposes_workspace_proof_schema(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)

    initialize_or_migrate_runtime_db(cfg.db_path)

    with get_connection(cfg) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == CURRENT_SCHEMA_VERSION
            == 23
        )
        ledger = connection.execute(
            "SELECT version, name FROM schema_migrations "
            "WHERE version IN (19, 20, 21, 22, 23) ORDER BY version"
        ).fetchall()
        objects = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN ({})".format(
                    ",".join("?" for _ in V20_OBJECTS)
                ),
                tuple(sorted(V20_OBJECTS)),
            ).fetchall()
        }
        foreign_keys = _workspace_proof_foreign_keys(connection)

    assert [tuple(row) for row in ledger] == [
        (19, AGENT_RUN_AUTHORIZATION_MIGRATION_NAME),
        (20, AGENT_WORKSPACE_PROOF_MIGRATION_NAME),
        (21, AGENT_PROCESS_INSTANCE_MIGRATION_NAME),
        (22, AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_NAME),
        (23, CURRENT_SCHEMA_MIGRATION_NAME),
    ]
    assert objects == V20_OBJECTS
    assert foreign_keys == {
        ("attempt_id", "run_attempts", "attempt_id", "RESTRICT"),
        (
            "authorization_id",
            "agent_run_authorizations",
            "authorization_id",
            "RESTRICT",
        ),
        ("run_id", "runs", "run_id", "RESTRICT"),
        ("source_attempt_id", "run_attempts", "attempt_id", "RESTRICT"),
        (
            "workflow_revision_id",
            "workflow_revisions",
            "workflow_revision_id",
            "RESTRICT",
        ),
    }


def test_workspace_proof_readiness_rejects_extra_side_effect_trigger(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER forged_workspace_side_effect "
            "AFTER INSERT ON agent_workspace_proofs BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: "
                r"triggers:agent_workspace_proofs$"
            ),
        ):
            agent_workspace_proof_schema.assert_agent_workspace_proof_schema(connection)


def test_v19_to_current_workspace_schema_matches_fresh_schema(tmp_path: Path) -> None:
    fresh_cfg = make_remote_runner_config(tmp_path / "fresh")
    migrated_cfg = make_remote_runner_config(tmp_path / "migrated")
    initialize_or_migrate_runtime_db(fresh_cfg.db_path)
    initialize_or_migrate_runtime_db(migrated_cfg.db_path)
    _downgrade_to_v19(Path(migrated_cfg.db_path))

    initialize_or_migrate_runtime_db(migrated_cfg.db_path)

    with sqlite3.connect(fresh_cfg.db_path) as connection:
        fresh = _v20_schema_snapshot(connection)
    with sqlite3.connect(migrated_cfg.db_path) as connection:
        migrated = _v20_schema_snapshot(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        migrations = connection.execute(
            "SELECT version, name FROM schema_migrations "
            "WHERE version IN (20, 21, 22, 23) ORDER BY version"
        ).fetchall()

    assert migrated == fresh
    assert version == 23
    assert migrations == [
        (20, AGENT_WORKSPACE_PROOF_MIGRATION_NAME),
        (21, AGENT_PROCESS_INSTANCE_MIGRATION_NAME),
        (22, AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_NAME),
        (23, CURRENT_SCHEMA_MIGRATION_NAME),
    ]


def test_v19_migration_rolls_back_partial_schema_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    _downgrade_to_v19(Path(cfg.db_path))

    def fail_after_partial_ddl(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE v20_partial_write (value TEXT NOT NULL)")
        raise RuntimeError("forced v20 schema failure")

    monkeypatch.setattr(
        agent_workspace_proof_schema,
        "ensure_agent_workspace_proof_schema",
        fail_after_partial_ddl,
    )

    with pytest.raises(RuntimeError, match="forced v20 schema failure"):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 20"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'v20_partial_write'"
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'agent_workspace_proofs'"
            ).fetchone()
            is None
        )


def test_v19_migration_rejects_malformed_preexisting_table_atomically(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    _downgrade_to_v19(Path(cfg.db_path))
    with sqlite3.connect(cfg.db_path) as connection:
        _create_unconstrained_workspace_proof_table(connection)

    with pytest.raises(
        RuntimeError,
        match=rf"{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: object-sql:agent_workspace_proofs",
    ):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 20"
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM pragma_index_list('agent_workspace_proofs')"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = 'agent_workspace_proofs'"
        ).fetchone() == (0,)


def test_v19_migration_rejects_wrong_preexisting_index_definition_atomically(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    _downgrade_to_v19(Path(cfg.db_path))
    with sqlite3.connect(cfg.db_path) as connection:
        ensure_agent_workspace_proof_schema(connection)
        connection.execute("DROP INDEX idx_agent_workspace_proofs_authorization")
        connection.execute(
            "CREATE INDEX idx_agent_workspace_proofs_authorization "
            "ON agent_workspace_proofs(run_id, process_ordinal)"
        )

    with pytest.raises(
        RuntimeError,
        match=(
            rf"{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: "
            "object-sql:idx_agent_workspace_proofs_authorization"
        ),
    ):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 20"
            ).fetchone()
            is None
        )
        index_columns = connection.execute(
            "SELECT name FROM pragma_index_info("
            "'idx_agent_workspace_proofs_authorization') ORDER BY seqno"
        ).fetchall()
    assert index_columns == [("run_id",), ("process_ordinal",)]


def test_fresh_schema_rejects_malformed_preexisting_table_before_ledger_commit(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cfg.db_path) as connection:
        _create_unconstrained_workspace_proof_table(connection)

    with pytest.raises(
        RuntimeError,
        match=rf"{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: object-sql:agent_workspace_proofs",
    ):
        initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM pragma_index_list('agent_workspace_proofs')"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = 'agent_workspace_proofs'"
        ).fetchone() == (0,)


def test_current_schema_readiness_rejects_wrong_workspace_index(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute("DROP INDEX idx_agent_workspace_proofs_authorization")
        connection.execute(
            "CREATE INDEX idx_agent_workspace_proofs_authorization "
            "ON agent_workspace_proofs(run_id, process_ordinal)"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: "
                "object-sql:idx_agent_workspace_proofs_authorization"
            ),
        ):
            ensure_runtime_schema_current(connection)


def test_workspace_proof_constraints_uniqueness_and_immutability(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)

    with get_connection(cfg) as connection:
        _insert_workspace_proof_parents(connection)
        _insert_workspace_proof(connection)

        with pytest.raises(
            sqlite3.IntegrityError, match="AGENT_WORKSPACE_PROOF_IMMUTABLE"
        ):
            connection.execute(
                "UPDATE agent_workspace_proofs SET created_at = 'changed' "
                "WHERE workspace_proof_id = 'proof_one'"
            )
        with pytest.raises(
            sqlite3.IntegrityError, match="AGENT_WORKSPACE_PROOF_IMMUTABLE"
        ):
            connection.execute(
                "DELETE FROM agent_workspace_proofs WHERE workspace_proof_id = 'proof_one'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            _insert_workspace_proof(
                connection, workspace_proof_id="proof_duplicate_ordinal"
            )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            _insert_workspace_proof(
                connection,
                workspace_proof_id="proof_duplicate_hash",
                process_ordinal=2,
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            _insert_workspace_proof(
                connection,
                workspace_proof_id="proof_bad_boundary",
                process_ordinal=2,
                process_boundary="resume",
                proof_hash="proof-hash-bad-boundary",
                event_id="event-bad-boundary",
            )
        with pytest.raises(
            sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"
        ):
            _insert_workspace_proof(
                connection,
                workspace_proof_id="proof_missing_source",
                process_ordinal=2,
                source_attempt_id="attempt_missing",
                proof_hash="proof-hash-missing-source",
                event_id="event-missing-source",
            )


def test_schema_contract_detects_missing_workspace_proof_foreign_key(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute("DROP TABLE agent_process_instances")
        connection.execute("DROP TABLE agent_workspace_proofs")
        connection.execute(
            """
            CREATE TABLE agent_workspace_proofs (
                workspace_proof_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                authorization_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                source_attempt_id TEXT,
                process_boundary TEXT NOT NULL,
                process_ordinal INTEGER NOT NULL,
                workflow_revision_id TEXT NOT NULL
            )
            """
        )
        ensure_agent_workspace_proof_schema(connection)
        missing = missing_required_schema_objects(connection)

    assert (
        "foreign-key:agent_workspace_proofs.source_attempt_id->run_attempts.attempt_id:RESTRICT"
        in missing
    )


def _downgrade_to_v19(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER agent_process_instances_run_events_no_update")
        connection.execute("DROP TRIGGER agent_process_instances_run_events_no_delete")
        connection.execute("DROP TABLE agent_process_instances")
        connection.execute("DROP TABLE agent_workspace_proofs")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN (20, 21, 22, 23)"
        )
        connection.execute("PRAGMA user_version = 19")


def _create_unconstrained_workspace_proof_table(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TABLE agent_workspace_proofs (
            workspace_proof_id TEXT PRIMARY KEY,
            contract_version TEXT NOT NULL,
            run_id TEXT NOT NULL,
            authorization_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            lease_generation INTEGER NOT NULL,
            source_attempt_id TEXT,
            process_boundary TEXT NOT NULL,
            process_ordinal INTEGER NOT NULL,
            workflow_revision_id TEXT NOT NULL,
            workflow_revision_content_hash TEXT NOT NULL,
            workflow_revision_manifest_hash TEXT NOT NULL,
            run_spec_hash TEXT NOT NULL,
            input_snapshot_hash TEXT NOT NULL,
            tool_assets_hash TEXT NOT NULL,
            runtime_lock_hash TEXT NOT NULL,
            runtime_proof_hash TEXT NOT NULL,
            immutable_manifest_json TEXT NOT NULL,
            immutable_manifest_hash TEXT NOT NULL,
            snakemake_manifest_json TEXT NOT NULL,
            snakemake_manifest_hash TEXT NOT NULL,
            previous_proof_hash TEXT,
            event_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            proof_hash TEXT NOT NULL
        )
        """
    )


def _v20_schema_snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    placeholders = ",".join("?" for _ in V20_OBJECTS)
    objects = [
        (str(row[0]), str(row[1]), " ".join(str(row[2]).split()))
        for row in connection.execute(
            f"SELECT type, name, sql FROM sqlite_master WHERE name IN ({placeholders}) "
            "ORDER BY type, name",
            tuple(sorted(V20_OBJECTS)),
        ).fetchall()
    ]
    return {
        "objects": objects,
        "foreignKeys": sorted(_workspace_proof_foreign_keys(connection)),
    }


def _workspace_proof_foreign_keys(
    connection: sqlite3.Connection,
) -> set[tuple[str, ...]]:
    return {
        (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
        for row in connection.execute(
            "PRAGMA foreign_key_list(agent_workspace_proofs)"
        ).fetchall()
    }


def _insert_workspace_proof_parents(connection: sqlite3.Connection) -> None:
    timestamp = "2099-01-01T00:00:00Z"
    connection.execute(
        """
        INSERT INTO agent_sessions (
            session_id, contract_version, project_id, goal_json, constraints_json, budget_json,
            status, state_version, plan_generation, active_plan_hash, workflow_revision_id,
            creation_request_id, creation_request_hash, created_by, created_at, updated_at
        ) VALUES (
            'agent_one', 'agent-session.v1', 'project', '{}', '{}', '{}', 'ready_to_run',
            4, 1, 'plan-hash', 'wfrev_one', 'create-one', 'create-hash', 'user', ?, ?
        )
        """,
        (timestamp, timestamp),
    )
    connection.execute(
        """
        INSERT INTO agent_plan_revisions (
            plan_revision_id, contract_version, session_id, plan_generation, draft_id,
            draft_revision, plan_hash, proposal_json, validation_json, budget_json,
            created_by, created_at
        ) VALUES (
            'plan_one', 'agent-plan-revision.v1', 'agent_one', 1, 'draft-one', 1,
            'plan-hash', '{}', '{}', '{}', 'user', ?
        )
        """,
        (timestamp,),
    )
    connection.execute(
        """
        INSERT INTO workflow_revisions (
            workflow_revision_id, draft_id, draft_revision, content_hash, manifest_json,
            graph_snapshot_json, runtime_lock_json, compiler_json, created_by, created_at
        ) VALUES ('wfrev_one', 'draft-one', 1, 'content-hash', '{}', '{}', '{}', '{}', 'user', ?)
        """,
        (timestamp,),
    )
    connection.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
            workflow_revision_id, status, stage, state_version, message, result_dir,
            last_updated_at, request_id, submitted_at, run_spec_json
        ) VALUES (
            'run_one', 'agent-control-plane.v1', 'project', 'pipeline', '1.0.0', '2026-04-21',
            'wfrev_one', 'running', 'running', 2, 'running', '', ?, 'run-request', ?, '{}'
        )
        """,
        (timestamp, timestamp),
    )
    connection.execute(
        """
        INSERT INTO agent_run_authorizations (
            authorization_id, contract_version, session_id, preview_hash, plan_revision_id,
            plan_generation, plan_hash, workflow_revision_id, expected_state_version,
            input_manifest_digest, run_spec_hash, execution_policy_id, execution_policy_hash,
            runtime_lock_hash, runtime_proof_hash, effect_budget_hash, run_id, scope,
            confirmation, actor, request_id, idempotency_key, command_hash, receipt_hash, created_at
        ) VALUES (
            'auth_one', 'agent-run-authorization.v1', 'agent_one', 'preview-hash', 'plan_one',
            1, 'plan-hash', 'wfrev_one', 4, 'input-manifest', 'run-spec-hash', 'policy-v1',
            'policy-hash', 'runtime-lock-hash', 'runtime-proof-hash', 'budget-hash', 'run_one',
            'submit_workflow_run', 'authorize-workflow-run', 'user', 'auth-request',
            'auth-idempotency', 'auth-command', 'auth-receipt', ?
        )
        """,
        (timestamp,),
    )
    connection.executemany(
        """
        INSERT INTO run_attempts (
            attempt_id, run_id, job_id, lease_generation, state, worker_id, work_dir,
            created_at, updated_at
        ) VALUES (?, 'run_one', 'job_one', ?, 'running', 'worker', ?, ?, ?)
        """,
        [
            ("attempt_source", 1, "source-work", timestamp, timestamp),
            ("attempt_one", 2, "current-work", timestamp, timestamp),
        ],
    )


def _insert_workspace_proof(
    connection: sqlite3.Connection,
    *,
    workspace_proof_id: str = "proof_one",
    process_ordinal: int = 1,
    process_boundary: str = "pre_dry_run",
    source_attempt_id: str | None = "attempt_source",
    proof_hash: str = "proof-hash",
    event_id: str = "event-one",
) -> None:
    connection.execute(
        """
        INSERT INTO agent_workspace_proofs (
            workspace_proof_id, contract_version, run_id, authorization_id, attempt_id,
            lease_generation, source_attempt_id, process_boundary, process_ordinal,
            workflow_revision_id, workflow_revision_content_hash,
            workflow_revision_manifest_hash, run_spec_hash, input_snapshot_hash,
            tool_assets_hash, runtime_lock_hash, runtime_proof_hash, immutable_manifest_json,
            immutable_manifest_hash, snakemake_manifest_json, snakemake_manifest_hash,
            previous_proof_hash, event_id, created_at, proof_hash
        ) VALUES (
            ?, 'agent-workspace-proof.v1', 'run_one', 'auth_one', 'attempt_one', 2, ?, ?, ?,
            'wfrev_one', 'content-hash', 'revision-manifest-hash', 'run-spec-hash',
            'input-snapshot-hash', 'tool-assets-hash', 'runtime-lock-hash',
            'runtime-proof-hash', '{}', 'immutable-manifest-hash', '{}',
            'snakemake-manifest-hash', NULL, ?, '2099-01-01T00:00:00Z', ?
        )
        """,
        (
            workspace_proof_id,
            source_attempt_id,
            process_boundary,
            process_ordinal,
            event_id,
            proof_hash,
        ),
    )
