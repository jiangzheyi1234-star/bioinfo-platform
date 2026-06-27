from __future__ import annotations

from apps.remote_runner.rule_partial_rerun_output_closure import build_rule_partial_rerun_output_closure


def test_rule_partial_rerun_output_closure_marks_contract_ready_when_declared_outputs_are_adopted() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure"},
        rule_retry_plan=_rule_retry_plan(),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(),
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
    assert closure["preservedOutputs"][0]["runArtifactEdgeId"] == "edge_trim"
    assert closure["preservedOutputs"][0]["ruleName"] == "trim_reads"


def test_rule_partial_rerun_output_closure_blocks_unadopted_declared_outputs_after_edges_close() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_unadopted"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_unadopted"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(),
        output_audit=_output_audit(state="adopted", adopted_output_count=0),
    )

    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is False
    assert closure["allDeclaredOutputsVerified"] is False
    assert closure["adoptedDeclaredOutputCount"] == 0
    assert closure["declaredOutputBlockedReasonCodes"] == ["RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_ADOPTED"]
    assert closure["blockedReasonCodes"] == ["RULE_PARTIAL_RERUN_DECLARED_OUTPUTS_NOT_ADOPTED"]


def test_rule_partial_rerun_output_closure_blocks_incomplete_declared_output_audit_after_edges_close() -> None:
    audit = _output_audit(state="adopted")
    audit["expectedOutputCount"] = 2

    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_incomplete"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_incomplete"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(),
        output_audit=audit,
    )

    assert closure["edgeClosureReady"] is True
    assert closure["closureReady"] is False
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_INCOMPLETE" in closure[
        "declaredOutputBlockedReasonCodes"
    ]
    assert "RULE_PARTIAL_RERUN_DECLARED_OUTPUT_AUDIT_INCOMPLETE" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_declared_output_schema_and_redaction() -> None:
    audit = _output_audit(state="adopted")
    audit["schemaVersion"] = "legacy-rule-output-audit.v0"
    audit["pathExposed"] = True

    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_redaction"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_redaction"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(),
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


def test_rule_partial_rerun_output_closure_blocks_pending_and_authoritative_unknown_edges() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_blocked"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_blocked"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(
            preserved_outputs=[],
            unmatched_outputs=[_unknown_output()],
        ),
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


def test_rule_partial_rerun_output_closure_blocks_without_authoritative_invalidation_plan() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_no_plan"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_no_plan"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan={
            "schemaVersion": "rule-output-invalidation-plan.v1",
            "previewAvailable": False,
            "reasonCode": "RULE_OUTPUT_INVALIDATION_PREFLIGHT_UNAVAILABLE",
            "outputEdgeSummary": {},
            "rules": [],
            "preservedOutputs": [],
            "unmatchedOutputs": [],
        },
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["edgeClosureReady"] is False
    assert "RULE_OUTPUT_INVALIDATION_PREFLIGHT_UNAVAILABLE" in closure["blockedReasonCodes"]
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_inconsistent_invalidation_counts() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_bad_counts"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_bad_counts"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(
            summary_override={"preservedOutputEdgeCount": 2},
        ),
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["edgeClosureReady"] is False
    assert "RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_COUNTS_INCONSISTENT" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_partial_preserved_rule_coverage() -> None:
    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_partial_preserved"},
        rule_retry_plan=_rule_retry_plan(
            run_id="run_output_closure_partial_preserved",
            preserved_rules=["trim_reads", "qc"],
        ),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(preserved_outputs=[_preserved_output()]),
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["edgeClosureReady"] is False
    assert closure["missingPreservedOutputEdgeCount"] == 1
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_preserved_output_rule_mismatch() -> None:
    mismatched = _preserved_output()
    mismatched["stepId"] = "legacy_orphan"

    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_mismatch"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_mismatch"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=_output_invalidation_plan(preserved_outputs=[mismatched]),
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["edgeClosureReady"] is False
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_RULE_UNMATCHED" in closure["blockedReasonCodes"]
    assert "RULE_PARTIAL_RERUN_PRESERVED_OUTPUT_EDGES_MISSING" in closure["blockedReasonCodes"]


def test_rule_partial_rerun_output_closure_blocks_invalidation_plan_redaction() -> None:
    output_invalidation_plan = _output_invalidation_plan()
    output_invalidation_plan["pathExposed"] = True

    closure = build_rule_partial_rerun_output_closure(
        run={"runId": "run_output_closure_plan_redaction"},
        rule_retry_plan=_rule_retry_plan(run_id="run_output_closure_plan_redaction"),
        cache_restore_plan=_cache_restore_plan(),
        output_invalidation_plan=output_invalidation_plan,
        output_audit=_output_audit(state="adopted"),
    )

    assert closure["edgeClosureReady"] is False
    assert "RULE_PARTIAL_RERUN_OUTPUT_INVALIDATION_REDACTION_UNSAFE" in closure["blockedReasonCodes"]
    assert closure["pathExposed"] is True


def _rule_retry_plan(
    *,
    run_id: str = "run_output_closure",
    preserved_rules: list[str] | None = None,
) -> dict:
    rules = preserved_rules or ["trim_reads"]
    return {
        "schemaVersion": "rule-retry-plan.v1",
        "runId": run_id,
        "preservedRules": [
            {
                "runRuleId": f"rr_{rule_name}",
                "ruleName": rule_name,
                "stepId": rule_name,
                "runtimeStatusKey": f"rule:{rule_name}",
            }
            for rule_name in rules
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


def _output_invalidation_plan(
    *,
    preserved_outputs: list[dict] | None = None,
    unmatched_outputs: list[dict] | None = None,
    summary_override: dict | None = None,
) -> dict:
    preserved = [_preserved_output()] if preserved_outputs is None else preserved_outputs
    unmatched = [] if unmatched_outputs is None else unmatched_outputs
    invalidated_outputs = [_invalidated_output()]
    summary = {
        "outputEdgeCount": len(invalidated_outputs) + len(preserved) + len(unmatched),
        "invalidatedOutputEdgeCount": len(invalidated_outputs),
        "selectedOutputEdgeCount": len(invalidated_outputs),
        "downstreamOutputEdgeCount": 0,
        "preservedOutputEdgeCount": len(preserved),
        "unmatchedOutputEdgeCount": len(unmatched),
        "invalidatedLineageEdgeCount": 1,
        "preservedLineageEdgeCount": len(preserved),
        "alreadyInvalidatedOutputEdgeCount": 0,
        "alreadyInvalidatedLineageEdgeCount": 0,
        "payloadDeletionAllowed": False,
        "lineageMutationAllowed": True,
        **(summary_override or {}),
    }
    return {
        "schemaVersion": "rule-output-invalidation-plan.v1",
        "previewAvailable": True,
        "reasonCode": "OUTPUT_EDGE_INVALIDATION_TOMBSTONE_READY",
        "pathExposed": False,
        "storageReferenceExposed": False,
        "outputEdgeSummary": summary,
        "rules": [
            {
                "ruleName": "align",
                "stepId": "align",
                "invalidationRole": "selected_failed_rule",
                "outputs": invalidated_outputs,
            }
        ],
        "preservedOutputs": preserved,
        "unmatchedOutputs": unmatched,
    }


def _invalidated_output() -> dict:
    return {
        "schemaVersion": "rule-output-edge-invalidation.v1",
        "runArtifactEdgeId": "edge_align",
        "role": "output",
        "portName": "bam",
        "stepId": "align",
        "contentHashPrefix": "aaaabbbbcccc",
        "lifecycleState": "active",
        "wouldDeletePayload": False,
        "lineageEdgeCount": 1,
        "lineageEdges": [],
    }


def _preserved_output() -> dict:
    return {
        "schemaVersion": "rule-output-edge-invalidation.v1",
        "runArtifactEdgeId": "edge_trim",
        "role": "output",
        "portName": "trim_qc",
        "stepId": "trim_reads",
        "contentHashPrefix": "dddd11112222",
        "lifecycleState": "active",
        "wouldDeletePayload": False,
        "lineageEdgeCount": 1,
        "lineageEdges": [],
    }


def _unknown_output() -> dict:
    return {
        "schemaVersion": "rule-output-edge-invalidation.v1",
        "runArtifactEdgeId": "edge_unknown",
        "role": "output",
        "portName": "unexpected",
        "stepId": "unexpected_rule",
        "contentHashPrefix": "eeee33334444",
        "lifecycleState": "active",
        "wouldDeletePayload": False,
        "lineageEdgeCount": 0,
        "lineageEdges": [],
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
