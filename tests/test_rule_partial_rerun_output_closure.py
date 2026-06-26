from __future__ import annotations

from pathlib import Path

from apps.remote_runner.artifact_ledger_storage import record_artifact_blob_for_path, record_run_artifact_edge
from apps.remote_runner.rule_partial_rerun_output_closure import build_rule_partial_rerun_output_closure
from apps.remote_runner.storage import create_run_record
from tests.helpers.reference_database import make_configured_remote_runner


def test_rule_partial_rerun_output_closure_marks_contract_ready_when_declared_outputs_are_adopted(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_output_closure")
    preserved_path = Path(cfg.results_dir) / "run_output_closure" / "trim.txt"
    preserved_path.parent.mkdir(parents=True, exist_ok=True)
    preserved_path.write_text("trim output\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(cfg, path=preserved_path, media_type="text/plain")
    record_run_artifact_edge(
        cfg,
        run_id="run_output_closure",
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name="trim_qc",
        step_id="trim_reads",
    )

    closure = build_rule_partial_rerun_output_closure(
        cfg,
        run={"runId": "run_output_closure"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["schemaVersion"] == "rule-partial-rerun-output-closure.v1"
    assert closure["available"] is True
    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is True
    assert closure["reasonCode"] == "RULE_PARTIAL_RERUN_OUTPUT_CLOSURE_READY"
    assert closure["scopedOutputCount"] == 1
    assert closure["adoptedScopedOutputCount"] == 1
    assert closure["pendingScopedOutputCount"] == 0
    assert closure["declaredOutputCount"] == 1
    assert closure["checkedDeclaredOutputCount"] == 1
    assert closure["verifiedDeclaredOutputCount"] == 1
    assert closure["adoptedDeclaredOutputCount"] == 1
    assert closure["missingDeclaredOutputCount"] == 0
    assert closure["rerunRequiredDeclaredOutputCount"] == 0
    assert closure["allDeclaredOutputsVerified"] is True
    assert closure["preservedOutputEdgeCount"] == 1
    assert closure["missingPreservedOutputEdgeCount"] == 0
    assert closure["unknownActiveOutputEdgeCount"] == 0
    assert closure["finalizeAllowed"] is False
    assert closure["pathExposed"] is False
    assert closure["storageUriExposed"] is False


def test_rule_partial_rerun_output_closure_blocks_unadopted_declared_outputs_after_edges_close(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_output_closure_unadopted")
    preserved_path = Path(cfg.results_dir) / "run_output_closure_unadopted" / "trim.txt"
    preserved_path.parent.mkdir(parents=True, exist_ok=True)
    preserved_path.write_text("trim output\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(cfg, path=preserved_path, media_type="text/plain")
    record_run_artifact_edge(
        cfg,
        run_id="run_output_closure_unadopted",
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name="trim_qc",
        step_id="trim_reads",
    )

    closure = build_rule_partial_rerun_output_closure(
        cfg,
        run={"runId": "run_output_closure_unadopted"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_audit=_output_audit(state="adopted", adopted_output_count=0),
    )

    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is False
    assert closure["allDeclaredOutputsVerified"] is False
    assert closure["adoptedDeclaredOutputCount"] == 0
    assert closure["declaredOutputBlockedReasonCodes"] == ["RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_ADOPTED"]
    assert closure["blockedReasonCodes"] == ["RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_ADOPTED"]


def test_rule_partial_rerun_output_closure_blocks_incomplete_declared_output_audit_after_edges_close(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_output_closure_incomplete")
    _record_preserved_edge(cfg, "run_output_closure_incomplete")
    audit = _output_audit(state="adopted")
    audit["expectedOutputCount"] = 2

    closure = build_rule_partial_rerun_output_closure(
        cfg,
        run={"runId": "run_output_closure_incomplete"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_audit=audit,
    )

    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is False
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_INCOMPLETE" in closure[
        "declaredOutputBlockedReasonCodes"
    ]
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_INCOMPLETE" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_declared_output_schema_and_redaction(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_output_closure_redaction")
    _record_preserved_edge(cfg, "run_output_closure_redaction")
    audit = _output_audit(state="adopted")
    audit["schemaVersion"] = "legacy-rule-output-audit.v0"
    audit["pathExposed"] = True

    closure = build_rule_partial_rerun_output_closure(
        cfg,
        run={"runId": "run_output_closure_redaction"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_audit=audit,
    )

    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is False
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_SCHEMA_UNSUPPORTED" in closure[
        "declaredOutputBlockedReasonCodes"
    ]
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_REDACTION_UNSAFE" in closure[
        "declaredOutputBlockedReasonCodes"
    ]


def test_rule_partial_rerun_output_closure_blocks_pending_and_unknown_edges(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _create_run(cfg, "run_output_closure_blocked")
    unknown_path = Path(cfg.results_dir) / "run_output_closure_blocked" / "unknown.txt"
    unknown_path.parent.mkdir(parents=True, exist_ok=True)
    unknown_path.write_text("unknown output\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(cfg, path=unknown_path, media_type="text/plain")
    record_run_artifact_edge(
        cfg,
        run_id="run_output_closure_blocked",
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name="unexpected",
        step_id="unexpected_rule",
    )

    closure = build_rule_partial_rerun_output_closure(
        cfg,
        run={"runId": "run_output_closure_blocked"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_audit=_output_audit(state="present"),
    )

    assert closure["edgeClosureReady"] is False
    assert closure["closureReady"] is False
    assert "RULE_PARTIAL_RERUN_SCOPED_OUTPUT_ADOPTION_PENDING" in closure["blockedReasonCodes"]
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING" in closure["blockedReasonCodes"]
    assert "RULE_PARTIAL_RERUN_UNKNOWN_ACTIVE_OUTPUTS" in closure["blockedReasonCodes"]
    assert closure["pendingScopedOutputCount"] == 1
    assert closure["missingPreservedOutputEdgeCount"] == 1
    assert closure["unknownActiveOutputEdgeCount"] == 1


def _create_run(cfg, run_id: str) -> None:
    create_run_record(
        cfg,
        server_id="srv_output_closure",
        request_id=f"req_{run_id}",
        run_spec={"runId": run_id, "pipelineId": "demo"},
        idempotency_key=f"idem_{run_id}",
        payload_hash="f" * 64,
    )


def _record_preserved_edge(cfg, run_id: str) -> None:
    preserved_path = Path(cfg.results_dir) / run_id / "trim.txt"
    preserved_path.parent.mkdir(parents=True, exist_ok=True)
    preserved_path.write_text("trim output\n", encoding="utf-8")
    blob = record_artifact_blob_for_path(cfg, path=preserved_path, media_type="text/plain")
    record_run_artifact_edge(
        cfg,
        run_id=run_id,
        artifact_blob_id=blob["artifactBlobId"],
        role="output",
        port_name="trim_qc",
        step_id="trim_reads",
    )


def _rule_retry_plan() -> dict:
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": "run_output_closure",
        "preservedRules": [
            {
                "runRuleId": "rr_trim",
                "ruleName": "trim_reads",
                "stepId": "trim_reads",
                "runtimeStatusKey": "rule:trim_reads",
            }
        ],
    }


def _cache_restore_plan() -> dict:
    return {
        "schemaVersion": "rule-cache-restore-plan.v1",
        "rules": [
            {
                "ruleName": "align",
                "stepId": "align",
                "invalidationRole": "selected_failed_rule",
                "outputs": [
                    {
                        "artifactKey": "bam",
                        "stepId": "align",
                        "outputOrdinal": 1,
                        "cacheHit": True,
                    }
                ],
            }
        ],
    }


def _output_audit(*, state: str, adopted_output_count: int | None = None) -> dict:
    missing_count = 1 if state == "missing" else 0
    rerun_required_count = 1 if state == "missing" else 0
    adopted_count = 1 if state == "adopted" else 0
    if adopted_output_count is not None:
        adopted_count = adopted_output_count
    return {
        "schemaVersion": "rule-output-audit.v1",
        "available": True,
        "expectedOutputCount": 1,
        "checkedOutputCount": 1,
        "verifiedOutputCount": 1,
        "adoptedOutputCount": adopted_count,
        "missingOutputCount": missing_count,
        "rerunRequiredOutputCount": rerun_required_count,
        "unsafeOutputCount": 0,
        "uncheckedOutputCount": 0,
        "unverifiedOutputCount": 0,
        "pathExposed": False,
        "storageUriExposed": False,
        "reasonCode": "OUTPUT_AUDIT_VERIFIED",
        "outputs": [
            {
                "stepId": "align",
                "outputOrdinal": 1,
                "state": state,
                "verificationState": "verified",
                "rerunRequired": state == "missing",
                "checksumVerified": True,
            }
        ],
    }
