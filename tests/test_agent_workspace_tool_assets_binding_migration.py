from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import sqlite_migrations
from apps.remote_runner.agent_process_instance_schema import (
    AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH,
    assert_agent_process_instance_schema,
    migrate_agent_process_instance_schema,
)
from apps.remote_runner.agent_process_instance_v22_schema import (
    AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE,
    AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,
)
from apps.remote_runner.agent_schema_migration_guard import (
    AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID,
)
from apps.remote_runner import agent_workspace_proof_storage
from apps.remote_runner.agent_workspace_tool_assets_binding_migration import (
    AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID,
    AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID,
    AgentWorkspaceToolAssetsBindingMigrationError,
)
from apps.remote_runner.sqlite_schema_checksums import (
    V21_SCHEMA_MIGRATION_NAME,
    V21_SCHEMA_VERSION,
    runtime_schema_ledger_checksum,
)
from apps.remote_runner.sqlite_migrations import (
    CURRENT_SCHEMA_MIGRATION_NAME,
    CURRENT_SCHEMA_VERSION,
    initialize_or_migrate_runtime_db,
)
from core.contracts.agent_workspace_proof import (
    agent_workspace_proof_hash,
    agent_workspace_proof_id,
    build_agent_workspace_proof_v1,
)
from tests.helpers.reference_database import make_remote_runner_config
from tests.agent_process_instance_schema_fixtures import (
    connection as process_connection,
    downgrade_process_schema,
    insert_prepared,
    seed_intent,
)


TIMESTAMP = "2099-06-07T10:00:00Z"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _proof_payload(tag: str) -> dict[str, object]:
    proof = build_agent_workspace_proof_v1(
        {
            "runId": f"run-{tag}",
            "authorizationId": f"authorization-{tag}",
            "attemptId": f"attempt-{tag}",
            "leaseGeneration": 1,
            "sourceAttemptId": None,
            "processBoundary": "pre_dry_run",
            "processOrdinal": 1,
            "workflowRevisionId": f"revision-{tag}",
            "workflowRevisionContentHash": _hash(f"revision-content-{tag}"),
            "workflowRevisionManifestHash": _hash(f"revision-manifest-{tag}"),
            "runSpecHash": _hash(f"run-spec-{tag}"),
            "inputSnapshotHash": _hash(f"input-snapshot-{tag}"),
            "runtimeLockHash": _hash(f"runtime-lock-{tag}"),
            "runtimeProofHash": _hash(f"runtime-proof-{tag}"),
            "immutableManifest": [
                {
                    "relativePath": "run-config.json",
                    "size": 10,
                    "sha256": _hash(f"run-config-{tag}"),
                },
                {
                    "relativePath": "workflow/Snakefile",
                    "size": 20,
                    "sha256": _hash(f"snakefile-{tag}"),
                },
                {
                    "relativePath": f"workflow/private/{tag}.smk",
                    "size": 30,
                    "sha256": _hash(f"private-rule-{tag}"),
                },
            ],
            "snakemakeManifest": [],
            "previousProofHash": None,
            "eventId": f"event-{tag}",
            "createdAt": TIMESTAMP,
        }
    )
    return proof.runtime_payload()


def _legacy_forged_tool_hash_payload(tag: str) -> dict[str, object]:
    payload = _proof_payload(tag)
    payload["toolAssetsHash"] = _hash(f"caller-chosen-tool-assets-{tag}")
    payload["proofHash"] = agent_workspace_proof_hash(payload)
    payload["workspaceProofId"] = agent_workspace_proof_id(str(payload["proofHash"]))
    return payload


def _insert_proof(connection: sqlite3.Connection, payload: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO agent_workspace_proofs (
            workspace_proof_id, contract_version, run_id, authorization_id,
            attempt_id, lease_generation, source_attempt_id, process_boundary,
            process_ordinal, workflow_revision_id,
            workflow_revision_content_hash, workflow_revision_manifest_hash,
            run_spec_hash, input_snapshot_hash, tool_assets_hash,
            runtime_lock_hash, runtime_proof_hash, immutable_manifest_json,
            immutable_manifest_hash, snakemake_manifest_json,
            snakemake_manifest_hash, previous_proof_hash, event_id,
            created_at, proof_hash
        ) VALUES (
            :workspaceProofId, :contractVersion, :runId, :authorizationId,
            :attemptId, :leaseGeneration, :sourceAttemptId, :processBoundary,
            :processOrdinal, :workflowRevisionId,
            :workflowRevisionContentHash, :workflowRevisionManifestHash,
            :runSpecHash, :inputSnapshotHash, :toolAssetsHash,
            :runtimeLockHash, :runtimeProofHash, :immutableManifestJson,
            :immutableManifestHash, :snakemakeManifestJson,
            :snakemakeManifestHash, :previousProofHash, :eventId,
            :createdAt, :proofHash
        )
        """,
        {
            **payload,
            "sourceAttemptId": payload["sourceAttemptId"] or None,
            "immutableManifestJson": _stable_json(payload["immutableManifest"]),
            "snakemakeManifestJson": _stable_json(payload["snakemakeManifest"]),
        },
    )


def _prepare_populated_v21(
    db_path: Path,
    *payloads: dict[str, object],
) -> None:
    initialize_or_migrate_runtime_db(db_path)
    downgrade_process_schema(db_path)
    with sqlite3.connect(db_path) as connection:
        migrate_agent_process_instance_schema(
            connection,
            record_migration=sqlite_migrations._record_migration,
        )
        for payload in payloads:
            _insert_proof(connection, payload)


def _proof_rows(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        return [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM agent_workspace_proofs ORDER BY workspace_proof_id"
            ).fetchall()
        ]


def test_populated_v21_valid_proofs_migrate_without_rewrite(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(
        db_path,
        _proof_payload("valid-one"),
        _proof_payload("valid-two"),
    )
    before = _proof_rows(db_path)
    expected_v21_checksum = runtime_schema_ledger_checksum(
        V21_SCHEMA_VERSION,
        V21_SCHEMA_MIGRATION_NAME,
    )
    assert expected_v21_checksum == (
        "586b075d1574c2ac9d5240c84b9d5de292a711701d4f384fd0d76493a1e75d8c"
    )
    with sqlite3.connect(db_path) as connection:
        v21_checksum = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 21"
        ).fetchone()[0]
        v21_event_guard = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'agent_process_instances_run_events_no_update'"
        ).fetchone()[0]
        assert_agent_process_instance_schema(connection, schema_version=21)
    assert v21_checksum == expected_v21_checksum
    assert "OLD.event_id IN" in v21_event_guard

    initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        ledger = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = 22"
        ).fetchone()
        index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,),
        ).fetchone()
        v22_event_guard = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'agent_process_instances_run_events_no_update'"
        ).fetchone()[0]
        assert_agent_process_instance_schema(connection)
    assert version == CURRENT_SCHEMA_VERSION == 22
    assert ledger == (CURRENT_SCHEMA_MIGRATION_NAME,)
    assert "UNIQUE INDEX" in str(index[0]).upper()
    assert "OLD.schema_version = 'run-event.v2'" in v22_event_guard
    assert _proof_rows(db_path) == before


def test_v21_upgrade_rejects_extra_trigger_without_partial_v22(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TRIGGER forged_runtime_side_effect "
            "AFTER INSERT ON uploads BEGIN SELECT 1; END"
        )

    with pytest.raises(
        RuntimeError,
        match=(
            rf"^{AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID}: "
            r"runtime-triggers$"
        ),
    ):
        initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None


def test_v21_well_formed_wrong_checksum_fails_atomically(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path, _proof_payload("checksum"))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 21",
            ("0" * 64,),
        )

    with pytest.raises(
        RuntimeError,
        match=rf"{AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID}: prior-ledger",
    ):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,),
        ).fetchone() is None


def test_v21_missing_required_table_fails_atomically(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path, _proof_payload("missing-baseline"))
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE uploads")

    with pytest.raises(
        RuntimeError,
        match=f"^{AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_BASELINE_INVALID}$",
    ):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,),
        ).fetchone() is None


def test_v21_event_guard_must_match_exact_stage9a_sql(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path, _proof_payload("event-guard"))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DROP TRIGGER agent_process_instances_run_events_no_update"
        )
        connection.execute(
            "CREATE TRIGGER agent_process_instances_run_events_no_update "
            "BEFORE UPDATE ON run_events BEGIN SELECT 1; END"
        )

    with pytest.raises(
        RuntimeError,
        match=AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH,
    ):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,),
        ).fetchone() is None


def test_v21_duplicate_logical_activity_fails_atomically(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path)
    with process_connection(db_path) as connection:
        first = seed_intent(connection, tag="logical-first")
        second = seed_intent(connection, tag="logical-second")
        insert_prepared(connection, first, logical_activity_id="shared-activity")
        insert_prepared(connection, second, logical_activity_id="shared-activity")

    with pytest.raises(RuntimeError, match=f"^{AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE}$"):
        initialize_or_migrate_runtime_db(db_path)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 21
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_process_instances"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,),
        ).fetchone() is None


def test_populated_v21_forged_tool_hash_fails_atomically_and_path_free(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    valid = _proof_payload("valid-before-forged")
    forged = _legacy_forged_tool_hash_payload("tenant-secret")
    assert agent_workspace_proof_hash(forged) == forged["proofHash"]
    _prepare_populated_v21(db_path, valid, forged)
    before = _proof_rows(db_path)

    with pytest.raises(
        AgentWorkspaceToolAssetsBindingMigrationError,
        match=f"^{AGENT_WORKSPACE_TOOL_ASSETS_BINDING_MIGRATION_PROOF_INVALID}$",
    ) as captured:
        initialize_or_migrate_runtime_db(db_path)

    assert "workflow/private/tenant-secret.smk" not in str(captured.value)
    with sqlite3.connect(db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        ledger = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone()
    assert version == 21
    assert ledger is None
    assert _proof_rows(db_path) == before


def test_current_v22_startup_keeps_structural_readiness_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    _prepare_populated_v21(db_path, _proof_payload("startup"))
    initialize_or_migrate_runtime_db(db_path)

    def fail_if_rescanned(row: sqlite3.Row) -> dict[str, object]:
        raise AssertionError(f"unexpected proof rescan: {row!r}")

    monkeypatch.setattr(
        agent_workspace_proof_storage,
        "agent_workspace_proof_row_to_dict",
        fail_if_rescanned,
    )
    initialize_or_migrate_runtime_db(db_path)
