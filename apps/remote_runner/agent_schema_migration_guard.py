"""Fail-closed migration-ledger preconditions for Agent schema upgrades."""

from __future__ import annotations

import re
import sqlite3


AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID = (
    "AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID"
)
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")


def assert_agent_schema_migration_precondition(
    connection: sqlite3.Connection,
    *,
    prior_version: int,
    prior_name: str,
    target_version: int,
    prior_checksum: str | None = None,
) -> None:
    """Require one credible prior ledger row and no pre-recorded target row."""

    observed_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if observed_version != prior_version or target_version != prior_version + 1:
        _raise_precondition("user-version")
    table = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = 'schema_migrations'"
    ).fetchone()
    if table is None or str(table[0]) != "table":
        _raise_precondition("ledger-table")
    rows = connection.execute(
        "SELECT name, checksum, applied_at FROM schema_migrations WHERE version = ?",
        (prior_version,),
    ).fetchall()
    if len(rows) != 1:
        _raise_precondition("prior-ledger")
    name, checksum, applied_at = rows[0]
    if (
        not isinstance(name, str)
        or name != prior_name
        or not isinstance(checksum, str)
        or _LOWER_SHA256.fullmatch(checksum) is None
        or (prior_checksum is not None and checksum != prior_checksum)
        or not isinstance(applied_at, str)
        or not applied_at.strip()
    ):
        _raise_precondition("prior-ledger")
    target = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version > ? LIMIT 1",
        (prior_version,),
    ).fetchone()
    if target is not None:
        _raise_precondition("target-ledger")


def _raise_precondition(component: str) -> None:
    raise RuntimeError(
        f"{AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID}: {component}"
    )


__all__ = [
    "AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID",
    "assert_agent_schema_migration_precondition",
]
