"""One-time V23 activation of exact Agent process lifecycle evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .agent_control_plane_schema_readiness import assert_agent_control_plane_schema
from .agent_process_instance_schema import assert_agent_process_instance_schema
from .agent_process_instance_v23_schema import (
    AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,
    assert_agent_process_instance_v23_schema,
    upgrade_agent_process_instance_schema_to_v23,
)
from .agent_schema_migration_guard import assert_agent_schema_migration_precondition
from .agent_schema_trigger_namespace import assert_exact_runtime_trigger_namespace
from .agent_workspace_proof_schema import assert_agent_workspace_proof_schema
from .sqlite_schema_checksums import (
    V22_SCHEMA_MIGRATION_NAME,
    V22_SCHEMA_VERSION,
    runtime_schema_ledger_checksum,
)
from .sqlite_schema_contract import REQUIRED_TRIGGERS, missing_required_schema_objects
from .sqlite_schema_ledger import assert_runtime_schema_ledger_current


AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID = (
    "AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID"
)
_V23_TARGET_SCHEMA_OBJECTS = frozenset(
    {f"trigger:{AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}"}
)

RecordMigration = Callable[[sqlite3.Connection, int, str], None]


class AgentProcessLifecycleMigrationError(RuntimeError):
    """Stable rejection of an unsafe V22 lifecycle baseline."""


def migrate_agent_process_lifecycle_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int = 23,
    name: str = "023_agent_process_lifecycle",
) -> None:
    """Install V23 only from an exact, prepared-only V22 database."""

    try:
        connection.execute("BEGIN IMMEDIATE")
        assert_agent_schema_migration_precondition(
            connection,
            prior_version=22,
            prior_name=V22_SCHEMA_MIGRATION_NAME,
            target_version=version,
            prior_checksum=runtime_schema_ledger_checksum(
                V22_SCHEMA_VERSION,
                V22_SCHEMA_MIGRATION_NAME,
            ),
        )
        assert_agent_control_plane_schema(connection)
        assert_agent_workspace_proof_schema(connection)
        assert_agent_process_instance_schema(connection, schema_version=22)
        _assert_complete_v22_baseline(connection)
        upgrade_agent_process_instance_schema_to_v23(connection)
        if missing_required_schema_objects(connection):
            raise RuntimeError(AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID)
        assert_exact_runtime_trigger_namespace(
            connection,
            expected_names=tuple(REQUIRED_TRIGGERS),
            error_code=AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID,
        )
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        assert_runtime_schema_ledger_current(
            connection,
            error_factory=AgentProcessLifecycleMigrationError,
        )
        assert_agent_process_instance_v23_schema(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _assert_complete_v22_baseline(connection: sqlite3.Connection) -> None:
    missing = set(missing_required_schema_objects(connection))
    if missing != _V23_TARGET_SCHEMA_OBJECTS:
        raise RuntimeError(AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID)


__all__ = [
    "AGENT_PROCESS_LIFECYCLE_MIGRATION_BASELINE_INVALID",
    "AgentProcessLifecycleMigrationError",
    "migrate_agent_process_lifecycle_schema",
]
