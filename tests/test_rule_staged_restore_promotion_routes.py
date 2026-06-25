from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.evidence_storage import list_evidence_events
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner
from tests.test_rule_cache_restore_pin_routes import _run_and_edge_state
from tests.test_rule_staged_restore_promotion_storage import (
    _active_staged_restore_run,
    _final_output_path,
)


def test_rule_staged_restore_promotion_prepare_route_is_ready_without_final_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_prepare_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)
    final_path = _final_output_path(cfg, claim)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/prepare",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "prepare-rule-cache-restore-final-outputs",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed final output promotion",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "ready"
    assert result["finalOutputCount"] == 1
    assert result["finalOutputMutated"] is False
    assert result["candidateOutputRecorded"] is False
    assert not final_path.exists()
    assert _candidate_count(cfg, run_id) == 0
    assert _run_and_edge_state(cfg, run_id) == before_state
    assert list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1") == []
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.final_outputs.prepare")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARED"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_final_outputs"
    assert audit[0]["details"]["finalOutputCount"] == 1
    assert audit[0]["details"]["createdFinalOutputCount"] == 0
    assert audit[0]["details"]["pathExposed"] is False
    assert "reviewed final output promotion" not in json.dumps(audit[0]["details"], sort_keys=True)


def test_rule_staged_restore_promotion_apply_route_promotes_and_records_safe_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_apply_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    before_state = _run_and_edge_state(cfg, run_id)
    final_path = _final_output_path(cfg, claim)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-final-outputs",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
            "actor": "operator",
            "reason": "reviewed final output promotion",
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "applied"
    assert result["finalOutputCount"] == 1
    assert result["createdFinalOutputCount"] == 1
    assert result["finalOutputMutated"] is True
    assert result["candidateOutputRecorded"] is True
    assert result["runStateMutated"] is False
    assert final_path.read_bytes() == b"cached align\n"
    assert _candidate_count(cfg, run_id) == 1
    assert _run_and_edge_state(cfg, run_id) == before_state

    evidence = list_evidence_events(cfg, event_type="rule.cache_restore.final_outputs_promoted.v1")[0]
    assert evidence["eventId"] == result["evidenceId"]
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.final_outputs.apply")["items"]
    assert audit[0]["decision"] == "allow"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLIED"
    assert audit[0]["details"]["finalOutputCount"] == 1
    assert audit[0]["details"]["createdFinalOutputCount"] == 1
    assert audit[0]["details"]["candidateOutputCount"] == 1
    serialized_public = json.dumps({"result": result, "audit": audit}, sort_keys=True)
    assert '"cacheKey":' not in serialized_public
    assert '"storageUri":' not in serialized_public
    assert "file://" not in serialized_public
    assert str(tmp_path) not in serialized_public
    assert "reviewed final output promotion" not in serialized_public


def test_rule_staged_restore_promotion_apply_route_rejects_stale_plan_hash_before_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_stale_plan_route")
    final_path = _final_output_path(cfg, claim)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-final-outputs",
            "planHash": "0" * 64,
            "attemptId": claim["attemptId"],
            "leaseGeneration": claim["leaseGeneration"],
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"
    public_plan = detail["ruleCacheRestorePlan"]
    assert public_plan["schemaVersion"] == "rule-cache-restore-final-output-public-plan.v1"
    assert public_plan["attemptFinalOutputPromotionAllowed"] is True
    assert not final_path.exists()
    assert _candidate_count(cfg, run_id) == 0
    detail_text = json.dumps(detail, sort_keys=True)
    assert "cacheEntryId" not in detail_text
    assert "artifactBlobId" not in detail_text
    assert '"storageUri":' not in detail_text
    assert str(tmp_path) not in detail_text
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.final_outputs.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["reasonCode"] == "RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH"


def test_rule_staged_restore_promotion_apply_route_rejects_lease_mismatch_without_final_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    run_id, claim = _active_staged_restore_run(cfg, tmp_path, "run_final_output_stale_lease_route")
    plan = fetch_run_execution_context(cfg, run_id)["ruleCacheRestorePlan"]
    final_path = _final_output_path(cfg, claim)

    response = TestClient(app).post(
        f"/api/v1/runs/{run_id}/rules/cache-restore/final-outputs/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-final-outputs",
            "planHash": plan["planHash"],
            "attemptId": claim["attemptId"],
            "leaseGeneration": int(claim["leaseGeneration"]) + 1,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RUN_ATTEMPT_STALE"
    assert not final_path.exists()
    assert _candidate_count(cfg, run_id) == 0
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.final_outputs.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["reasonCode"] == "RUN_ATTEMPT_STALE"


def test_rule_staged_restore_promotion_apply_route_denies_wrong_role_before_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("auditor",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_context_read(*_args, **_kwargs):
        raise AssertionError("execution context must not be read before authorization")

    monkeypatch.setattr(
        "apps.remote_runner.rule_staged_restore_promotion_service.fetch_run_execution_context",
        fail_context_read,
    )
    response = TestClient(app).post(
        "/api/v1/runs/run_final_output_denied/rules/cache-restore/final-outputs/apply",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "confirmation": "apply-rule-cache-restore-final-outputs",
            "planHash": "0" * 64,
            "attemptId": "att_denied",
            "leaseGeneration": 1,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    audit = list_governance_audit_events(cfg, action="run.rule_cache_restore.final_outputs.apply")["items"]
    assert audit[0]["decision"] == "deny"
    assert audit[0]["subjectKind"] == "run_rule_cache_restore_final_outputs"
    assert audit[0]["subjectId"] == "authorization"


def _candidate_count(cfg: Any, run_id: str) -> int:
    with get_connection(cfg) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM candidate_outputs WHERE run_id = ?",
                (run_id,),
            ).fetchone()["count"]
        )
