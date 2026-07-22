"""Deterministic ledger checksums for versioned runtime schema contracts."""

from __future__ import annotations

import hashlib

from .agent_process_instance_schema import (
    AGENT_PROCESS_INSTANCE_SCHEMA_SQL,
    AGENT_PROCESS_INSTANCE_V21_SCHEMA_SQL,
)
from .agent_process_instance_v23_schema import AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL
from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL
from .storage_schema import SCHEMA_SQL


V21_SCHEMA_VERSION = 21
V21_SCHEMA_MIGRATION_NAME = "021_agent_process_instance"
V22_SCHEMA_VERSION = 22
V22_SCHEMA_MIGRATION_NAME = "022_agent_workspace_tool_assets_binding"
V23_SCHEMA_VERSION = 23
V23_SCHEMA_MIGRATION_NAME = "023_agent_process_lifecycle"


def runtime_schema_ledger_checksum(version: int, name: str) -> str:
    """Hash the exact baseline represented by a durable ledger row."""

    normalized_version = int(version)
    normalized_name = str(name)
    schema_sql = SCHEMA_SQL
    requested = (normalized_version, normalized_name)
    if requested in {
        (V21_SCHEMA_VERSION, V21_SCHEMA_MIGRATION_NAME),
        (V22_SCHEMA_VERSION, V22_SCHEMA_MIGRATION_NAME),
    }:
        if schema_sql.count(AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL) != 1:
            raise RuntimeError("REMOTE_RUNNER_V22_SCHEMA_CHECKSUM_SOURCE_INVALID")
        schema_sql = schema_sql.replace(
            AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL,
            "",
            1,
        )
    if requested == (V21_SCHEMA_VERSION, V21_SCHEMA_MIGRATION_NAME):
        if schema_sql.count(AGENT_PROCESS_INSTANCE_SCHEMA_SQL) != 1:
            raise RuntimeError("REMOTE_RUNNER_V21_SCHEMA_CHECKSUM_SOURCE_INVALID")
        schema_sql = schema_sql.replace(
            AGENT_PROCESS_INSTANCE_SCHEMA_SQL,
            AGENT_PROCESS_INSTANCE_V21_SCHEMA_SQL,
            1,
        )
    elif requested not in {
        (V22_SCHEMA_VERSION, V22_SCHEMA_MIGRATION_NAME),
        (V23_SCHEMA_VERSION, V23_SCHEMA_MIGRATION_NAME),
    }:
        normalized_version = V23_SCHEMA_VERSION
        normalized_name = V23_SCHEMA_MIGRATION_NAME
    payload = (
        f"{normalized_version}:{normalized_name}:"
        f"{schema_sql}:{REFERENCE_DATABASE_SCHEMA_SQL}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "V21_SCHEMA_MIGRATION_NAME",
    "V21_SCHEMA_VERSION",
    "V22_SCHEMA_MIGRATION_NAME",
    "V22_SCHEMA_VERSION",
    "V23_SCHEMA_MIGRATION_NAME",
    "V23_SCHEMA_VERSION",
    "runtime_schema_ledger_checksum",
]
