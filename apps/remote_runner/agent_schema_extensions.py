"""Ordered schema orchestration for Agent execution extensions."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .agent_process_instance_schema import (
    assert_agent_process_instance_schema,
    migrate_agent_process_instance_schema,
)
from .agent_workspace_proof_schema import (
    assert_agent_workspace_proof_schema,
    migrate_agent_workspace_proof_schema,
)


RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def migrate_agent_schema_extensions(
    connection: sqlite3.Connection,
    version: int,
    record_migration: RecordMigration,
) -> None:
    """Advance the append-only Agent execution schemas in dependency order."""

    current = int(version)
    if current == 19:
        migrate_agent_workspace_proof_schema(
            connection,
            record_migration=record_migration,
        )
        current = 20
    if current != 20:
        raise RuntimeError(f"AGENT_SCHEMA_MIGRATION_VERSION_UNSUPPORTED: {current}")
    migrate_agent_process_instance_schema(
        connection,
        record_migration=record_migration,
    )


def assert_agent_schema_extensions(connection: sqlite3.Connection) -> None:
    """Require both durable Agent execution schemas at current readiness."""

    assert_agent_workspace_proof_schema(connection)
    assert_agent_process_instance_schema(connection)


__all__ = [
    "assert_agent_schema_extensions",
    "migrate_agent_schema_extensions",
]
