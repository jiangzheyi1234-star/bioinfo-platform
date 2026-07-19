from __future__ import annotations

import sqlite3
from collections.abc import Callable


AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH = (
    "AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH"
)

AGENT_WORKSPACE_PROOF_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_workspace_proofs (
        workspace_proof_id TEXT PRIMARY KEY,
        contract_version TEXT NOT NULL CHECK (
            contract_version = 'agent-workspace-proof.v1'
        ),
        run_id TEXT NOT NULL,
        authorization_id TEXT NOT NULL,
        attempt_id TEXT NOT NULL,
        lease_generation INTEGER NOT NULL CHECK (lease_generation >= 1),
        source_attempt_id TEXT,
        process_boundary TEXT NOT NULL CHECK (
            process_boundary IN ('pre_dry_run', 'pre_run', 'terminal')
        ),
        process_ordinal INTEGER NOT NULL CHECK (process_ordinal >= 1),
        workflow_revision_id TEXT NOT NULL,
        workflow_revision_content_hash TEXT NOT NULL,
        workflow_revision_manifest_hash TEXT NOT NULL,
        run_spec_hash TEXT NOT NULL,
        input_snapshot_hash TEXT NOT NULL,
        tool_assets_hash TEXT NOT NULL,
        runtime_lock_hash TEXT NOT NULL,
        runtime_proof_hash TEXT NOT NULL,
        immutable_manifest_json TEXT NOT NULL,
        immutable_manifest_hash TEXT NOT NULL,
        snakemake_manifest_json TEXT NOT NULL,
        snakemake_manifest_hash TEXT NOT NULL,
        previous_proof_hash TEXT,
        event_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        proof_hash TEXT NOT NULL,
        UNIQUE(attempt_id, lease_generation, process_ordinal),
        UNIQUE(proof_hash),
        UNIQUE(event_id),
        FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT,
        FOREIGN KEY (authorization_id)
            REFERENCES agent_run_authorizations(authorization_id) ON DELETE RESTRICT,
        FOREIGN KEY (attempt_id) REFERENCES run_attempts(attempt_id) ON DELETE RESTRICT,
        FOREIGN KEY (source_attempt_id) REFERENCES run_attempts(attempt_id) ON DELETE RESTRICT,
        FOREIGN KEY (workflow_revision_id)
            REFERENCES workflow_revisions(workflow_revision_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_workspace_proofs_run_boundary
    ON agent_workspace_proofs(run_id, process_boundary, process_ordinal)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_workspace_proofs_authorization
    ON agent_workspace_proofs(authorization_id, process_ordinal)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_workspace_proofs_no_update
    BEFORE UPDATE ON agent_workspace_proofs
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_WORKSPACE_PROOF_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_workspace_proofs_no_delete
    BEFORE DELETE ON agent_workspace_proofs
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_WORKSPACE_PROOF_IMMUTABLE');
    END
    """,
)

AGENT_WORKSPACE_PROOF_SCHEMA_SQL = "\n".join(
    f"{statement.strip()};" for statement in AGENT_WORKSPACE_PROOF_SCHEMA_STATEMENTS
)

_SCHEMA_OBJECT_IDENTITIES = (
    ("table", "agent_workspace_proofs"),
    ("index", "idx_agent_workspace_proofs_run_boundary"),
    ("index", "idx_agent_workspace_proofs_authorization"),
    ("trigger", "agent_workspace_proofs_no_update"),
    ("trigger", "agent_workspace_proofs_no_delete"),
)
_EXPECTED_COLUMNS = (
    (0, "workspace_proof_id", "TEXT", 0, None, 1),
    (1, "contract_version", "TEXT", 1, None, 0),
    (2, "run_id", "TEXT", 1, None, 0),
    (3, "authorization_id", "TEXT", 1, None, 0),
    (4, "attempt_id", "TEXT", 1, None, 0),
    (5, "lease_generation", "INTEGER", 1, None, 0),
    (6, "source_attempt_id", "TEXT", 0, None, 0),
    (7, "process_boundary", "TEXT", 1, None, 0),
    (8, "process_ordinal", "INTEGER", 1, None, 0),
    (9, "workflow_revision_id", "TEXT", 1, None, 0),
    (10, "workflow_revision_content_hash", "TEXT", 1, None, 0),
    (11, "workflow_revision_manifest_hash", "TEXT", 1, None, 0),
    (12, "run_spec_hash", "TEXT", 1, None, 0),
    (13, "input_snapshot_hash", "TEXT", 1, None, 0),
    (14, "tool_assets_hash", "TEXT", 1, None, 0),
    (15, "runtime_lock_hash", "TEXT", 1, None, 0),
    (16, "runtime_proof_hash", "TEXT", 1, None, 0),
    (17, "immutable_manifest_json", "TEXT", 1, None, 0),
    (18, "immutable_manifest_hash", "TEXT", 1, None, 0),
    (19, "snakemake_manifest_json", "TEXT", 1, None, 0),
    (20, "snakemake_manifest_hash", "TEXT", 1, None, 0),
    (21, "previous_proof_hash", "TEXT", 0, None, 0),
    (22, "event_id", "TEXT", 1, None, 0),
    (23, "created_at", "TEXT", 1, None, 0),
    (24, "proof_hash", "TEXT", 1, None, 0),
)
_EXPECTED_UNIQUE_COLUMN_SETS = (
    ("attempt_id", "lease_generation", "process_ordinal"),
    ("event_id",),
    ("proof_hash",),
)
_EXPECTED_FOREIGN_KEYS = (
    ("attempt_id", "run_attempts", "attempt_id", "NO ACTION", "RESTRICT", "NONE"),
    (
        "authorization_id",
        "agent_run_authorizations",
        "authorization_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    ("run_id", "runs", "run_id", "NO ACTION", "RESTRICT", "NONE"),
    (
        "source_attempt_id",
        "run_attempts",
        "attempt_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    (
        "workflow_revision_id",
        "workflow_revisions",
        "workflow_revision_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
)

_EXPECTED_OBJECT_SQL = {
    identity: " ".join(statement.replace("IF NOT EXISTS", "").split()).casefold()
    for identity, statement in zip(
        _SCHEMA_OBJECT_IDENTITIES,
        AGENT_WORKSPACE_PROOF_SCHEMA_STATEMENTS,
        strict=True,
    )
}

RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_agent_workspace_proof_schema(connection: sqlite3.Connection) -> None:
    for statement in AGENT_WORKSPACE_PROOF_SCHEMA_STATEMENTS:
        connection.execute(statement)


def assert_agent_workspace_proof_schema(connection: sqlite3.Connection) -> None:
    for object_type, object_name in _SCHEMA_OBJECT_IDENTITIES:
        row = connection.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = ?",
            (object_name,),
        ).fetchone()
        if row is None or str(row[0]) != object_type or row[1] is None:
            _raise_schema_mismatch(f"missing-or-wrong-type:{object_name}")
        actual_sql = " ".join(str(row[1]).split()).casefold()
        if actual_sql != _EXPECTED_OBJECT_SQL[(object_type, object_name)]:
            _raise_schema_mismatch(f"object-sql:{object_name}")

    columns = tuple(
        (
            int(row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            None if row[4] is None else str(row[4]),
            int(row[5]),
        )
        for row in connection.execute(
            "PRAGMA table_info(agent_workspace_proofs)"
        ).fetchall()
    )
    if columns != _EXPECTED_COLUMNS:
        _raise_schema_mismatch("columns")

    unique_column_sets = tuple(
        sorted(
            tuple(
                str(column[2])
                for column in connection.execute(
                    f"PRAGMA index_info({_quote_pragma_identifier(str(index[1]))})"
                ).fetchall()
            )
            for index in connection.execute(
                "PRAGMA index_list(agent_workspace_proofs)"
            ).fetchall()
            if bool(index[2]) and str(index[3]) == "u"
        )
    )
    if unique_column_sets != _EXPECTED_UNIQUE_COLUMN_SETS:
        _raise_schema_mismatch("unique-constraints")

    foreign_keys = tuple(
        sorted(
            (
                str(row[3]),
                str(row[2]),
                str(row[4]),
                str(row[5]).upper(),
                str(row[6]).upper(),
                str(row[7]).upper(),
            )
            for row in connection.execute(
                "PRAGMA foreign_key_list(agent_workspace_proofs)"
            ).fetchall()
        )
    )
    if foreign_keys != _EXPECTED_FOREIGN_KEYS:
        _raise_schema_mismatch("foreign-keys")


def migrate_agent_workspace_proof_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
    version: int = 20,
    name: str = "020_agent_workspace_proof",
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_schema_migrations_table(connection)
        ensure_agent_workspace_proof_schema(connection)
        assert_agent_workspace_proof_schema(connection)
        record_migration(connection, version, name)
        connection.execute(f"PRAGMA user_version = {int(version)}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _raise_schema_mismatch(component: str) -> None:
    raise RuntimeError(
        f"{AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH}: {component}"
    )


def _quote_pragma_identifier(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
