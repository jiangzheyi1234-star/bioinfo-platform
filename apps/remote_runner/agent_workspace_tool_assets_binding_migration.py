"""One-time validation of server-derived Agent workspace tool asset hashes."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .agent_control_plane_schema_readiness import assert_agent_control_plane_schema
from .agent_process_instance_schema import assert_agent_process_instance_schema
from .agent_process_instance_v22_schema import (
    AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,
    upgrade_agent_process_instance_schema_to_v22,
)
from .agent_process_instance_v23_schema import (
    AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,
)
from .agent_schema_migration_guard import assert_agent_schema_migration_precondition
from .agent_schema_trigger_namespace import assert_exact_runtime_trigger_namespace
from .agent_workspace_proof_schema import assert_agent_workspace_proof_schema
from .sqlite_schema_checksums import (
    V21_SCHEMA_MIGRATION_NAME,
    V21_SCHEMA_VERSION,
    runtime_schema_ledger_checksum,
)
from .sqlite_schema_contract import REQUIRED_TRIGGERS, missing_required_schema_objects
from .sqlite_schema_ledger import assert_runtime_schema_ledger_at_version


AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID = (
    "AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID"
)
AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID = (
    "AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID"
)
_V22_TARGET_SCHEMA_OBJECTS = frozenset(
    {
        f"index:{AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX}",
        "trigger:agent_process_instances_envelope_guard",
    }
)
_V23_FUTURE_SCHEMA_OBJECTS = frozenset(
    {f"trigger:{AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}"}
)

RecordMigration = Callable[[sqlite3.Connection, int, str], None]


class AgentWorkspaceToolAssetsBindingMigrationError(RuntimeError):
    """Stable, path-free rejection of a non-current persisted proof."""


def migrate_agent_workspace_tool_assets_binding(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int = 22,
    name: str = "022_agent_workspace_tool_assets_binding",
) -> None:
    """Validate every v21 proof without rewriting its immutable history."""

    try:
        connection.execute("BEGIN IMMEDIATE")
        assert_agent_schema_migration_precondition(
            connection,
            prior_version=21,
            prior_name="021_agent_process_instance",
            target_version=version,
            prior_checksum=runtime_schema_ledger_checksum(
                V21_SCHEMA_VERSION,
                V21_SCHEMA_MIGRATION_NAME,
            ),
        )
        assert_agent_control_plane_schema(connection)
        assert_agent_workspace_proof_schema(connection)
        assert_agent_process_instance_schema(connection, schema_version=21)
        _assert_complete_v21_baseline(connection)
        upgrade_agent_process_instance_schema_to_v22(connection)
        _assert_existing_workspace_proofs_current(connection)
        assert_agent_process_instance_schema(connection)
        if set(missing_required_schema_objects(connection)) != (
            _V23_FUTURE_SCHEMA_OBJECTS
        ):
            raise RuntimeError(
                AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID
            )
        assert_exact_runtime_trigger_namespace(
            connection,
            expected_names=tuple(
                REQUIRED_TRIGGERS - {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}
            ),
            error_code=AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID,
        )
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        assert_runtime_schema_ledger_at_version(
            connection,
            version=22,
            error_factory=AgentWorkspaceToolAssetsBindingMigrationError,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _assert_complete_v21_baseline(connection: sqlite3.Connection) -> None:
    missing = set(missing_required_schema_objects(connection))
    if missing != _V22_TARGET_SCHEMA_OBJECTS | _V23_FUTURE_SCHEMA_OBJECTS:
        raise RuntimeError(
            AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID
        )


def _assert_existing_workspace_proofs_current(
    connection: sqlite3.Connection,
) -> None:
    # Local by design: storage imports config/storage_core, which import the
    # top-level migration orchestrator while it is being initialized.
    from .agent_workspace_proof_storage import (
        AgentWorkspaceProofStorageConflictError,
        agent_workspace_proof_row_to_dict,
    )

    cursor = connection.cursor()
    cursor.row_factory = sqlite3.Row
    try:
        for row in cursor.execute("SELECT * FROM agent_workspace_proofs"):
            try:
                agent_workspace_proof_row_to_dict(row)
            except AgentWorkspaceProofStorageConflictError:
                raise AgentWorkspaceToolAssetsBindingMigrationError(
                    AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID
                ) from None
    finally:
        cursor.close()


__all__ = [
    "AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID",
    "AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID",
    "AgentWorkspaceToolAssetsBindingMigrationError",
    "migrate_agent_workspace_tool_assets_binding",
]
