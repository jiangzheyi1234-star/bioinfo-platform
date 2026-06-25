from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import list_lineage_edges_for_run, list_run_artifact_edges
from apps.remote_runner.candidate_output_storage import record_candidate_output
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.rule_cache_restore_adoption_storage import (
    apply_rule_cache_restore_adoption,
    prepare_rule_cache_restore_adoption,
)
from apps.remote_runner.rule_staged_restore_promotion_storage import apply_rule_cache_restore_final_outputs
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_pin_routes import _run_and_edge_state
from tests.test_rule_staged_restore_promotion_storage import _active_staged_restore_run


def test_rule_cache_restore_adoption_adopts_promoted_candidates_without_run_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before = _run_job_and_command_state(cfg, run_id)

    unrelated_path = tmp_path / "unrelated.txt"
    unrelated_path.write_text("not part of restored outputs\n", encoding="utf-8")
    unrelated = record_candidate_output(
        cfg,
        run_id=run_id,
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        output_key="unrelated",
        path=unrelated_path,
        observed_at="2099-06-07T10:03:30Z",
    )

    prepared = prepare_rule_cache_restore_adoption(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
    )
    assert prepared["schemaVersion"] == "rule-cache-restore-adoption-prepare-result.v1"
    assert prepared["status"] == "ready"
    assert prepared["targetCount"] == 1
    assert prepared["adoptedArtifactCount"] == 0
    assert prepared["activePinCount"] == 1

    result = apply_rule_cache_restore_adoption(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:04:00Z",
    )

    assert result["schemaVersion"] == "rule-cache-restore-adoption-apply-result.v1"
    assert result["status"] == "applied"
    assert result["adoptedArtifactCount"] == 1
    assert result["verifiedCandidateOutputCount"] == 1
    assert result["releasedPinCount"] == 1
    assert result["runStateMutated"] is False
    assert result["retryEnqueued"] is False
    assert result["pathExposed"] is False
    assert result["storageUriExposed"] is False
    assert result["cacheKeyExposed"] is False
    assert _run_job_and_command_state(cfg, run_id) == before

    results = fetch_run_results(cfg, run_id)
    assert results["artifactCount"] == 1
    assert results["artifacts"][0]["artifactKey"] == "bam"
    assert results["artifacts"][0]["sha256"]
    assert [pin["state"] for pin in list_artifact_cache_pins(cfg)["items"]] == ["released"]
    active_edges = list_run_artifact_edges(cfg, run_id)
    assert len(active_edges) == 1
    assert active_edges[0]["portName"] == "bam"
    all_edges = list_run_artifact_edges(cfg, run_id, include_inactive=True)
    assert {edge["lifecycleState"] for edge in all_edges} == {"active", "invalidated"}
    lineage = list_lineage_edges_for_run(cfg, run_id)
    assert len(lineage) == 1
    assert lineage[0]["predicate"] == "h2ometa:cache_adopted"
    promotion_state = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]["finalOutputPromotionState"]
    assert promotion_state["state"] == "applied"
    assert promotion_state["adoptedCandidateOutputCount"] == 1

    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.adoption_applied.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    assert evidence["payload"]["releasedPinCount"] == 1
    with get_connection(cfg) as connection:
        unrelated_row = connection.execute(
            "SELECT verification_state, adopted_artifact_id FROM candidate_outputs WHERE candidate_output_id = ?",
            (unrelated["candidateOutputId"],),
        ).fetchone()
    assert unrelated_row["verification_state"] == "pending"
    assert unrelated_row["adopted_artifact_id"] is None


def test_rule_cache_restore_adoption_apply_is_idempotent_after_pin_release(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_idempotent")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]

    first = apply_rule_cache_restore_adoption(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:04:00Z",
    )
    plan_after = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    second = apply_rule_cache_restore_adoption(
        cfg,
        plan_after,
        plan_hash=plan_after["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:05:00Z",
    )

    assert first["adoptedArtifactCount"] == 1
    assert first["releasedPinCount"] == 1
    assert second["adoptedArtifactCount"] == 1
    assert second["releasedPinCount"] == 0
    assert fetch_run_results(cfg, run_id)["artifactCount"] == 1
    assert len(list_lineage_edges_for_run(cfg, run_id)) == 1


def test_rule_cache_restore_adoption_can_use_cache_source_artifact_metadata(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_source_metadata")
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT run_spec_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        run_spec = dict(json.loads(run["run_spec_json"]))
        run_spec.pop("outputSchema", None)
        source = connection.execute(
            """
            SELECT artifacts.mime_type
            FROM artifact_cache_entries AS entries
            JOIN artifacts ON artifacts.artifact_id = entries.artifact_id
            LIMIT 1
            """
        ).fetchone()
        connection.execute(
            "UPDATE runs SET run_spec_json = ? WHERE run_id = ?",
            (json.dumps(run_spec, sort_keys=True), run_id),
        )
        connection.commit()
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]

    result = apply_rule_cache_restore_adoption(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
    )

    assert result["status"] == "applied"
    assert fetch_run_results(cfg, run_id)["artifacts"][0]["mimeType"] == source["mime_type"]


def test_rule_cache_restore_adoption_rejects_missing_output_metadata_without_artifact_mutation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_bad_schema")
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT run_spec_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        run_spec = dict(json.loads(run["run_spec_json"]))
        run_spec.pop("outputSchema", None)
        connection.execute(
            "UPDATE runs SET run_spec_json = ? WHERE run_id = ?",
            (json.dumps(run_spec, sort_keys=True), run_id),
        )
        source = connection.execute("SELECT artifact_id FROM artifact_cache_entries LIMIT 1").fetchone()
        connection.execute("UPDATE artifacts SET kind = '', mime_type = '' WHERE artifact_id = ?", (source["artifact_id"],))
        connection.commit()
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]

    try:
        apply_rule_cache_restore_adoption(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )
    except ValueError as exc:
        assert str(exc) == "RULE_CACHE_RESTORE_ADOPTION_CACHE_ARTIFACT_METADATA_REQUIRED"
    else:
        raise AssertionError("expected missing output metadata to fail loudly")
    assert fetch_run_results(cfg, run_id)["artifactCount"] == 0
    assert list_evidence_events(cfg, event_type="rule.cache_restore.adoption_applied.v1") == []


def _promoted_restore_run(cfg: Any, tmp_path: Path, run_id: str) -> tuple[str, dict[str, Any]]:
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, run_id)
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    apply_rule_cache_restore_final_outputs(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        now="2099-06-07T10:03:00Z",
    )
    return run_id, claim


def _run_job_and_command_state(cfg: Any, run_id: str) -> dict[str, Any]:
    state = _run_and_edge_state(cfg, run_id)
    return {
        "run": state["run"],
        "job": state["job"],
        "commandCount": state["commandCount"],
    }
