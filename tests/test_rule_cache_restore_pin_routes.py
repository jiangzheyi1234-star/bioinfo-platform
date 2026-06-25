from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.artifact_ledger_storage import record_artifact_blob_for_path, record_lineage_edge, record_run_artifact_edge
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.rule_execution_storage import upsert_run_rule_state
from apps.remote_runner.rule_output_invalidation_storage import apply_rule_output_invalidation_plan
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_cache_restore_pin_prepare_route_is_ready_without_pin_mutation(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_rule_restore_pin_prepare")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/pins/prepare",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "prepare-rule-cache-restore-pins",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed restore pin scope",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "ready"
    assert result["eligiblePinCount"] == 1
    assert result["preparedPinCount"] == 0
    assert list_artifact_cache_pins(cfg)["items"] == []
    assert list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.pins.prepare")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_PINS_PREPARED"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_pins"
    assert audit[0]["details"] == {
        "planHash": plan["planHash"],
        "previewAvailable": True,
        "creationEnabled": True,
        "pinCreationAllowed": False,
        "requestReasonProvided": True,
        "attemptProvided": True,
        "leaseGenerationProvided": True,
        "candidatePinCount": 1,
        "requiredPinCount": 1,
        "eligiblePinCount": 1,
        "blockedPinCount": 0,
        "blockedReasonCodes": ["RESTORE_PIN_ACTIVE_LEASE_REQUIRED"],
        "preparedPinCount": 0,
    }
    assert "operator" not in json.dumps(audit[0]["details"], sort_keys=True)


def test_rule_cache_restore_pin_apply_route_creates_pins_and_records_safe_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_rule_restore_pin_apply")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/pins/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-pins",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed restore pin scope",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    pins = list_artifact_cache_pins(cfg)["items"]
    assert result["status"] == "applied"
    assert result["appliedPinCount"] == 1
    assert result["createdPinCount"] == 1
    assert result["reusedPinCount"] == 0
    assert result["cachePinIds"] == [pins[0]["cachePinId"]]
    assert pins[0]["pinScope"] == "restore"
    assert pins[0]["ownerKind"] == "run_attempt"
    assert pins[0]["state"] == "active"
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert list_evidence_events(cfg, event_type="artifact.cache.lookup.v1") == []
    with get_connection(cfg) as connection:
        hit_counts = [row["hit_count"] for row in connection.execute("SELECT hit_count FROM artifact_cache_entries")]
    assert hit_counts == [0]

    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.pins_applied.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    assert evidence["payload"]["cachePinCount"] == 1
    assert evidence["payload"]["createdPinCount"] == 1
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.pins.apply")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_PINS_APPLIED"
    assert audit[0]["details"] == {
        "planHash": plan["planHash"],
        "previewAvailable": True,
        "creationEnabled": True,
        "pinCreationAllowed": False,
        "requestReasonProvided": True,
        "attemptProvided": True,
        "leaseGenerationProvided": True,
        "candidatePinCount": 1,
        "requiredPinCount": 1,
        "eligiblePinCount": 1,
        "blockedPinCount": 0,
        "blockedReasonCodes": ["RESTORE_PIN_ACTIVE_LEASE_REQUIRED"],
        "appliedPinCount": 1,
        "createdPinCount": 1,
        "reusedPinCount": 0,
        "cacheEntryCount": 1,
    }
    serialized = json.dumps({"audit": audit, "evidence": evidence}, sort_keys=True)
    assert '"cacheKey":' not in serialized
    assert '"storageUri":' not in serialized
    assert str(tmp_path) not in serialized
    assert "reviewed restore pin scope" not in serialized


def test_rule_cache_restore_pin_apply_route_rejects_stale_plan_hash_before_mutation(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _create_active_rule_cache_restore_run(cfg, tmp_path, "run_rule_restore_pin_stale")

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/pins/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-pins",
            "planHash": "0" * 64,
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"
    public_plan = detail["ruleCacheRestorePlan"]
    assert public_plan["schemaVersion"] == "rule-cache-restore-pin-public-plan.v1"
    assert public_plan["eligiblePinCount"] == 1
    detail_text = json.dumps(detail, sort_keys=True)
    assert "cacheEntryId" not in detail_text
    assert "artifactBlobId" not in detail_text
    assert '"storageUri":' not in detail_text
    assert str(tmp_path) not in detail_text
    assert list_artifact_cache_pins(cfg)["items"] == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.pins.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"


def test_rule_cache_restore_pin_apply_route_denies_wrong_role_before_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("auditor",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("execution context must not be read before authorization")

    monkeypatch.setattr("apps.remote_runner.run_reexecution_service.fetch_run_execution_context", fail_context_read)
    response = TestClient(app).post(
        "/api/v1/runs/run_rule_restore_pin_denied/rules/cache-restore/pins/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-pins",
            "planHash": "0" * 64,
            "attemptId": "att_denied",
            "leaseGeneration": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.pins.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_pins"
    assert audit[0]["subjectId"] == "authorization"


def _create_active_rule_cache_restore_run(cfg, tmp_path: Path, run_id: str) -> tuple[str, dict[str, Any]]:
    workflow_revision_id = _create_failed_rule_revision(cfg, run_id)
    source_run_id = f"{run_id}_source"
    _create_run(cfg, source_run_id, workflow_revision_id=workflow_revision_id)
    _mark_run_completed(cfg, source_run_id)
    persist_artifact(
        cfg,
        run_id=source_run_id,
        kind="bam",
        path=_managed_output(cfg, source_run_id, "align.bam", b"cached align\n"),
        mime_type="application/octet-stream",
        artifact_key="bam",
        step_id="align",
    )
    _create_run(cfg, run_id, workflow_revision_id=workflow_revision_id)
    claim = claim_next_run_job(cfg, worker_id=f"worker_{run_id}", now="2099-06-07T10:00:00Z", lease_seconds=30)
    assert claim is not None
    for rule_name, status in (("trim_reads", "succeeded"), ("align", "failed"), ("report", "blocked")):
        upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=rule_name,
            runtime_status_key=f"rule:{rule_name}",
            status=status,
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
            attempt_number=int(claim["attempt"]["attemptNumber"]),
        )
    align = _output_edge(cfg, tmp_path, run_id=run_id, step_id="align", port_name="bam")
    _lineage(cfg, run_id=run_id, edge=align, workflow_revision_id=workflow_revision_id)
    output_plan = fetch_run_execution_context(cfg, run_id)["ruleOutputInvalidationPlan"]
    assert output_plan["invalidationEnabled"] is True
    apply_rule_output_invalidation_plan(cfg, output_plan, plan_hash=output_plan["planHash"])
    return run_id, claim


def _create_failed_rule_revision(cfg, run_id: str) -> str:
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"wfd_{run_id}",
        draft_revision=1,
        manifest={"schemaVersion": "workflow-revision-manifest.v1", "files": []},
        graph_snapshot={
            "schemaVersion": "workflow-graph-snapshot.v1",
            "runSpec": {
                "workflow": {
                    "nodes": [
                        {"id": "trim_reads", "toolRevisionId": "tool_trim"},
                        {"id": "align", "toolRevisionId": "tool_align"},
                        {"id": "report", "toolRevisionId": "tool_report"},
                    ],
                    "edges": [
                        {"from": {"nodeId": "trim_reads", "port": "reads"}, "to": {"nodeId": "align", "port": "reads"}},
                        {"from": {"nodeId": "align", "port": "bam"}, "to": {"nodeId": "report", "port": "bam"}},
                    ],
                }
            },
        },
        runtime_lock={"schemaVersion": "runtime-lock.v1"},
        compiler={"name": "test", "version": "1"},
    )
    return str(revision["workflowRevisionId"])


def _create_run(cfg, run_id: str, *, workflow_revision_id: str | None) -> None:
    create_run_record(
        cfg,
        server_id="srv_rule_restore_pin_route",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_rule_restore_pin_route",
            "pipelineId": "pipeline_rule_restore_pin_route",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
            "workflowRevisionId": workflow_revision_id,
            "execution": {
                "outputs": {"bam": "align.bam"},
                "retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0},
            },
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )


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


def _managed_output(cfg, run_id: str, filename: str, payload: bytes) -> Path:
    path = Path(cfg.results_dir) / run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _output_edge(cfg, tmp_path: Path, *, run_id: str, step_id: str, port_name: str) -> dict[str, Any]:
    path = tmp_path / f"{run_id}-{step_id}-{port_name}.txt"
    path.write_text(f"{step_id}:{port_name}\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(cfg, path=path, media_type="text/plain", created_at="2099-06-07T10:00:00Z")
    return record_run_artifact_edge(
        cfg,
        run_id=run_id,
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name=port_name,
        step_id=step_id,
        created_at="2099-06-07T10:00:01Z",
    )


def _lineage(cfg, *, run_id: str, edge: dict[str, Any], workflow_revision_id: str) -> None:
    record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id=str(edge["artifactBlobId"]),
        run_id=run_id,
        workflow_revision_id=workflow_revision_id,
        payload={
            "runArtifactEdgeId": edge["edgeId"],
            "portName": edge["portName"],
            "stepId": edge["stepId"],
        },
        content_hash=str(edge["contentHash"]),
        created_at="2099-06-07T10:00:02Z",
    )


def _run_and_edge_state(cfg, run_id: str) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        run = connection.execute("SELECT status, stage FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        job = connection.execute("SELECT state, execution_options_json FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        command_count = connection.execute(
            "SELECT COUNT(*) AS count FROM run_commands WHERE run_id = ?",
            (run_id,),
        ).fetchone()["count"]
        edges = connection.execute(
            """
            SELECT edge_id, lifecycle_state, invalidation_event_id
            FROM run_artifact_edges
            WHERE run_id = ?
            ORDER BY edge_id
            """,
            (run_id,),
        ).fetchall()
    return {
        "run": dict(run),
        "job": dict(job),
        "commandCount": int(command_count),
        "edges": [dict(edge) for edge in edges],
    }
