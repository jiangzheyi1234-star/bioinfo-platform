from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import sqlite_migrations
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.sqlite_migrations import (
    CURRENT_SCHEMA_VERSION,
    RemoteRunnerSQLiteSchemaError,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage_schema import SCHEMA_SQL
from apps.remote_runner.database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from tests.helpers.reference_database import make_remote_runner_config


def test_output_edge_uniqueness_migration_preserves_legacy_duplicates(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(cfg.db_path) as legacy:
        legacy.executescript(SCHEMA_SQL)
        legacy.executemany(
            """
            INSERT INTO run_artifact_edges (
                edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                content_hash, upstream_run_id, created_at
            ) VALUES (?, 'run_legacy', ?, ?, 'report', 'summarize', ?, NULL, ?)
            """,
            [
                ("aredge_first", "ablob_first", "output", "sha256:first", "2099-06-07T10:00:00Z"),
                ("aredge_later", "ablob_later", "output", "sha256:later", "2099-06-07T10:00:01Z"),
                ("aredge_input_1", "ablob_input_1", "input", "sha256:input1", "2099-06-07T10:00:02Z"),
                ("aredge_input_2", "ablob_input_2", "input", "sha256:input2", "2099-06-07T10:00:03Z"),
            ],
        )

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as migrated:
        rows = migrated.execute(
            """
            SELECT edge_id, role, port_name
            FROM run_artifact_edges
            WHERE run_id = 'run_legacy'
            ORDER BY created_at, edge_id
            """
        ).fetchall()
        index = migrated.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_run_artifact_edges_adopted_output'
            """
        ).fetchone()

    assert [dict(row) for row in rows] == [
        {"edge_id": "aredge_first", "role": "output", "port_name": "report"},
        {
            "edge_id": "aredge_later",
            "role": "output",
            "port_name": "report#legacy-aredge_later",
        },
        {"edge_id": "aredge_input_1", "role": "input", "port_name": "report"},
        {"edge_id": "aredge_input_2", "role": "input", "port_name": "report"},
    ]
    assert index is not None
    assert "WHERE role = 'output' AND port_name IS NOT NULL" in index["sql"]

    with get_connection(cfg) as replay:
        replayed_port_name = replay.execute(
            "SELECT port_name FROM run_artifact_edges WHERE edge_id = 'aredge_later'"
        ).fetchone()["port_name"]
        with pytest.raises(sqlite3.IntegrityError):
            replay.execute(
                """
                INSERT INTO run_artifact_edges (
                    edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                    content_hash, upstream_run_id, created_at
                ) VALUES (
                    'aredge_rejected', 'run_legacy', 'ablob_rejected', 'output',
                    'report', 'summarize', 'sha256:rejected', NULL, '2099-06-07T10:00:04Z'
                )
                """
            )
    assert replayed_port_name == "report#legacy-aredge_later"


def test_runtime_layout_records_schema_version_and_migration_ledger(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)

    ensure_runtime_layout(cfg)

    with sqlite3.connect(cfg.db_path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        migration = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()
        reference_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'reference_databases'
            """
        ).fetchone()

    assert user_version == CURRENT_SCHEMA_VERSION
    assert migration is not None
    assert migration[0] == CURRENT_SCHEMA_VERSION
    assert migration[1] == sqlite_migrations.RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME
    assert migration[2]
    assert reference_table is not None


def test_runtime_schema_migrates_v1_to_current_scheduler_trigger_tables(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(f"{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        sqlite_migrations._apply_baseline_schema_migration(connection)
        connection.execute("DROP INDEX IF EXISTS idx_run_rule_events_run_rule")
        connection.execute("DROP INDEX IF EXISTS idx_run_rules_run_status")
        connection.execute("DROP TABLE IF EXISTS run_rule_events")
        connection.execute("DROP TABLE IF EXISTS run_rules")
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (1, '001_baseline_remote_runner_schema', 'legacy-v1', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 1")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        table_names = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND (name LIKE 'run_rule%' OR name LIKE 'workflow_trigger%')
                """
            ).fetchall()
        }
        index_names = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND (name LIKE 'idx_run_rule%' OR name LIKE 'idx_workflow_trigger%')
                """
            ).fetchall()
        }
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert user_version == CURRENT_SCHEMA_VERSION
    assert {
        "run_rules",
        "run_rule_events",
        "workflow_triggers",
        "workflow_trigger_events",
        "workflow_trigger_dispatches",
    } <= table_names
    assert {
        "idx_run_rules_run_status",
        "idx_run_rule_events_run_rule",
        "idx_workflow_triggers_source_enabled",
        "idx_workflow_trigger_events_trigger_created",
        "idx_workflow_trigger_dispatches_state",
    } <= index_names
    assert migration["name"] == sqlite_migrations.RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME


def test_runtime_schema_migrates_v2_scheduler_trigger_tables(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(f"{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        sqlite_migrations._apply_baseline_schema_migration(connection)
        connection.execute("DROP INDEX IF EXISTS idx_workflow_trigger_dispatches_run")
        connection.execute("DROP INDEX IF EXISTS idx_workflow_trigger_dispatches_state")
        connection.execute("DROP INDEX IF EXISTS idx_workflow_trigger_events_external")
        connection.execute("DROP INDEX IF EXISTS idx_workflow_trigger_events_trigger_created")
        connection.execute("DROP INDEX IF EXISTS idx_workflow_triggers_source_enabled")
        connection.execute("DROP TABLE IF EXISTS workflow_trigger_dispatches")
        connection.execute("DROP TABLE IF EXISTS workflow_trigger_events")
        connection.execute("DROP TABLE IF EXISTS workflow_triggers")
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (2, '002_rule_level_run_state', 'legacy-v2', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 2")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        trigger_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'workflow_trigger%'"
            ).fetchall()
        }
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert {
        "workflow_triggers",
        "workflow_trigger_events",
        "workflow_trigger_dispatches",
    } <= trigger_tables
    assert migration["name"] == sqlite_migrations.RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME


def test_runtime_schema_migrates_v6_result_package_exports(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(f"{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        sqlite_migrations._apply_baseline_schema_migration(connection)
        connection.execute("DROP INDEX IF EXISTS idx_result_package_exports_result_created")
        connection.execute("DROP INDEX IF EXISTS idx_result_package_exports_run_lifecycle")
        connection.execute("DROP TABLE IF EXISTS result_package_exports")
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (6, '006_backfill_launch', 'legacy-v6', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 6")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'result_package_exports'
            """
        ).fetchone()
        indexes = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND name LIKE 'idx_result_package_exports%'
                """
            ).fetchall()
        }
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert table is not None
    assert {
        "idx_result_package_exports_result_created",
        "idx_result_package_exports_run_lifecycle",
    } <= indexes
    assert migration["name"] == sqlite_migrations.RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME


def test_runtime_schema_migrates_v7_result_package_payload_mode(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(f"{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        sqlite_migrations._apply_baseline_schema_migration(connection)
        connection.execute("DROP TABLE IF EXISTS result_package_exports")
        connection.execute(
            """
            CREATE TABLE result_package_exports (
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
            CREATE INDEX idx_result_package_exports_run_lifecycle
            ON result_package_exports(run_id, lifecycle_state, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_result_package_exports_result_created
            ON result_package_exports(result_id, created_at)
            """
        )
        connection.execute(
            """
            INSERT INTO result_package_exports (
                package_export_id, result_id, run_id, workflow_revision_id,
                package_path, package_uri, size_bytes, sha256, manifest_sha256,
                evidence_event_id, artifact_ids_json, lifecycle_state, created_at
            ) VALUES (
                'rpexp_legacy', 'res_run_legacy', 'run_legacy', 'wfrev_legacy',
                'C:/packages/res_run_legacy.zip', 'file:///C:/packages/res_run_legacy.zip',
                42, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                'ev_legacy', '[]', 'active', '2099-06-07T10:00:00Z'
            )
            """
        )
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (7, '007_result_package_exports', 'legacy-v7', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 7")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(result_package_exports)").fetchall()
        }
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()
        legacy_row = connection.execute(
            """
            SELECT include_artifacts, artifact_payload_mode
            FROM result_package_exports
            WHERE package_export_id = 'rpexp_legacy'
            """
        ).fetchone()

    assert {"include_artifacts", "artifact_payload_mode"} <= columns
    assert legacy_row["include_artifacts"] == 1
    assert legacy_row["artifact_payload_mode"] == "included"
    assert migration["name"] == sqlite_migrations.RESULT_PACKAGE_PAYLOAD_MODE_MIGRATION_NAME


def test_runtime_schema_rejects_future_user_version(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match="REMOTE_RUNNER_SQLITE_SCHEMA_TOO_NEW"):
        get_connection(cfg)


def test_storage_connection_requires_explicit_schema_migration_for_v0_database(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match="REMOTE_RUNNER_SQLITE_SCHEMA_MIGRATION_REQUIRED"):
        get_connection(cfg)

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_runtime_schema_rejects_latest_with_tampered_migration_checksum(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        )

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match="REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_CHECKSUM_MISMATCH"):
        get_connection(cfg)


def test_runtime_schema_rejects_latest_with_missing_baseline_object(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute("DROP TABLE reference_databases")

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match="REMOTE_RUNNER_SQLITE_SCHEMA_OBJECT_MISSING"):
        get_connection(cfg)


def test_runtime_schema_migration_rolls_back_failed_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def fail_baseline(_connection: sqlite3.Connection) -> None:
        raise RuntimeError("forced baseline failure")

    monkeypatch.setattr(sqlite_migrations, "_apply_baseline_schema_migration", fail_baseline)
    with sqlite3.connect(db_path) as connection:
        sqlite_migrations.configure_runtime_connection(connection)
        with pytest.raises(RuntimeError, match="forced baseline failure"):
            sqlite_migrations.migrate_runtime_schema(connection)
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        runs_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'runs'
            """
        ).fetchone()

    assert user_version == 0
    assert runs_table is None
