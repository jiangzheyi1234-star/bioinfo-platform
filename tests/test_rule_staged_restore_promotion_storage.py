from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.rule_restore_pin_storage import apply_rule_cache_restore_pins
from apps.remote_runner.rule_staged_restore_promotion_storage import (
    apply_rule_cache_restore_final_outputs,
    prepare_rule_cache_restore_final_outputs,
)
from apps.remote_runner.rule_staged_restore_storage import apply_rule_cache_restore_staged_files
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_pin_routes import (
    _create_active_rule_cache_restore_run,
    _run_and_edge_state,
)


def test_rule_staged_restore_final_output_prepare_is_side_effect_free(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_prepare")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)
    final_path = _final_output_path(cfg, claim)
    assert not final_path.exists()

    result = prepare_rule_cache_restore_final_outputs(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
    )

    assert result["schemaVersion"] == "rule-cache-restore-final-output-prepare-result.v1"
    assert result["status"] == "ready"
    assert result["finalOutputCount"] == 1
    assert result["finalOutputMutated"] is False
    assert result["candidateOutputRecorded"] is False
    assert result["artifactLedgerMutated"] is False
    assert result["pathExposed"] is False
    assert result["storageUriExposed"] is False
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert not final_path.exists()
    assert _candidate_count(cfg, run_id) == 0
    assert list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1") == []

    serialized = json.dumps(result, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def test_rule_staged_restore_final_output_apply_promotes_to_attempt_outputs_without_adoption(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_apply")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)
    before_artifacts = _artifact_count(cfg, run_id)
    final_path = _final_output_path(cfg, claim)

    result = apply_rule_cache_restore_final_outputs(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        actor="operator",
        reason="promote staged cached output",
        now="2099-06-07T10:04:00Z",
    )

    assert result["schemaVersion"] == "rule-cache-restore-final-output-apply-result.v1"
    assert result["status"] == "applied"
    assert result["finalOutputCount"] == 1
    assert result["createdFinalOutputCount"] == 1
    assert result["reusedFinalOutputCount"] == 0
    assert result["candidateOutputCount"] == 1
    assert result["finalOutputMutated"] is True
    assert result["candidateOutputRecorded"] is True
    assert result["runStateMutated"] is False
    assert result["artifactLedgerMutated"] is False
    assert final_path.read_bytes() == b"cached align\n"
    assert _candidate_count(cfg, run_id) == 1
    assert _artifact_count(cfg, run_id) == before_artifacts
    assert _run_and_edge_state(cfg, run_id) == before_state
    promotion_state = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]["finalOutputPromotionState"]
    assert promotion_state["state"] == "applied"
    assert promotion_state["promotedFinalOutputCount"] == 1
    assert promotion_state["adoptedCandidateOutputCount"] == 0

    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    assert evidence["payload"]["candidateOutputIds"]
    assert Path(evidence["payload"]["finalOutputPaths"][0]).resolve() == final_path.resolve()

    second = apply_rule_cache_restore_final_outputs(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:05:00Z",
    )

    assert second["createdFinalOutputCount"] == 0
    assert second["reusedFinalOutputCount"] == 1
    assert _candidate_count(cfg, run_id) == 1
    assert len(list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1")) == 2

    serialized = json.dumps(result, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def test_rule_staged_restore_final_output_apply_rejects_stale_lease_without_file_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_stale")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    final_path = _final_output_path(cfg, claim)

    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        apply_rule_cache_restore_final_outputs(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]) + 1,
        )

    assert not final_path.exists()
    assert _candidate_count(cfg, run_id) == 0
    assert list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1") == []


def test_rule_staged_restore_final_output_apply_refuses_unowned_existing_output(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_existing")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    final_path = _final_output_path(cfg, claim)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(b"cached align\n")

    with pytest.raises(ValueError, match="FINAL_OUTPUT_PROMOTION_DESTINATION_EXISTS"):
        apply_rule_cache_restore_final_outputs(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )

    assert _candidate_count(cfg, run_id) == 0
    assert list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1") == []


def _active_staged_restore_run(cfg: Any, tmp_path: Path, run_id: str) -> tuple[str, dict[str, Any]]:
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, run_id)
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:01:00Z",
    )
    apply_rule_cache_restore_staged_files(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:02:00Z",
    )
    return run_id, claim


def _final_output_path(cfg: Any, claim: dict[str, Any]) -> Path:
    return (
        Path(cfg.results_dir)
        / "attempts"
        / str(claim["attemptId"])
        / f"generation-{int(claim['leaseGeneration'])}"
        / "align.bam"
    )


def _candidate_count(cfg: Any, run_id: str) -> int:
    with get_connection(cfg) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM candidate_outputs WHERE run_id = ?",
                (run_id,),
            ).fetchone()["count"]
        )


def _artifact_count(cfg: Any, run_id: str) -> int:
    with get_connection(cfg) as connection:
        return int(connection.execute("SELECT COUNT(*) AS count FROM artifacts WHERE run_id = ?", (run_id,)).fetchone()["count"])
