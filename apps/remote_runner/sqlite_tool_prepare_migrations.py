from __future__ import annotations

import sqlite3

from .tool_prepare_reservations import json_object, tool_prepare_job_reservation


TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR = "REMOTE_RUNNER_SQLITE_TOOL_PREPARE_ATTEMPT_SCHEMA_INVALID"
TOOL_PREPARE_ATTEMPT_TABLE = "tool_prepare_attempts"
TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX = "idx_tool_prepare_attempts_one_open"
TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX = "idx_tool_prepare_attempts_active_expiry"

_ATTEMPT_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TOOL_PREPARE_ATTEMPT_TABLE} (
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
    process_marker_schema TEXT NOT NULL DEFAULT '',
    process_marker_json TEXT NOT NULL DEFAULT '',
    process_marker_fingerprint TEXT NOT NULL DEFAULT '',
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
)
"""

_ATTEMPT_ONE_OPEN_INDEX_SQL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX}
ON {TOOL_PREPARE_ATTEMPT_TABLE}(job_id)
WHERE state IN ('active', 'recovery_required')
"""

_ATTEMPT_ACTIVE_EXPIRY_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS {TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX}
ON {TOOL_PREPARE_ATTEMPT_TABLE}(lease_expires_at, job_id)
WHERE state = 'active'
"""

_REQUIRED_ATTEMPT_COLUMNS = {
    "attempt_id": ("TEXT", 1, None, 1),
    "job_id": ("TEXT", 1, None, 0),
    "generation": ("INTEGER", 1, None, 0),
    "state": ("TEXT", 1, None, 0),
    "outcome_status": ("TEXT", 1, "''", 0),
    "worker_id": ("TEXT", 1, None, 0),
    "session_id": ("TEXT", 1, None, 0),
    "process_pid": ("INTEGER", 1, None, 0),
    "hostname": ("TEXT", 1, None, 0),
    "process_instance_id": ("TEXT", 1, None, 0),
    "process_marker_schema": ("TEXT", 1, "''", 0),
    "process_marker_json": ("TEXT", 1, "''", 0),
    "process_marker_fingerprint": ("TEXT", 1, "''", 0),
    "claim_owner": ("TEXT", 1, None, 0),
    "claim_token_hash": ("TEXT", 1, None, 0),
    "claimed_at": ("TEXT", 1, None, 0),
    "heartbeat_at": ("TEXT", 1, None, 0),
    "lease_expires_at": ("TEXT", 1, None, 0),
    "released_at": ("TEXT", 0, None, 0),
    "created_at": ("TEXT", 1, None, 0),
    "updated_at": ("TEXT", 1, None, 0),
    "last_error_json": ("TEXT", 1, "'{}'", 0),
    "recovery_evidence_json": ("TEXT", 1, "'{}'", 0),
}


def ensure_tool_prepare_attempt_schema(connection: sqlite3.Connection) -> None:
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(_ATTEMPT_TABLE_SQL)
        _ensure_attempt_process_marker_columns(connection)
        connection.execute(_ATTEMPT_ONE_OPEN_INDEX_SQL)
        connection.execute(_ATTEMPT_ACTIVE_EXPIRY_INDEX_SQL)
        assert_tool_prepare_attempt_schema(connection)
        if owns_transaction:
            connection.commit()
    except Exception:
        if owns_transaction:
            connection.rollback()
        raise


def _ensure_attempt_process_marker_columns(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({TOOL_PREPARE_ATTEMPT_TABLE})").fetchall()
    }
    definitions = {
        "process_marker_schema": "TEXT NOT NULL DEFAULT ''",
        "process_marker_json": "TEXT NOT NULL DEFAULT ''",
        "process_marker_fingerprint": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in definitions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE {TOOL_PREPARE_ATTEMPT_TABLE} ADD COLUMN {name} {definition}"
            )


def assert_tool_prepare_attempt_schema(
    connection: sqlite3.Connection,
    *,
    error_type: type[RuntimeError] = RuntimeError,
) -> None:
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (TOOL_PREPARE_ATTEMPT_TABLE,),
    ).fetchone()
    if table is None:
        _raise_schema_error(error_type, f"missing table:{TOOL_PREPARE_ATTEMPT_TABLE}")

    columns = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
        for row in connection.execute(f"PRAGMA table_info({TOOL_PREPARE_ATTEMPT_TABLE})").fetchall()
    }
    for name, expected in _REQUIRED_ATTEMPT_COLUMNS.items():
        if columns.get(name) != expected:
            _raise_schema_error(error_type, f"invalid column:{TOOL_PREPARE_ATTEMPT_TABLE}.{name}")

    normalized_table_sql = _normalized_sql(str(table[0] or ""))
    required_checks = (
        "check (generation > 0)",
        "check (process_pid > 0)",
        "check (state in ('active', 'released', 'recovery_required', 'abandoned'))",
        "(state in ('active', 'recovery_required') and released_at is null)",
        "or (state in ('released', 'abandoned') and released_at is not null)",
    )
    for check in required_checks:
        if check not in normalized_table_sql:
            _raise_schema_error(error_type, f"invalid constraint:{TOOL_PREPARE_ATTEMPT_TABLE}")

    indexes = {
        str(row[1]): row
        for row in connection.execute(f"PRAGMA index_list({TOOL_PREPARE_ATTEMPT_TABLE})").fetchall()
    }
    _assert_named_index(
        connection,
        indexes,
        TOOL_PREPARE_ATTEMPT_ONE_OPEN_INDEX,
        columns=("job_id",),
        unique=True,
        predicate="where state in ('active', 'recovery_required')",
        error_type=error_type,
    )
    _assert_named_index(
        connection,
        indexes,
        TOOL_PREPARE_ATTEMPT_ACTIVE_EXPIRY_INDEX,
        columns=("lease_expires_at", "job_id"),
        unique=False,
        predicate="where state = 'active'",
        error_type=error_type,
    )
    has_generation_uniqueness = any(
        int(row[2]) == 1 and _index_columns(connection, name) == ("job_id", "generation")
        for name, row in indexes.items()
    )
    if not has_generation_uniqueness:
        _raise_schema_error(error_type, f"missing uniqueness:{TOOL_PREPARE_ATTEMPT_TABLE}(job_id,generation)")


def ensure_tool_prepare_job_schema(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_prepare_jobs)").fetchall()}
    column_definitions = {
        "reservation_key": "TEXT NOT NULL DEFAULT ''",
        "reservation_package_spec": "TEXT NOT NULL DEFAULT ''",
        "reservation_validation_target": "TEXT NOT NULL DEFAULT ''",
        "claimed_by": "TEXT NOT NULL DEFAULT ''",
        "claimed_until": "TEXT",
        "heartbeat_at": "TEXT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "max_attempts": "INTEGER NOT NULL DEFAULT 3",
        "next_attempt_at": "TEXT",
        "exhausted_at": "TEXT",
        "backoff_seconds": "INTEGER NOT NULL DEFAULT 30",
        "last_worker_error_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    added_columns = False
    for column, definition in column_definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE tool_prepare_jobs ADD COLUMN {column} {definition}")
            added_columns = True
    if added_columns or _tool_prepare_jobs_need_reservation_backfill(connection):
        _backfill_tool_prepare_job_reservations(connection)
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_prepare_jobs_active_reservation
        ON tool_prepare_jobs(reservation_key)
        WHERE status IN ('queued', 'running') AND reservation_key <> ''
        """
    )


def _assert_named_index(
    connection: sqlite3.Connection,
    indexes: dict[str, sqlite3.Row | tuple[object, ...]],
    name: str,
    *,
    columns: tuple[str, ...],
    unique: bool,
    predicate: str,
    error_type: type[RuntimeError],
) -> None:
    row = indexes.get(name)
    if row is None or bool(row[2]) is not unique or int(row[4]) != 1:
        _raise_schema_error(error_type, f"invalid index:{name}")
    if _index_columns(connection, name) != columns:
        _raise_schema_error(error_type, f"invalid index:{name}")
    index_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        (name,),
    ).fetchone()
    if index_sql is None or predicate not in _normalized_sql(str(index_sql[0] or "")):
        _raise_schema_error(error_type, f"invalid index:{name}")


def _index_columns(connection: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    return tuple(str(row[2]) for row in connection.execute(f"PRAGMA index_info({index_name})").fetchall())


def _normalized_sql(value: str) -> str:
    return " ".join(value.lower().split())


def _raise_schema_error(error_type: type[RuntimeError], detail: str) -> None:
    raise error_type(f"{TOOL_PREPARE_ATTEMPT_SCHEMA_ERROR}: {detail}")


def _tool_prepare_jobs_need_reservation_backfill(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM tool_prepare_jobs
        WHERE reservation_key = ''
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _backfill_tool_prepare_job_reservations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT job_id, tool_id, request_json
        FROM tool_prepare_jobs
        WHERE reservation_key = ''
        """
    ).fetchall()
    for row in rows:
        request = json_object(row["request_json"])
        reservation = tool_prepare_job_reservation(request, str(row["tool_id"] or ""))
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET reservation_key = ?,
                reservation_package_spec = ?,
                reservation_validation_target = ?
            WHERE job_id = ?
            """,
            (
                reservation["key"],
                reservation["packageSpec"],
                reservation["validationTarget"],
                row["job_id"],
            ),
        )
