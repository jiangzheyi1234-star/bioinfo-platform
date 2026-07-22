"""Fail-closed contracts for the runtime schema migration ledger."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from .sqlite_schema_checksums import runtime_schema_ledger_checksum


SCHEMA_LEDGER_MISSING_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_MISSING"
SCHEMA_LEDGER_CHECKSUM_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_CHECKSUM_MISMATCH"
SCHEMA_LEDGER_HISTORY_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_HISTORY_INVALID"
SCHEMA_LEDGER_AHEAD_ERROR = "REMOTE_RUNNER_SQLITE_SCHEMA_LEDGER_AHEAD_OF_USER_VERSION"

_EXPECTED_NAMES = {
    1: "001_baseline_remote_runner_schema",
    2: "002_rule_level_run_state",
    3: "003_scheduler_triggers",
    4: "004_artifact_lifecycle",
    5: "005_artifact_cache",
    6: "006_backfill_launch",
    7: "007_result_package_exports",
    8: "008_result_package_payload_mode",
    9: "009_workflow_trigger_inbox",
    10: "010_workflow_trigger_inbox_payload",
    11: "011_artifact_cache_pins",
    12: "012_workflow_trigger_inbox_signature_metadata",
    13: "013_workflow_trigger_readiness_watcher",
    14: "014_result_package_byte_state",
    15: "015_artifact_ledger_invalidation",
    16: "016_result_package_retired_at",
    17: "017_artifact_lifecycle_policy",
    18: "018_agent_session_control_plane",
    19: "019_agent_run_authorization_execution_binding",
    20: "020_agent_workspace_proof",
    21: "021_agent_process_instance",
    22: "022_agent_workspace_tool_assets_binding",
    23: "023_agent_process_lifecycle",
}
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXPECTED_COLUMNS = (
    (0, "version", "INTEGER", 0, None, 1),
    (1, "name", "TEXT", 1, None, 0),
    (2, "checksum", "TEXT", 1, None, 0),
    (3, "applied_at", "TEXT", 1, None, 0),
)
_EXPECTED_TABLE_SQL = " ".join(
    """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL
    )
    """.split()
).casefold()

ErrorFactory = Callable[[str], Exception]


def assert_runtime_schema_migration_source(
    connection: sqlite3.Connection,
    *,
    version: int,
    error_factory: ErrorFactory,
) -> None:
    """Reject an incoherent source ledger before any migration can write."""

    normalized_version = int(version)
    table_exists = _ledger_table_exists(connection)
    if normalized_version == 0:
        if table_exists:
            _assert_ledger_table_shape(connection, error_factory)
            if (
                connection.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone()
                is not None
            ):
                _raise(error_factory, SCHEMA_LEDGER_AHEAD_ERROR)
        return
    if not table_exists:
        _raise(error_factory, SCHEMA_LEDGER_MISSING_ERROR)
    _assert_ledger_table_shape(connection, error_factory)
    if (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version > ? LIMIT 1",
            (normalized_version,),
        ).fetchone()
        is not None
    ):
        _raise(error_factory, SCHEMA_LEDGER_AHEAD_ERROR)
    if normalized_version >= 17:
        expected_versions = tuple(range(17, normalized_version + 1))
        rows = connection.execute(
            """
            SELECT version, name, checksum, applied_at
            FROM schema_migrations
            WHERE version BETWEEN 17 AND ?
            ORDER BY version
            """,
            (normalized_version,),
        ).fetchall()
        _assert_expected_history(
            rows,
            expected_versions=expected_versions,
            exact_checksum_versions=frozenset(),
            error_factory=error_factory,
        )
        return
    expected_name = _EXPECTED_NAMES.get(normalized_version)
    rows = connection.execute(
        "SELECT name, checksum, applied_at FROM schema_migrations WHERE version = ?",
        (normalized_version,),
    ).fetchall()
    if expected_name is None or len(rows) != 1:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    name, checksum, applied_at = rows[0]
    if (
        name != expected_name
        or not isinstance(checksum, str)
        or not checksum
        or not isinstance(applied_at, str)
        or not applied_at.strip()
    ):
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)


def assert_runtime_schema_ledger_current(
    connection: sqlite3.Connection,
    *,
    error_factory: ErrorFactory,
) -> None:
    """Require continuous named history and exact current Agent checksums."""

    assert_runtime_schema_ledger_at_version(
        connection,
        version=23,
        error_factory=error_factory,
    )


def assert_runtime_schema_ledger_at_version(
    connection: sqlite3.Connection,
    *,
    version: int,
    error_factory: ErrorFactory,
) -> None:
    """Require the exact append-only Agent ledger at V22 or V23."""

    normalized_version = int(version)
    if normalized_version not in {22, 23}:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    if not _ledger_table_exists(connection):
        _raise(error_factory, SCHEMA_LEDGER_MISSING_ERROR)
    _assert_ledger_table_shape(connection, error_factory)
    if (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version > ? LIMIT 1",
            (normalized_version,),
        ).fetchone()
        is not None
    ):
        _raise(error_factory, SCHEMA_LEDGER_AHEAD_ERROR)
    if (
        connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (normalized_version,),
        ).fetchone()
        is None
    ):
        _raise(error_factory, SCHEMA_LEDGER_MISSING_ERROR)
    rows = connection.execute(
        """
        SELECT version, name, checksum, applied_at
        FROM schema_migrations
        WHERE version BETWEEN 17 AND ?
        ORDER BY version
        """,
        (normalized_version,),
    ).fetchall()
    _assert_expected_history(
        rows,
        expected_versions=tuple(range(17, normalized_version + 1)),
        exact_checksum_versions=frozenset(range(21, normalized_version + 1)),
        error_factory=error_factory,
    )


def assert_runtime_schema_ledger_write_safe(
    connection: sqlite3.Connection,
    *,
    error_factory: ErrorFactory,
) -> None:
    """Require the exact trigger-free ledger namespace before an INSERT."""

    if not _ledger_table_exists(connection):
        _raise(error_factory, SCHEMA_LEDGER_MISSING_ERROR)
    _assert_ledger_table_shape(connection, error_factory)


def _assert_expected_history(
    rows: list[sqlite3.Row] | list[tuple[object, ...]],
    *,
    expected_versions: tuple[int, ...],
    exact_checksum_versions: frozenset[int],
    error_factory: ErrorFactory,
) -> None:
    try:
        versions = tuple(int(row[0]) for row in rows)
    except (TypeError, ValueError):
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    if versions != expected_versions:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    for version, name, checksum, applied_at in rows:
        normalized_version = int(version)
        expected_name = _EXPECTED_NAMES[normalized_version]
        if (
            name != expected_name
            or not isinstance(applied_at, str)
            or not applied_at.strip()
        ):
            _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
        if not isinstance(checksum, str) or _LOWER_SHA256.fullmatch(checksum) is None:
            _raise(error_factory, SCHEMA_LEDGER_CHECKSUM_ERROR)
        if (
            normalized_version in exact_checksum_versions
            and checksum
            != runtime_schema_ledger_checksum(normalized_version, expected_name)
        ):
            _raise(error_factory, SCHEMA_LEDGER_CHECKSUM_ERROR)


def _ledger_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = 'schema_migrations'"
    ).fetchone()
    return row is not None and str(row[0]) == "table"


def _assert_ledger_table_shape(
    connection: sqlite3.Connection,
    error_factory: ErrorFactory,
) -> None:
    columns = tuple(
        (
            int(row[0]),
            str(row[1]),
            str(row[2]).upper(),
            int(row[3]),
            None if row[4] is None else str(row[4]),
            int(row[5]),
        )
        for row in connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
    )
    if columns != _EXPECTED_COLUMNS:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if (
        table is None
        or table[0] is None
        or _normalize_table_sql(str(table[0])) != _EXPECTED_TABLE_SQL
    ):
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    index = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'index' AND tbl_name = 'schema_migrations'
        LIMIT 1
        """
    ).fetchone()
    if index is not None:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)
    trigger = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'trigger' AND tbl_name = 'schema_migrations'
        LIMIT 1
        """
    ).fetchone()
    if trigger is not None:
        _raise(error_factory, SCHEMA_LEDGER_HISTORY_ERROR)


def _normalize_table_sql(value: str) -> str:
    normalized = " ".join(value.split()).casefold()
    return normalized.replace(
        "create table if not exists schema_migrations",
        "create table schema_migrations",
        1,
    )


def _raise(error_factory: ErrorFactory, code: str) -> None:
    raise error_factory(code)


__all__ = [
    "SCHEMA_LEDGER_AHEAD_ERROR",
    "SCHEMA_LEDGER_CHECKSUM_ERROR",
    "SCHEMA_LEDGER_HISTORY_ERROR",
    "SCHEMA_LEDGER_MISSING_ERROR",
    "assert_runtime_schema_ledger_at_version",
    "assert_runtime_schema_ledger_current",
    "assert_runtime_schema_ledger_write_safe",
    "assert_runtime_schema_migration_source",
]
