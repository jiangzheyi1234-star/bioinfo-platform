from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from pathlib import Path
import threading

import pytest

from apps.remote_runner import sqlite_migrations, sqlite_schema_contract
from apps.remote_runner.sqlite_migrations import (
    CURRENT_SCHEMA_VERSION,
    RemoteRunnerSQLiteSchemaError,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.sqlite_tool_prepare_migrations import (
    TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX,
    TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX,
    TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR,
    TOOL_PREPARE_ATTEMPT_TABLE,
    assert_tool_prepare_attempt_schema,
)
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_worker_lease import tool_prepare_worker_activity
from tests.helpers.reference_database import make_remote_runner_config


EXPECTED_ATTEMPT_COLUMNS = {
    "attempt_id",
    "job_id",
    "generation",
    "state",
    "outcome_status",
    "worker_id",
    "session_id",
    "process_pid",
    "hostname",
    "process_instance_id",
    "process_marker_schema",
    "process_marker_json",
    "process_marker_fingerprint",
    "claim_owner",
    "claim_token_hash",
    "claimed_at",
    "heartbeat_at",
    "lease_expires_at",
    "released_at",
    "created_at",
    "updated_at",
    "last_error_json",
    "recovery_evidence_json",
}


def test_initialization_adds_schema_neutral_attempt_ledger(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    expected_checksum = sqlite_migrations._baseline_checksum()

    initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        connection.row_factory = sqlite3.Row
        user_version, ledger = _core_ledger(connection)
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({TOOL_PREPARE_ATTEMPT_TABLE})").fetchall()
        }
        indexes = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA index_list({TOOL_PREPARE_ATTEMPT_TABLE})").fetchall()
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (TOOL_PREPARE_ATTEMPT_TABLE,),
            ).fetchone()["sql"]
        )
        assert_tool_prepare_attempt_schema(connection)
        sqlite_migrations._assert_current_schema_contract(connection)

    assert user_version == CURRENT_SCHEMA_VERSION
    assert ledger == (
        CURRENT_SCHEMA_VERSION,
        sqlite_migrations.CURRENT_SCHEMA_MIGRATION_NAME,
        expected_checksum,
    )
    assert EXPECTED_ATTEMPT_COLUMNS <= columns
    assert {TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX, TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX} <= indexes
    assert "FOREIGN KEY" not in table_sql.upper()
    assert TOOL_PREPARE_ATTEMPT_TABLE not in sqlite_schema_contract.REQUIRED_TABLES
    assert TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX not in sqlite_schema_contract.REQUIRED_INDEXES
    assert TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX not in sqlite_schema_contract.REQUIRED_INDEXES


def test_existing_v18_gets_sidecar_without_core_ledger_changes(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        sqlite_migrations.configure_runtime_connection(connection)
        sqlite_migrations.migrate_runtime_schema(connection)
        before = _core_ledger(connection)
        assert _schema_object(connection, "table", TOOL_PREPARE_ATTEMPT_TABLE) is None

    initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        after = _core_ledger(connection)
        assert_tool_prepare_attempt_schema(connection)

    assert before == after
    assert after[0] == CURRENT_SCHEMA_VERSION
    assert after[1][2] == sqlite_migrations._baseline_checksum()


def test_existing_open_attempts_get_fail_closed_process_marker_columns(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(f"DROP TABLE {TOOL_PREPARE_ATTEMPT_TABLE}")
        _create_legacy_attempt_sidecar(connection)
        _insert_attempt(connection, "legacy-active", job_id="legacy-job-active", generation=1)
        _insert_attempt(
            connection,
            "legacy-recovery",
            job_id="legacy-job-recovery",
            generation=1,
            state="recovery_required",
        )
        before = _core_ledger(connection)

    initialize_or_migrate_runtime_db(cfg.db_path)

    with sqlite3.connect(cfg.db_path) as connection:
        connection.row_factory = sqlite3.Row
        after = _core_ledger(connection)
        rows = connection.execute(
            f"""
            SELECT attempt_id, process_marker_schema, process_marker_json, process_marker_fingerprint
            FROM {TOOL_PREPARE_ATTEMPT_TABLE}
            ORDER BY attempt_id
            """
        ).fetchall()
        assert_tool_prepare_attempt_schema(connection)
    with get_connection(cfg) as connection:
        activity = tool_prepare_worker_activity(connection, now="2099-06-07T10:06:00Z")

    assert before == after
    assert [dict(row) for row in rows] == [
        {
            "attempt_id": attempt_id,
            "process_marker_schema": "",
            "process_marker_json": "",
            "process_marker_fingerprint": "",
        }
        for attempt_id in ("legacy-active", "legacy-recovery")
    ]
    assert activity["activeAttemptCount"] == 1
    assert activity["recoveryRequiredAttemptCount"] == 1
    assert activity["openAttemptCount"] == 2
    assert activity["invalidProcessIdentityAttemptCount"] == 2
    assert sum(
        item["reason"] == "OPEN_ATTEMPT_PROCESS_MARKER_INVALID"
        for item in activity["projectionViolations"]
    ) == 2


def test_concurrent_attempt_sidecar_upgrades_are_serialized(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(f"DROP TABLE {TOOL_PREPARE_ATTEMPT_TABLE}")
        _create_legacy_attempt_sidecar(connection)

    barrier = threading.Barrier(3)

    def initialize() -> None:
        barrier.wait()
        initialize_or_migrate_runtime_db(cfg.db_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(initialize) for _ in range(2)]
        barrier.wait()
        for future in futures:
            future.result(timeout=10)

    with sqlite3.connect(cfg.db_path) as connection:
        connection.row_factory = sqlite3.Row
        assert_tool_prepare_attempt_schema(connection)


def test_initializer_validates_core_before_creating_auxiliary_schema(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        sqlite_migrations.configure_runtime_connection(connection)
        sqlite_migrations.migrate_runtime_schema(connection)
        connection.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        )
        connection.commit()

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match="REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_CHECKSUM_MISMATCH"):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert _schema_object(connection, "table", TOOL_PREPARE_ATTEMPT_TABLE) is None


def test_ordinary_connection_does_not_create_missing_attempt_schema(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(f"DROP TABLE {TOOL_PREPARE_ATTEMPT_TABLE}")

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match=TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR):
        get_connection(cfg)

    with sqlite3.connect(cfg.db_path) as connection:
        assert _schema_object(connection, "table", TOOL_PREPARE_ATTEMPT_TABLE) is None


def test_attempt_schema_assertion_rejects_missing_column(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(f"DROP TABLE {TOOL_PREPARE_ATTEMPT_TABLE}")
        connection.execute(
            f"""
            CREATE TABLE {TOOL_PREPARE_ATTEMPT_TABLE} (
                attempt_id TEXT PRIMARY KEY NOT NULL,
                job_id TEXT NOT NULL,
                generation INTEGER NOT NULL
            )
            """
        )

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=f"{TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR}: invalid column:{TOOL_PREPARE_ATTEMPT_TABLE}.state",
    ):
        get_connection(cfg)


def test_attempt_schema_assertion_rejects_wrong_index_shape(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        connection.execute(f"DROP INDEX {TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX}")
        connection.execute(
            f"""
            CREATE INDEX {TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX}
            ON {TOOL_PREPARE_ATTEMPT_TABLE}(job_id)
            WHERE state = 'active'
            """
        )

    with pytest.raises(
        RemoteRunnerSQLiteSchemaError,
        match=f"{TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR}: invalid index:{TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX}",
    ):
        get_connection(cfg)


def test_attempt_schema_enforces_generation_and_open_attempt_uniqueness(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    with sqlite3.connect(cfg.db_path) as connection:
        _insert_attempt(connection, "attempt-1", generation=1)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_attempt(connection, "attempt-2", generation=2)
        connection.execute(
            f"""
            UPDATE {TOOL_PREPARE_ATTEMPT_TABLE}
            SET state = 'released', released_at = '2099-06-07T10:01:00Z'
            WHERE attempt_id = 'attempt-1'
            """
        )
        _insert_attempt(connection, "attempt-2", generation=2)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_attempt(connection, "attempt-2-duplicate", generation=2, state="released")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_attempt(connection, "attempt-invalid", job_id="job-invalid", generation=1, state="expired")


def _insert_attempt(
    connection: sqlite3.Connection,
    attempt_id: str,
    *,
    job_id: str = "job-1",
    generation: int,
    state: str = "active",
) -> None:
    released_at = "2099-06-07T10:01:00Z" if state in {"released", "abandoned"} else None
    connection.execute(
        f"""
        INSERT INTO {TOOL_PREPARE_ATTEMPT_TABLE} (
            attempt_id, job_id, generation, state, worker_id, session_id,
            process_pid, hostname, process_instance_id, claim_owner,
            claim_token_hash, claimed_at, heartbeat_at, lease_expires_at,
            released_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            job_id,
            generation,
            state,
            "worker-1",
            "session-1",
            1234,
            "runner-1",
            "process-1",
            "worker-1:session-1",
            "sha256:claim-token",
            "2099-06-07T10:00:00Z",
            "2099-06-07T10:00:00Z",
            "2099-06-07T10:05:00Z",
            released_at,
            "2099-06-07T10:00:00Z",
            "2099-06-07T10:00:00Z",
        ),
    )


def _create_legacy_attempt_sidecar(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
        CREATE TABLE {TOOL_PREPARE_ATTEMPT_TABLE} (
            attempt_id TEXT PRIMARY KEY NOT NULL,
            job_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            state TEXT NOT NULL,
            outcome_status TEXT NOT NULL DEFAULT '',
            worker_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            process_pid INTEGER NOT NULL,
            hostname TEXT NOT NULL,
            process_instance_id TEXT NOT NULL,
            claim_owner TEXT NOT NULL,
            claim_token_hash TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL,
            released_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_error_json TEXT NOT NULL DEFAULT '{{}}',
            recovery_evidence_json TEXT NOT NULL DEFAULT '{{}}',
            UNIQUE(job_id, generation),
            CHECK (generation > 0),
            CHECK (process_pid > 0),
            CHECK (state IN ('active', 'released', 'recovery_required', 'abandoned')),
            CHECK (
                (state IN ('active', 'recovery_required') AND released_at IS NULL)
                OR (state IN ('released', 'abandoned') AND released_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX {TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX}
        ON {TOOL_PREPARE_ATTEMPT_TABLE}(job_id)
        WHERE state IN ('active', 'recovery_required');
        CREATE INDEX {TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX}
        ON {TOOL_PREPARE_ATTEMPT_TABLE}(lease_expires_at, job_id)
        WHERE state = 'active';
        """
    )


def _core_ledger(connection: sqlite3.Connection) -> tuple[int, tuple[int, str, str]]:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    row = connection.execute(
        "SELECT version, name, checksum FROM schema_migrations WHERE version = ?",
        (CURRENT_SCHEMA_VERSION,),
    ).fetchone()
    assert row is not None
    return user_version, (int(row[0]), str(row[1]), str(row[2]))


def _schema_object(connection: sqlite3.Connection, object_type: str, name: str) -> sqlite3.Row | tuple | None:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
