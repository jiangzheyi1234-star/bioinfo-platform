from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import sqlite_migrations
from apps.remote_runner.agent_process_instance_schema import (
    migrate_agent_process_instance_schema,
)
from apps.remote_runner.sqlite_migrations import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_LEDGER_AHEAD_ERROR,
    SCHEMA_LEDGER_CHECKSUM_ERROR,
    SCHEMA_LEDGER_HISTORY_ERROR,
    RemoteRunnerSQLiteSchemaError,
    initialize_or_migrate_runtime_db,
)
from tests.agent_process_instance_schema_fixtures import downgrade_process_schema
from tests.helpers.reference_database import make_remote_runner_config


@pytest.mark.parametrize(
    ("sql", "parameters", "expected_error"),
    [
        (
            "DELETE FROM schema_migrations WHERE version = 21",
            (),
            SCHEMA_LEDGER_HISTORY_ERROR,
        ),
        (
            "UPDATE schema_migrations SET checksum = ? WHERE version = 21",
            ("0" * 64,),
            SCHEMA_LEDGER_CHECKSUM_ERROR,
        ),
        (
            "UPDATE schema_migrations SET name = 'forged' WHERE version = 22",
            (),
            SCHEMA_LEDGER_HISTORY_ERROR,
        ),
        (
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (24, '024_future', 'future', '2099-01-01T00:00:00Z')
            """,
            (),
            SCHEMA_LEDGER_AHEAD_ERROR,
        ),
        (
            "DELETE FROM schema_migrations WHERE version = 17",
            (),
            SCHEMA_LEDGER_HISTORY_ERROR,
        ),
        (
            "UPDATE schema_migrations SET applied_at = '' WHERE version = 18",
            (),
            SCHEMA_LEDGER_HISTORY_ERROR,
        ),
        (
            """
            CREATE TRIGGER forged_schema_ledger_trigger
            AFTER INSERT ON schema_migrations BEGIN SELECT 1; END
            """,
            (),
            SCHEMA_LEDGER_HISTORY_ERROR,
        ),
    ],
    ids=[
        "missing-v21",
        "forged-v21-checksum",
        "forged-v22-name",
        "future-v24",
        "history-gap",
        "blank-applied-at",
        "ledger-trigger",
    ],
)
def test_current_schema_rejects_incoherent_ledger(
    tmp_path: Path,
    sql: str,
    parameters: tuple[str, ...],
    expected_error: str,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(sql, parameters)

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=re.escape(expected_error),
    ):
        initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == CURRENT_SCHEMA_VERSION
        )


def test_fresh_schema_has_continuous_agent_era_ledger(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        rows = connection.execute(
            "SELECT version, name FROM schema_migrations WHERE version >= 15 ORDER BY version"
        ).fetchall()

    assert [row[0] for row in rows] == list(range(15, 24))
    assert rows[-3:] == [
        (21, "021_agent_process_instance"),
        (22, "022_agent_workspace_tool_assets_binding"),
        (23, "023_agent_process_lifecycle"),
    ]


def test_migration_record_conflict_never_replaces_history() -> None:
    with sqlite3.connect(":memory:") as connection:
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (22, 'forged', 'forged', '2099-01-01T00:00:00Z')
            """
        )
        before = connection.execute(
            "SELECT name, checksum, applied_at FROM schema_migrations WHERE version = 22"
        ).fetchone()

        with pytest.raises(sqlite3.IntegrityError):
            sqlite_migrations._record_migration(
                connection,
                22,
                "022_agent_workspace_tool_assets_binding",
            )

        assert (
            connection.execute(
                "SELECT name, checksum, applied_at FROM schema_migrations WHERE version = 22"
            ).fetchone()
            == before
        )


def test_agent_era_source_history_gap_is_rejected_before_writing(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    downgrade_process_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN (17, 18, 19)"
        )
        ledger_before = connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        schema_before = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=re.escape(SCHEMA_LEDGER_HISTORY_ERROR),
    ):
        initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 20
        assert (
            connection.execute(
                "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            == ledger_before
        )
        assert (
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            == schema_before
        )


def test_v21_migration_rejects_ledger_trigger_without_partial_v22(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    downgrade_process_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        migrate_agent_process_instance_schema(
            connection,
            record_migration=sqlite_migrations._record_migration,
        )
        connection.execute(
            """
            CREATE TRIGGER corrupt_v22_ledger
            AFTER INSERT ON schema_migrations WHEN NEW.version = 22
            BEGIN
                UPDATE schema_migrations SET checksum = 'forged' WHERE version = 22;
            END
            """
        )

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=re.escape(SCHEMA_LEDGER_HISTORY_ERROR),
    ):
        initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 22"
            ).fetchone()
            is None
        )


def test_v0_empty_ledger_namespace_must_be_canonical(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        sqlite_migrations._ensure_schema_migrations_table(connection)
        connection.execute(
            """
            CREATE TRIGGER forged_empty_ledger_trigger
            AFTER INSERT ON schema_migrations BEGIN SELECT 1; END
            """
        )

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=re.escape(SCHEMA_LEDGER_HISTORY_ERROR),
    ):
        initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runs'"
            ).fetchone()
            is None
        )
