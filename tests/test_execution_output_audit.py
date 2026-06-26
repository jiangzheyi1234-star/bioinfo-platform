from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.execution_output_audit import build_attempt_output_audit


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


def _attempt(work_dir: Path) -> dict[str, object]:
    return {
        "attemptId": "att_1",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "state": "failed",
        "updatedAt": "2099-06-07T10:00:00Z",
        "workDir": str(work_dir),
        "workDirPresent": True,
    }
