from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import list_artifact_materializations
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.rule_restore_pin_storage import apply_rule_cache_restore_pins
from apps.remote_runner.rule_staged_restore_storage import (
    apply_rule_cache_restore_staged_files,
    prepare_rule_cache_restore_staged_files,
)
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_pin_routes import (
    _create_active_rule_cache_restore_run,
    _run_and_edge_state,
)


def test_rule_staged_restore_prepare_is_side_effect_free_and_requires_active_pins(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_staged_restore_prepare")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]

    with pytest.raises(ValueError, match="STAGED_RESTORE_ACTIVE_PIN_REQUIRED"):
        prepare_rule_cache_restore_staged_files(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )

    apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:01:00Z",
    )
    before_state = _run_and_edge_state(cfg, run_id)

    result = prepare_rule_cache_restore_staged_files(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
    )

    assert result["schemaVersion"] == "rule-cache-restore-staged-file-prepare-result.v1"
    assert result["status"] == "ready"
    assert result["stagedFileCount"] == 1
    assert result["restorePinCount"] == 1
    assert result["preparedStagedFileCount"] == 0
    assert result["finalOutputMutated"] is False
    assert result["runStateMutated"] is False
    assert result["pathExposed"] is False
    assert result["storageUriExposed"] is False
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1") == []

    serialized = json.dumps(result, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def test_rule_staged_restore_apply_materializes_attempt_owned_payload_without_final_adoption(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_staged_restore_apply")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    pin_result = apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:01:00Z",
    )
    before_state = _run_and_edge_state(cfg, run_id)
    before_artifacts = _artifact_count(cfg, run_id)

    result = apply_rule_cache_restore_staged_files(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        actor="operator",
        reason="restore cached bam to attempt staging",
        now="2099-06-07T10:02:00Z",
    )

    assert result["schemaVersion"] == "rule-cache-restore-staged-file-apply-result.v1"
    assert result["status"] == "applied"
    assert result["stagedFileCount"] == 1
    assert result["createdStagedFileCount"] == 1
    assert result["reusedStagedFileCount"] == 0
    assert result["restorePinCount"] == 1
    assert result["finalOutputMutated"] is False
    assert result["runStateMutated"] is False
    assert result["stagingDirectoryExposed"] is False
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert _artifact_count(cfg, run_id) == before_artifacts
    assert list_artifact_cache_pins(cfg)["items"][0]["state"] == "active"

    events = list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1")
    assert len(events) == 1
    event = events[0]
    assert event["eventId"] == result["evidenceId"]
    assert event["payload"]["cachePinIds"] == pin_result["cachePinIds"]
    staged_path = Path(event["payload"]["stagedLocalPaths"][0])
    assert staged_path.is_file()
    assert staged_path.read_bytes() == b"cached align\n"
    assert str(staged_path).startswith(str(Path(cfg.work_dir).resolve()))
    materializations = list_artifact_materializations(cfg, event["payload"]["artifactBlobIds"][0])
    assert event["payload"]["materializationIds"][0] in {item["materializationId"] for item in materializations}

    second = apply_rule_cache_restore_staged_files(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:03:00Z",
    )

    assert second["createdStagedFileCount"] == 0
    assert second["reusedStagedFileCount"] == 1
    assert len(list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1")) == 2

    serialized = json.dumps(result, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def test_rule_staged_restore_rejects_stale_lease_before_materialization(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_staged_restore_stale")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:01:00Z",
    )

    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        apply_rule_cache_restore_staged_files(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]) + 1,
        )

    assert list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1") == []
    assert not (Path(cfg.work_dir) / "cache-restore-staging").exists()


def _artifact_count(cfg: Any, run_id: str) -> int:
    with get_connection(cfg) as connection:
        return int(connection.execute("SELECT COUNT(*) AS count FROM artifacts WHERE run_id = ?", (run_id,)).fetchone()["count"])
