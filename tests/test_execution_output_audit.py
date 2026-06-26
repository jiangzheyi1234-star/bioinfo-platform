from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.candidate_output_storage import record_candidate_output
from apps.remote_runner.execution_output_audit import build_attempt_output_audit, build_rule_retry_output_audit
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_configured_remote_runner


def test_attempt_output_audit_checks_managed_absolute_and_relative_outputs(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    result_root = tmp_path / "results"
    work_dir = work_root / "attempts" / "att_1"
    result_dir = result_root / "run_1"
    work_output = work_dir / "relative.txt"
    result_output = result_dir / "report.txt"
    work_output.parent.mkdir(parents=True)
    result_output.parent.mkdir(parents=True)
    work_output.write_text("relative\n", encoding="utf-8")
    result_output.write_text("result\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps(
            {
                "outputs": {
                    "relative": "relative.txt",
                    "report": str(result_output),
                    "missing": str(result_dir / "missing.txt"),
                }
            }
        ),
        encoding="utf-8",
    )

    audit = build_attempt_output_audit(
        run={"runId": "run_1", "resultDir": str(result_dir)},
        attempts=[_attempt(work_dir)],
        managed_work_dir=work_root,
        managed_results_dir=result_root,
    )

    assert audit["schemaVersion"] == "run-output-audit.v1"
    assert audit["available"] is True
    assert audit["pathExposed"] is False
    assert audit["configAvailable"] is True
    assert audit["expectedOutputCount"] == 3
    assert audit["checkedOutputCount"] == 3
    assert audit["existingOutputCount"] == 2
    assert audit["missingOutputCount"] == 1
    assert audit["verifiedOutputCount"] == 3
    assert audit["checksumVerifiedOutputCount"] == 2
    assert audit["rerunRequiredOutputCount"] == 1
    assert audit["rerunRequired"] is True
    assert audit["unsafeOutputCount"] == 0
    assert audit["uncheckedOutputCount"] == 0
    assert audit["unverifiedOutputCount"] == 0
    assert audit["reasonCode"] == "OUTPUT_AUDIT_RERUN_REQUIRED"
    assert [item["state"] for item in audit["outputs"]] == ["present", "present", "missing"]
    assert [item["verificationState"] for item in audit["outputs"]] == ["verified", "verified", "verified"]
    assert [item["reasonCode"] for item in audit["outputs"]] == [
        "OUTPUT_PRESENT_CHECKSUM_VERIFIED",
        "OUTPUT_PRESENT_CHECKSUM_VERIFIED",
        "OUTPUT_MISSING_RERUN_REQUIRED",
    ]
    assert [item.get("checksumVerified") for item in audit["outputs"]] == [True, True, None]
    assert all("sha256" not in item for item in audit["outputs"])
    assert all(item["pathExposed"] is False and "path" not in item for item in audit["outputs"])


def test_attempt_output_audit_blocks_workdir_outside_managed_root(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_dir = tmp_path / "outside" / "att_1"
    work_dir.mkdir(parents=True)
    (work_dir / "run-config.json").write_text(json.dumps({"outputs": {"report": "report.txt"}}), encoding="utf-8")

    audit = build_attempt_output_audit(
        run={"runId": "run_1", "resultDir": ""},
        attempts=[_attempt(work_dir)],
        managed_work_dir=work_root,
        managed_results_dir=tmp_path / "results",
    )

    assert audit["available"] is False
    assert audit["configAvailable"] is False
    assert audit["reasonCode"] == "WORKDIR_OUTSIDE_MANAGED_ROOT"


def test_attempt_output_audit_reports_unsafe_and_unchecked_outputs(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    result_root = tmp_path / "results"
    work_dir = work_root / "attempts" / "att_1"
    outside = tmp_path / "outside" / "escape.txt"
    work_dir.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    outside.write_text("escape\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"escape": str(outside), "bad": 42}}),
        encoding="utf-8",
    )

    audit = build_attempt_output_audit(
        run={"runId": "run_1", "resultDir": str(result_root / "run_1")},
        attempts=[_attempt(work_dir)],
        managed_work_dir=work_root,
        managed_results_dir=result_root,
    )

    assert audit["available"] is False
    assert audit["expectedOutputCount"] == 2
    assert audit["checkedOutputCount"] == 1
    assert audit["unsafeOutputCount"] == 1
    assert audit["uncheckedOutputCount"] == 1
    assert audit["unverifiedOutputCount"] == 2
    assert audit["reasonCode"] == "OUTPUT_AUDIT_UNSAFE_REFERENCES"
    assert audit["rerunRequired"] is False
    assert [item["reasonCode"] for item in audit["outputs"]] == [
        "OUTPUT_PATH_OUTSIDE_MANAGED_ROOT",
        "OUTPUT_REFERENCE_INVALID",
    ]
    assert all("path" not in item for item in audit["outputs"])


def test_attempt_output_audit_reports_missing_or_invalid_run_config(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    result_root = tmp_path / "results"
    missing_config_dir = work_root / "attempts" / "missing_config"
    invalid_config_dir = work_root / "attempts" / "invalid_config"
    missing_config_dir.mkdir(parents=True)
    invalid_config_dir.mkdir(parents=True)
    (invalid_config_dir / "run-config.json").write_text("{", encoding="utf-8")

    missing = build_attempt_output_audit(
        run={"runId": "run_1", "resultDir": ""},
        attempts=[_attempt(missing_config_dir)],
        managed_work_dir=work_root,
        managed_results_dir=result_root,
    )
    invalid = build_attempt_output_audit(
        run={"runId": "run_1", "resultDir": ""},
        attempts=[_attempt(invalid_config_dir)],
        managed_work_dir=work_root,
        managed_results_dir=result_root,
    )

    assert missing["reasonCode"] == "RUN_CONFIG_NOT_FOUND"
    assert missing["configAvailable"] is False
    assert invalid["reasonCode"] == "RUN_CONFIG_INVALID"
    assert invalid["configAvailable"] is True


def test_rule_retry_output_audit_verifies_adopted_and_rerun_required_outputs(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_audit"
    attempt_id = "att_rule_audit"
    lease_generation = 1
    work_dir = Path(cfg.work_dir) / "attempts" / attempt_id
    result_dir = Path(cfg.results_dir) / "attempts" / attempt_id / f"generation-{lease_generation}"
    work_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    adopted_path = result_dir / "align.bam"
    adopted_path.write_text("cached bam\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"bam": str(adopted_path), "report": str(result_dir / "report.txt")}}),
        encoding="utf-8",
    )
    candidate = record_candidate_output(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        output_key="bam",
        path=adopted_path,
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE candidate_outputs SET adopted_artifact_id = ? WHERE candidate_output_id = ?",
            ("art_bam", candidate["candidateOutputId"]),
        )
        connection.execute(
            """
            INSERT INTO run_artifact_edges (
                edge_id, run_id, artifact_blob_id, role, port_name, step_id, content_hash, created_at
            ) VALUES (?, ?, ?, 'output', ?, ?, ?, ?)
            """,
            ("edge_bam", run_id, "blob_bam", "bam", "align", candidate["sha256"], "2099-06-07T10:00:00Z"),
        )
        connection.commit()

    audit = build_rule_retry_output_audit(
        cfg=cfg,
        run={"runId": run_id, "resultDir": str(result_dir)},
        attempts=[_attempt(work_dir, attempt_id=attempt_id, lease_generation=lease_generation, state="running")],
        active_lease={"attemptId": attempt_id, "leaseGeneration": lease_generation, "state": "active"},
        output_invalidation_plan=_applied_invalidation_plan(),
        cache_restore_plan=_rule_cache_restore_plan(candidate["sha256"]),
        managed_work_dir=cfg.work_dir,
        managed_results_dir=cfg.results_dir,
    )

    assert audit["schemaVersion"] == "rule-output-audit.v1"
    assert audit["available"] is True
    assert audit["pathExposed"] is False
    assert audit["storageUriExposed"] is False
    assert audit["expectedOutputCount"] == 2
    assert audit["verifiedOutputCount"] == 2
    assert audit["adoptedOutputCount"] == 1
    assert audit["missingOutputCount"] == 1
    assert audit["rerunRequiredOutputCount"] == 1
    assert audit["unverifiedOutputCount"] == 0
    assert [item["state"] for item in audit["outputs"]] == ["adopted", "missing"]
    assert [item["reasonCode"] for item in audit["outputs"]] == [
        "RULE_OUTPUT_ADOPTED_CHECKSUM_VERIFIED",
        "RULE_OUTPUT_RERUN_REQUIRED",
    ]
    serialized = json.dumps(audit, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert '"storageUri":' not in serialized
    assert candidate["sha256"] not in serialized


def test_rule_retry_output_audit_rejects_candidate_path_mismatch(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_rule_output_audit_mismatch"
    attempt_id = "att_rule_audit_mismatch"
    lease_generation = 1
    work_dir = Path(cfg.work_dir) / "attempts" / attempt_id
    result_dir = Path(cfg.results_dir) / "attempts" / attempt_id / f"generation-{lease_generation}"
    work_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    expected_path = result_dir / "align.bam"
    wrong_path = result_dir / "other.bam"
    wrong_path.write_text("wrong\n", encoding="utf-8")
    (work_dir / "run-config.json").write_text(json.dumps({"outputs": {"bam": str(expected_path)}}), encoding="utf-8")
    candidate = record_candidate_output(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        output_key="bam",
        path=wrong_path,
    )

    audit = build_rule_retry_output_audit(
        cfg=cfg,
        run={"runId": run_id, "resultDir": str(result_dir)},
        attempts=[_attempt(work_dir, attempt_id=attempt_id, lease_generation=lease_generation, state="running")],
        active_lease={"attemptId": attempt_id, "leaseGeneration": lease_generation, "state": "active"},
        output_invalidation_plan=_applied_invalidation_plan(),
        cache_restore_plan=_rule_cache_restore_plan(candidate["sha256"], include_report=False),
        managed_work_dir=cfg.work_dir,
        managed_results_dir=cfg.results_dir,
    )

    assert audit["available"] is False
    assert audit["unsafeOutputCount"] == 1
    assert audit["unverifiedOutputCount"] == 1
    assert audit["outputs"][0]["reasonCode"] == "RULE_OUTPUT_AUDIT_CANDIDATE_MISMATCH"
    assert str(tmp_path) not in json.dumps(audit, sort_keys=True)


def test_rule_retry_output_audit_reports_unapplied_invalidation_as_unchecked(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    audit = build_rule_retry_output_audit(
        cfg=cfg,
        run={"runId": "run_rule_output_audit_unapplied", "resultDir": ""},
        attempts=[],
        active_lease=None,
        output_invalidation_plan={
            "schemaVersion": "rule-output-invalidation-plan.v1",
            "previewAvailable": True,
            "outputInvalidationState": {"state": "pending", "appliedOutputEdgeCount": 0},
        },
        cache_restore_plan=_rule_cache_restore_plan("a" * 64),
        managed_work_dir=cfg.work_dir,
        managed_results_dir=cfg.results_dir,
    )

    assert audit["available"] is False
    assert audit["expectedOutputCount"] == 2
    assert audit["uncheckedOutputCount"] == 2
    assert audit["reasonCode"] == "OUTPUT_AUDIT_UNCHECKED_REFERENCES"
    assert {item["reasonCode"] for item in audit["outputs"]} == {"RULE_OUTPUT_AUDIT_INVALIDATION_UNAPPLIED"}


def _attempt(
    work_dir: Path,
    *,
    attempt_id: str = "att_1",
    lease_generation: int = 1,
    state: str = "failed",
) -> dict[str, object]:
    return {
        "attemptId": attempt_id,
        "attemptNumber": 1,
        "leaseGeneration": lease_generation,
        "state": state,
        "updatedAt": "2099-06-07T10:00:00Z",
        "workDir": str(work_dir),
        "workDirPresent": True,
    }


def _applied_invalidation_plan() -> dict[str, object]:
    return {
        "schemaVersion": "rule-output-invalidation-plan.v1",
        "previewAvailable": True,
        "outputInvalidationState": {
            "state": "applied",
            "appliedOutputEdgeCount": 2,
            "appliedLineageEdgeCount": 0,
        },
    }


def _rule_cache_restore_plan(sha256: str, *, include_report: bool = True) -> dict[str, object]:
    rules = [
        {
            "ruleName": "align",
            "stepId": "align",
            "invalidationRole": "selected_failed_rule",
            "outputs": [
                {
                    "outputOrdinal": 1,
                    "artifactKey": "bam",
                    "stepId": "align",
                    "cacheHit": True,
                    "cacheEntry": {"sha256": sha256},
                }
            ],
        }
    ]
    if include_report:
        rules.append(
            {
                "ruleName": "report",
                "stepId": "report",
                "invalidationRole": "downstream_rule",
                "outputs": [
                    {
                        "outputOrdinal": 2,
                        "artifactKey": "report",
                        "stepId": "report",
                        "cacheHit": False,
                        "cacheEntry": None,
                    }
                ],
            }
        )
    return {
        "schemaVersion": "rule-cache-restore-plan.v1",
        "reasonCode": "PER_RULE_CACHE_RESTORE_UNPROVEN",
        "redactionPolicy": {
            "cacheKeysExposed": False,
            "cacheKeyFingerprintsExposed": True,
            "keyPayloadsExposed": False,
            "storageUrisExposed": False,
            "pathsExposed": False,
        },
        "finalOutputPromotionState": {
            "targetCount": 1,
            "adoptedCandidateOutputCount": 1,
        },
        "rules": rules,
    }
