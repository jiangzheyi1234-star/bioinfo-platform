from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import record_artifact_blob_for_path, record_run_artifact_edge
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.rule_cache_restore_plan import build_rule_cache_restore_plan
from apps.remote_runner.rule_output_invalidation_plan import build_rule_output_invalidation_plan
from apps.remote_runner.rule_output_invalidation_storage import apply_rule_output_invalidation_plan
from apps.remote_runner.rule_restore_pin_policy import (
    RESTORE_PIN_ACTIVE_LEASE_REQUIRED,
    restore_pin_owner_id,
)
from apps.remote_runner.rule_restore_pin_storage import (
    apply_rule_cache_restore_pins,
    prepare_rule_cache_restore_pins,
    release_rule_cache_restore_pins,
)
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import StaleRunAttemptError
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_restore_pin_prepare_is_side_effect_free_and_redacted(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_restore_pin_source", workflow_revision_id=workflow_revision_id)
    _mark_run_completed(cfg, source_run["runId"])
    current_run = _create_run(cfg, "run_restore_pin_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    claim = claim_next_run_job(cfg, worker_id="worker_restore_pin", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None
    plan = _applied_cache_restore_plan(cfg, current_run, workflow_revision_id)

    result = prepare_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
    )

    assert result["schemaVersion"] == "rule-cache-restore-pin-prepare-result.v1"
    assert result["status"] == "ready"
    assert result["eligiblePinCount"] == 1
    assert result["preparedPinCount"] == 0
    assert result["pinCreationAllowed"] is True
    assert result["ownerKind"] == "run_attempt"
    assert result["pinScope"] == "restore"
    assert result["ownerIdExposed"] is False
    assert result["cacheKeyExposed"] is False
    assert result["storageUriExposed"] is False
    assert result["pathExposed"] is False
    assert list_artifact_cache_pins(cfg)["items"] == []
    assert list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1") == []
    assert list_evidence_events(cfg, event_type="artifact.cache.lookup.v1") == []
    with get_connection(cfg) as connection:
        hit_counts = [row["hit_count"] for row in connection.execute("SELECT hit_count FROM artifact_cache_entries")]
    assert hit_counts == [0]

    serialized = json.dumps({"result": result}, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized


def test_rule_restore_pin_apply_creates_attempt_scoped_pins_without_lookup_or_restore_side_effects(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_restore_pin_apply_source", workflow_revision_id=workflow_revision_id)
    _mark_run_completed(cfg, source_run["runId"])
    current_run = _create_run(cfg, "run_restore_pin_apply_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    claim = claim_next_run_job(cfg, worker_id="worker_restore_pin_apply", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None
    plan = _applied_cache_restore_plan(cfg, current_run, workflow_revision_id)
    before_run_state = _run_job_state(cfg, current_run["runId"])
    before_edges = _output_edge_state(cfg, current_run["runId"])

    result = apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        actor="restore-worker",
        reason="apply partial restore pins",
        now="2099-06-07T10:01:00Z",
    )

    pins = list_artifact_cache_pins(cfg)["items"]
    events = list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1")
    assert result["schemaVersion"] == "rule-cache-restore-pin-apply-result.v1"
    assert result["status"] == "applied"
    assert result["appliedPinCount"] == 1
    assert result["createdPinCount"] == 1
    assert result["reusedPinCount"] == 0
    assert result["cacheEntryCount"] == 1
    assert result["cachePinIds"] == [pins[0]["cachePinId"]]
    assert result["ownerIdExposed"] is False
    assert result["cacheKeyExposed"] is False
    assert result["storageUriExposed"] is False
    assert pins[0]["pinScope"] == "restore"
    assert pins[0]["ownerKind"] == "run_attempt"
    assert pins[0]["ownerId"] == restore_pin_owner_id(claim["attemptId"], claim["leaseGeneration"])
    assert pins[0]["state"] == "active"
    assert pins[0]["expiresAt"] == "2099-06-07T11:01:00Z"
    assert len(events) == 1
    assert events[0]["eventId"] == result["evidenceId"]
    assert events[0]["payload"]["cachePinCount"] == 1
    assert events[0]["payload"]["createdPinCount"] == 1
    assert events[0]["payload"]["reusedPinCount"] == 0
    assert events[0]["payload"]["actorPresent"] is True
    assert _run_job_state(cfg, current_run["runId"]) == before_run_state
    assert _output_edge_state(cfg, current_run["runId"]) == before_edges
    assert list_evidence_events(cfg, event_type="artifact.cache.lookup.v1") == []
    with get_connection(cfg) as connection:
        hit_counts = [row["hit_count"] for row in connection.execute("SELECT hit_count FROM artifact_cache_entries")]
    assert hit_counts == [0]

    second = apply_rule_cache_restore_pins(
        cfg,
        plan,
        plan_hash=plan["planHash"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        actor="restore-worker",
        now="2099-06-07T10:02:00Z",
    )

    assert second["cachePinIds"] == result["cachePinIds"]
    assert second["appliedPinCount"] == 1
    assert second["createdPinCount"] == 0
    assert second["reusedPinCount"] == 1
    assert len(list_artifact_cache_pins(cfg)["items"]) == 1
    assert len(list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1")) == 2

    serialized = json.dumps(
        {"result": result, "second": second, "events": events},
        sort_keys=True,
    )
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized

    released = release_rule_cache_restore_pins(
        cfg,
        cache_pin_ids=result["cachePinIds"],
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        reason="restore complete",
        now="2099-06-07T10:02:00Z",
    )
    released_pins = list_artifact_cache_pins(cfg)["items"]
    release_events = list_evidence_events(cfg, event_type="rule.cache_restore.pins_released.v1")
    assert released["releasedPinCount"] == 1
    assert released_pins[0]["state"] == "released"
    assert released_pins[0]["releasedAt"] == "2099-06-07T10:02:00Z"
    assert release_events[0]["payload"]["cachePinCount"] == 1


def test_rule_restore_pin_prepare_rejects_stale_lease_before_pin_creation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_restore_pin_stale_source", workflow_revision_id=workflow_revision_id)
    _mark_run_completed(cfg, source_run["runId"])
    current_run = _create_run(cfg, "run_restore_pin_stale_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    claim = claim_next_run_job(cfg, worker_id="worker_restore_pin_stale", now="2099-06-07T10:00:00Z")
    assert claim is not None
    plan = _applied_cache_restore_plan(cfg, current_run, workflow_revision_id)

    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        prepare_rule_cache_restore_pins(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]) + 1,
        )
    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        apply_rule_cache_restore_pins(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]) + 1,
        )

    assert list_artifact_cache_pins(cfg)["items"] == []
    assert list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1") == []
    assert list_evidence_events(cfg, event_type="artifact.cache.lookup.v1") == []


def test_rule_restore_pin_prepare_requires_applied_output_invalidation(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    revision = _create_revision(cfg)
    workflow_revision_id = str(revision["workflowRevisionId"])
    source_run = _create_run(cfg, "run_restore_pin_unapplied_source", workflow_revision_id=workflow_revision_id)
    _mark_run_completed(cfg, source_run["runId"])
    current_run = _create_run(cfg, "run_restore_pin_unapplied_current", workflow_revision_id=workflow_revision_id)
    persist_artifact(
        cfg,
        run_id=source_run["runId"],
        kind="bam",
        path=_managed_output(cfg, source_run["runId"], "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _output_edge(cfg, tmp_path, run_id=current_run["runId"], step_id="align", port_name="bam")
    claim = claim_next_run_job(cfg, worker_id="worker_restore_pin_unapplied", now="2099-06-07T10:00:00Z")
    assert claim is not None
    rule_retry_plan = _rule_retry_plan(current_run["runId"], workflow_revision_id)
    output_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )
    plan = build_rule_cache_restore_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
        output_invalidation_plan=output_invalidation_plan,
    )

    with pytest.raises(ValueError, match="RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED"):
        prepare_rule_cache_restore_pins(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )
    with pytest.raises(ValueError, match="RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED"):
        apply_rule_cache_restore_pins(
            cfg,
            plan,
            plan_hash=plan["planHash"],
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )

    assert RESTORE_PIN_ACTIVE_LEASE_REQUIRED not in plan["restorePinPolicy"]["blockedReasonCodes"]
    assert list_artifact_cache_pins(cfg)["items"] == []


def _applied_cache_restore_plan(cfg, current_run: dict[str, Any], workflow_revision_id: str) -> dict[str, Any]:
    rule_retry_plan = _rule_retry_plan(current_run["runId"], workflow_revision_id)
    output_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )
    apply_rule_output_invalidation_plan(
        cfg,
        output_invalidation_plan,
        plan_hash=output_invalidation_plan["planHash"],
        now="2099-06-07T10:00:30Z",
    )
    applied_invalidation_plan = build_rule_output_invalidation_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
    )
    return build_rule_cache_restore_plan(
        cfg,
        run=current_run,
        rule_retry_plan=rule_retry_plan,
        output_invalidation_plan=applied_invalidation_plan,
    )


def _create_revision(cfg) -> dict[str, Any]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_rule_restore_pin",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "snake"}]},
        graph_snapshot={"nodes": [{"id": "align"}]},
        runtime_lock={"snakemake": "9.23.1", "python": "3.12"},
        compiler={"name": "h2ometa", "version": "rule-restore-pin-test"},
    )


def _create_run(cfg, run_id: str, *, workflow_revision_id: str) -> dict[str, Any]:
    run_spec = _run_spec(run_id, workflow_revision_id)
    create_run_record(
        cfg,
        server_id="srv_rule_restore_pin",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    return {"runId": run_id, "workflowRevisionId": workflow_revision_id, "runSpec": run_spec}


def _mark_run_completed(cfg, run_id: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2099-06-07T09:59:00Z',
                last_updated_at = '2099-06-07T09:59:00Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'completed',
                updated_at = '2099-06-07T09:59:00Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.commit()


def _run_spec(run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    return {
        "runId": run_id,
        "projectId": "proj_rule_restore_pin",
        "pipelineId": "pipeline_rule_restore_pin",
        "pipelineVersion": "0.1.0",
        "workflowRevisionId": workflow_revision_id,
        "inputs": [{"name": "reads", "sha256": "sha256:reads"}],
        "params": {"threshold": 3},
        "resourceBindings": {"taxonomy": {"databaseId": "db_ref", "templateId": "kraken2"}},
        "execution": {"profile": "default"},
    }


def _managed_output(cfg, run_id: str, filename: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _output_edge(cfg, tmp_path: Path, *, run_id: str, step_id: str, port_name: str) -> dict[str, Any]:
    path = tmp_path / f"{run_id}-{step_id}-{port_name}.txt"
    path.write_text(f"{step_id}:{port_name}\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(
        cfg,
        path=path,
        media_type="text/plain",
        created_at="2099-06-07T10:00:00Z",
    )
    return record_run_artifact_edge(
        cfg,
        run_id=run_id,
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name=port_name,
        step_id=step_id,
        created_at="2099-06-07T10:00:01Z",
    )


def _run_job_state(cfg, run_id: str) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT status, stage FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        job = connection.execute("SELECT state, execution_options_json FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ?",
            (run_id,),
        ).fetchone()["count"]
    return {
        "run": dict(run),
        "job": dict(job),
        "commandCount": int(command_count),
    }


def _output_edge_state(cfg, run_id: str) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT edge_id, lifecycle_state, invalidation_event_id
            FROM run_artifact_edges
            WHERE run_id = ?
            ORDER BY edge_id
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _rule_retry_plan(run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    selected_attempt = {
        "attemptId": "att_failed",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "status": "failed",
    }
    align = {
        "runRuleId": "rr_align",
        "ruleName": "align",
        "stepId": "align",
        "runtimeStatusKey": "rule:align",
        "status": "failed",
        "attemptId": selected_attempt["attemptId"],
        "leaseGeneration": selected_attempt["leaseGeneration"],
        "attemptNumber": selected_attempt["attemptNumber"],
        "selectedAttempt": selected_attempt,
    }
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id,
        "invalidationPlanAvailable": True,
        "rules": [align],
        "invalidatedRules": [align],
        "preservedRules": [],
        "blockedReasonCodes": ["CACHE_ADOPTION_UNPROVEN", "ARTIFACT_ADOPTION_UNPROVEN"],
    }
