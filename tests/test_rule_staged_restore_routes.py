from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.rule_restore_pin_storage import apply_rule_cache_restore_pins
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_pin_routes import (
    _create_active_rule_cache_restore_run,
    _run_and_edge_state,
)


def test_rule_staged_restore_prepare_route_is_ready_without_materialization(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_staged_restore_prepare_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/staged-files/prepare",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "prepare-rule-cache-restore-staged-files",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed staged restore scope",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "ready"
    assert result["stagedFileCount"] == 1
    assert result["restorePinCount"] == 1
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.staged_files.prepare")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_STAGED_FILES_PREPARED"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_staged_files"
    assert audit[0]["details"] == {
        "planHash": plan["planHash"],
        "previewAvailable": True,
        "enabled": False,
        "materializationEnabled": True,
        "attemptStagingAllowed": True,
        "overwriteAllowed": False,
        "deleteUnknownOutputs": False,
        "requestReasonProvided": True,
        "attemptProvided": True,
        "leaseGenerationProvided": True,
        "targetCount": 1,
        "managedTargetCount": 1,
        "cacheHitTargetCount": 1,
        "cacheMissTargetCount": 0,
        "unmappedTargetCount": 0,
        "unknownOutputCount": 0,
        "restorePinnedCount": 0,
        "blockedReasonCodes": ["STAGED_FILE_MATERIALIZATION_PIN_REQUIRED"],
        "stagedFileCount": 1,
        "preparedStagedFileCount": 0,
        "createdStagedFileCount": 0,
        "reusedStagedFileCount": 0,
        "restorePinCount": 1,
    }
    assert "reviewed staged restore scope" not in json.dumps(audit[0]["details"], sort_keys=True)


def test_rule_staged_restore_apply_route_materializes_and_records_safe_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_staged_restore_apply_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)
    before_artifacts = _artifact_count(cfg, run_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/staged-files/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-staged-files",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed staged restore scope",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "applied"
    assert result["stagedFileCount"] == 1
    assert result["createdStagedFileCount"] == 1
    assert result["finalOutputMutated"] is False
    assert result["runStateMutated"] is False
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert _artifact_count(cfg, run_id) == before_artifacts
    assert list_artifact_cache_pins(cfg)["items"][0]["state"] == "active"
    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    assert Path(evidence["payload"]["stagedLocalPaths"][0]).is_file()
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.staged_files.apply")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_STAGED_FILES_APPLIED"
    serialized_public = json.dumps({"result": result, "audit": audit}, sort_keys=True)
    assert '"cacheKey":' not in serialized_public
    assert '"storageUri":' not in serialized_public
    assert str(tmp_path) not in serialized_public
    assert "reviewed staged restore scope" not in serialized_public


def test_rule_staged_restore_apply_route_rejects_stale_plan_hash_before_mutation(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_staged_restore_stale_route")

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/staged-files/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-staged-files",
            "planHash": "0" * 64,
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"
    public_plan = detail["ruleCacheRestorePlan"]
    assert public_plan["schemaVersion"] == "rule-cache-restore-staged-file-public-plan.v1"
    assert public_plan["materializationEnabled"] is True
    detail_text = json.dumps(detail, sort_keys=True)
    assert "cacheEntryId" not in detail_text
    assert "artifactBlobId" not in detail_text
    assert '"storageUri":' not in detail_text
    assert str(tmp_path) not in detail_text
    assert list_evidence_events(cfg, event_type="rule.cache_restore.staged_files_applied.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.staged_files.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"


def test_rule_staged_restore_apply_route_denies_wrong_role_before_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("auditor",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("execution context must not be read before authorization")

    monkeypatch.setattr("apps.remote_runner.run_reexecution_service.fetch_run_execution_context", fail_context_read)
    response = TestClient(app).post(
        "/api/v1/runs/run_staged_restore_denied/rules/cache-restore/staged-files/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-staged-files",
            "planHash": "0" * 64,
            "attemptId": "att_denied",
            "leaseGeneration": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.staged_files.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_staged_files"
    assert audit[0]["subjectId"] == "authorization"


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
    return run_id, claim


def _artifact_count(cfg: Any, run_id: str) -> int:
    with get_connection(cfg) as connection:
        return int(connection.execute("SELECT COUNT(*) AS count FROM artifacts WHERE run_id = ?", (run_id,)).fetchone()["count"])
