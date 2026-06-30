from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.remote_runner import sqlite_migrations
from apps.remote_runner.database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from apps.remote_runner.sqlite_migrations import CURRENT_SCHEMA_VERSION, initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage_schema import SCHEMA_SQL
from tests.helpers.reference_database import make_remote_runner_config


def test_runtime_schema_migrates_v16_artifact_lifecycle_policy_table(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(f"{SCHEMA_SQL}\n{REFERENCE_DATABASE_SCHEMA_SQL}")
        sqlite_migrations._apply_baseline_schema_migration(connection)
        connection.execute("DROP TABLE IF EXISTS artifact_lifecycle_policies")
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute("DELETE FROM schema_migrations")
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (16, '016_result_package_retired_at', 'legacy-v16', '2099-06-07T10:00:00Z')
            """
        )
        connection.execute("PRAGMA user_version = 16")

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'artifact_lifecycle_policies'
            """
        ).fetchone()
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

    assert table is not None
    assert migration["name"] == sqlite_migrations.CURRENT_SCHEMA_MIGRATION_NAME
