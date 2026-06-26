from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.remote_runner import sqlite_migrations
from apps.remote_runner.database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from apps.remote_runner.sqlite_migrations import CURRENT_SCHEMA_VERSION, initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage_schema import SCHEMA_SQL
from tests.helpers.reference_database import make_remote_runner_config


def test_runtime_schema_migrates_v15_result_package_retired_at(tmp_path: Path) -> None:
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
                include_artifacts INTEGER NOT NULL DEFAULT 1,
                artifact_payload_mode TEXT NOT NULL DEFAULT 'included',
                lifecycle_state TEXT NOT NULL DEFAULT 'active',
                package_bytes_state TEXT NOT NULL DEFAULT 'available',
                package_bytes_deleted_at TEXT,
                package_bytes_gc_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(result_id, sha256, manifest_sha256)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO result_package_exports (
                package_export_id, result_id, run_id, workflow_revision_id,
                package_path, package_uri, size_bytes, sha256, manifest_sha256,
                evidence_event_id, artifact_ids_json, include_artifacts,
                artifact_payload_mode, lifecycle_state, package_bytes_state, created_at
            ) VALUES (
                'rpexp_retired_at', 'res_run_retired_at', 'run_retired_at', 'wfrev_legacy',
                'C:/packages/res_run_retired_at.zip', 'file:///C:/packages/res_run_retired_at.zip',
                42, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                'ev_legacy', '[]', 1, 'included', 'retired', 'available', '2099-06-07T10:00:00Z'
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
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (15, '015_artifact_ledger_invalidation', 'legacy-v15', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 15")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(result_package_exports)").fetchall()
        }
        row = connection.execute(
            """
            SELECT retired_at
            FROM result_package_exports
            WHERE package_export_id = 'rpexp_retired_at'
            """
        ).fetchone()
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert "retired_at" in columns
    assert row["retired_at"] is None
    assert migration["name"] == sqlite_migrations.RESULT_PACKAGE_RETIRED_AT_MIGRATION_NAME
