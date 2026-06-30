from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.executor_cache import try_complete_from_artifact_cache
from apps.remote_runner.executor_execution_options import _snakemake_execution_options
from apps.remote_runner.workflow_engine_adapter import WorkflowRuntimeCommandError


def test_executor_accepts_strict_run_resume_options_without_forcerun() -> None:
    parsed = _snakemake_execution_options(_run_resume_options())

    assert parsed == {
        "forcerun_rules": [],
        "rerun_incomplete": True,
        "output_adoption_scope": None,
        "resume_scope": parsed["resume_scope"],
    }
    assert parsed["resume_scope"]["schemaVersion"] == "run-resume-execution-scope.v1"
    assert parsed["resume_scope"]["mode"] == "run-resume"


def test_executor_rejects_run_resume_options_with_forcerun_rules() -> None:
    options = _run_resume_options()
    options["snakemake"]["forcerunRules"] = ["align"]

    with pytest.raises(WorkflowRuntimeCommandError, match="RUN_RESUME_FORCERUN_RULES_FORBIDDEN"):
        _snakemake_execution_options(options)


def test_executor_rejects_run_resume_options_with_unsafe_flags() -> None:
    options = _run_resume_options()
    options["snakemake"]["argsPreview"] = ["--rerun-incomplete", "--forceall"]

    with pytest.raises(WorkflowRuntimeCommandError, match="RUN_RESUME_UNSAFE_FLAG_FORBIDDEN"):
        _snakemake_execution_options(options)


def test_executor_rejects_run_resume_options_without_redacted_scope() -> None:
    options = _run_resume_options()
    options["resumeScope"]["pathExposed"] = True

    with pytest.raises(WorkflowRuntimeCommandError, match="RUN_RESUME_EXECUTION_SCOPE_REDACTION_UNSAFE"):
        _snakemake_execution_options(options)


def test_artifact_cache_adoption_skips_run_resume_execution_options(tmp_path: Path, monkeypatch) -> None:
    cfg = RemoteRunnerConfig(
        token="phase3-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
    )

    def fail_adoption(*_args, **_kwargs):
        raise AssertionError("whole-run cache adoption must not run for run-resume execution options")

    monkeypatch.setattr("apps.remote_runner.executor_cache.try_adopt_cached_outputs", fail_adoption)
    monkeypatch.setattr("apps.remote_runner.executor_cache.update_run_state", fail_adoption)

    result = try_complete_from_artifact_cache(
        cfg,
        run_id="run_resume_cache_guard",
        request_id="req_resume_cache_guard",
        run_spec={"workflowRevisionId": "wfrev_resume"},
        execution_options=_run_resume_options(),
        output_schema={},
        run_outputs={},
        attempt_id="att_resume",
        lease_generation=1,
        attempt_number=1,
        result_dir=str(tmp_path / "results"),
    )

    assert result == {"adopted": False, "reason": "run_resume_cache_adoption_unavailable"}


def _run_resume_options() -> dict:
    return {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-run-resume-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": [],
            "argsPreview": ["--rerun-incomplete"],
            "unsafeFlagsProhibited": ["--forceall", "--touch", "--ignore-incomplete"],
        },
        "resumeScope": {
            "schemaVersion": "run-resume-execution-scope.v1",
            "mode": "run-resume",
            "sourcePlanHash": "a" * 64,
            "sourceAttempt": {
                "attemptId": "att_source",
                "attemptNumber": 1,
                "leaseGeneration": 1,
                "state": "failed",
            },
            "workdirReusePolicy": {
                "schemaVersion": "run-workdir-reuse-policy.v1",
                "workDirReusable": True,
                "managedRoot": True,
                "directoryPresent": True,
                "runConfigPresent": True,
                "pathExposed": False,
            },
            "outputCount": 2,
            "outputKeys": ["present", "missing"],
            "expectedOutputCount": 2,
            "verifiedOutputCount": 2,
            "checksumVerifiedOutputCount": 1,
            "rerunRequiredOutputCount": 1,
            "unsafeOutputCount": 0,
            "unverifiedOutputCount": 0,
            "finalizeRunOnAdoption": True,
            "postExecutionAdoptionRequired": True,
            "cacheAdoptionAllowed": False,
            "pathExposed": False,
            "storageUriExposed": False,
            "checksumValueExposed": False,
        },
    }
