from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.artifact_cache_storage import list_artifact_cache_pins
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_adoption_storage import _promoted_restore_run, _run_job_and_command_state


def test_rule_cache_restore_adoption_prepare_route_is_side_effect_free(tmp_path: Path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_prepare_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before = _run_job_and_command_state(cfg, run_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/adoption/prepare",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "prepare-rule-cache-restore-adoption",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed restored output adoption",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "ready"
    assert result["targetCount"] == 1
    assert result["adoptedArtifactCount"] == 0
    assert result["activePinCount"] == 1
    assert fetch_run_results(cfg, run_id)["artifactCount"] == 0
    assert _run_job_and_command_state(cfg, run_id) == before
    assert list_evidence_events(cfg, event_type="rule.cache_restore.adoption_applied.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.adoption.prepare")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_adoption"
    assert audit[0]["details"]["resultTargetCount"] == 1
    assert audit[0]["details"]["pathExposed"] is False
    assert "reviewed restored output adoption" not in json.dumps(audit[0]["details"], sort_keys=True)


def test_rule_cache_restore_adoption_apply_route_adopts_and_records_safe_audit(tmp_path: Path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_apply_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before = _run_job_and_command_state(cfg, run_id)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/adoption/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-adoption",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed restored output adoption",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "applied"
    assert result["adoptedArtifactCount"] == 1
    assert result["verifiedCandidateOutputCount"] == 1
    assert result["releasedPinCount"] == 1
    assert result["runStateMutated"] is False
    assert result["retryEnqueued"] is False
    assert fetch_run_results(cfg, run_id)["artifactCount"] == 1
    assert _run_job_and_command_state(cfg, run_id) == before
    assert [pin["state"] for pin in list_artifact_cache_pins(cfg)["items"]] == ["released"]

    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.adoption_applied.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.adoption.apply")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_ADOPTION_APPLIED"
    assert audit[0]["details"]["resultAdoptedArtifactCount"] == 1
    assert audit[0]["details"]["resultReleasedPinCount"] == 1
    serialized_public = json.dumps({"result": result, "audit": audit}, sort_keys=True)
    assert '"cacheKey":' not in serialized_public
    assert '"storageUri":' not in serialized_public
    assert "file://" not in serialized_public
    assert str(tmp_path) not in serialized_public
    assert "reviewed restored output adoption" not in serialized_public


def test_rule_cache_restore_adoption_apply_route_rejects_stale_plan_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _promoted_restore_run(cfg, tmp_path, "run_rule_cache_restore_adopt_stale_route")

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/adoption/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-adoption",
            "planHash": "0" * 64,
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"
    assert detail["ruleCacheRestorePlan"]["schemaVersion"] == "rule-cache-restore-adoption-public-plan.v1"
    assert fetch_run_results(cfg, run_id)["artifactCount"] == 0
    assert [pin["state"] for pin in list_artifact_cache_pins(cfg)["items"]] == ["active"]
    serialized_detail = json.dumps(detail, sort_keys=True)
    assert "cacheEntryId" not in serialized_detail
    assert '"storageUri":' not in serialized_detail
    assert str(tmp_path) not in serialized_detail
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.adoption.apply")["items"]
    assert audit[0]["decision"] == "deny"


def test_rule_cache_restore_adoption_apply_route_denies_wrong_role_before_read(tmp_path: Path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("auditor",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("execution context must not be read before authorization")

    monkeypatch.setattr(
        "apps.remote_runner.rule_cache_restore_adoption_service.fetch_run_execution_context",
        fail_context_read,
    )
    response = TestClient(app).post(
        "/api/v1/runs/run_rule_cache_restore_adopt_denied/rules/cache-restore/adoption/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-adoption",
            "planHash": "0" * 64,
            "attemptId": "att_denied",
            "leaseGeneration": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.adoption.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_adoption"
    assert audit[0]["subjectId"] == "authorization"
