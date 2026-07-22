from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.agent_process_instance_schema import (
    AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH,
)
from apps.remote_runner.agent_process_instance_v23_schema import (
    AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,
    AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED,
    AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH,
    assert_agent_process_instance_v23_schema,
)
from apps.remote_runner.sqlite_migrations import (
    CURRENT_SCHEMA_MIGRATION_NAME,
    CURRENT_SCHEMA_VERSION,
    ensure_runtime_schema_current,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.sqlite_schema_checksums import (
    V22_SCHEMA_MIGRATION_NAME,
    V22_SCHEMA_VERSION,
    V23_SCHEMA_MIGRATION_NAME,
    V23_SCHEMA_VERSION,
    runtime_schema_ledger_checksum,
)
from tests.agent_process_instance_schema_fixtures import (
    connection as process_connection,
    insert_prepared,
    seed_intent,
    start,
)
from tests.helpers.reference_database import make_remote_runner_config


_EXPECTED_V22_LEDGER_CHECKSUM = (
    "43e3c4345671f06dcf410e9a0bf8eff6ebffbe8611b87e61dd9fbdbee77f71d1"
)


def test_v22_prepared_only_database_migrates_to_exact_v23(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    _downgrade_to_v22(db_path)
    with process_connection(db_path) as connection:
        intent = seed_intent(connection, tag="legacy-prepared")
        insert_prepared(connection, intent)

    initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 23
        ledger = connection.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 23"
        ).fetchone()
        prepared = connection.execute(
            "SELECT process_instance_id, state FROM agent_process_instances"
        ).fetchone()
        assert_agent_process_instance_v23_schema(connection)
    assert prepared == (intent["process_instance_id"], "prepared")
    assert ledger == (
        V23_SCHEMA_MIGRATION_NAME,
        runtime_schema_ledger_checksum(
            V23_SCHEMA_VERSION,
            V23_SCHEMA_MIGRATION_NAME,
        ),
    )
    assert CURRENT_SCHEMA_VERSION == V23_SCHEMA_VERSION
    assert CURRENT_SCHEMA_MIGRATION_NAME == V23_SCHEMA_MIGRATION_NAME


def test_v23_migration_rejects_old_unverified_started_history_atomically(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    _downgrade_to_v22(db_path)
    with process_connection(db_path) as connection:
        intent = seed_intent(connection, tag="legacy-started")
        insert_prepared(connection, intent)
        start(connection, intent)

    with pytest.raises(
        RuntimeError,
        match=re.escape(AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED),
    ):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 22
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 23"
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT state FROM agent_process_instances"
        ).fetchone() == ("started",)
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ?",
                (AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,),
            ).fetchone()
            is None
        )


def test_v23_migration_rejects_preexisting_target_trigger_without_writes(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    _downgrade_to_v22(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"CREATE TRIGGER {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME} "
            "BEFORE UPDATE ON agent_process_instances BEGIN SELECT 1; END"
        )

    with pytest.raises(
        RuntimeError,
        match=re.escape(AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH),
    ):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 22
        assert (
            connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 23"
            ).fetchone()
            is None
        )


def test_current_readiness_rejects_forged_v23_trigger_sql(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"DROP TRIGGER {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}")
        connection.execute(
            f"CREATE TRIGGER {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME} "
            "BEFORE UPDATE ON agent_process_instances BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=re.escape(AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH),
        ):
            assert_agent_process_instance_v23_schema(connection)
        with pytest.raises(
            RuntimeError,
            match=re.escape(AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH),
        ):
            ensure_runtime_schema_current(connection)


def test_v22_checksum_remains_exact_after_v23_becomes_current(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        stored = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 22"
        ).fetchone()[0]
    assert stored == _EXPECTED_V22_LEDGER_CHECKSUM
    assert (
        runtime_schema_ledger_checksum(
            V22_SCHEMA_VERSION,
            V22_SCHEMA_MIGRATION_NAME,
        )
        == _EXPECTED_V22_LEDGER_CHECKSUM
    )


def _downgrade_to_v22(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"DROP TRIGGER {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 23")
        connection.execute("PRAGMA user_version = 22")
