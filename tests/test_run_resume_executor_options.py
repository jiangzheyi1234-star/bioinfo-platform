from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from apps.remote_runner.agent_run_launch_gate import (
    AgentRunLaunchAuthorization,
    AgentRunLaunchGateError,
)
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.executor import _execute_snakemake_workflow
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

    with pytest.raises(
        WorkflowRuntimeCommandError, match="RUN_RESUME_FORCERUN_RULES_FORBIDDEN"
    ):
        _snakemake_execution_options(options)


def test_executor_rejects_run_resume_options_with_unsafe_flags() -> None:
    options = _run_resume_options()
    options["snakemake"]["argsPreview"] = ["--rerun-incomplete", "--forceall"]

    with pytest.raises(
        WorkflowRuntimeCommandError, match="RUN_RESUME_UNSAFE_FLAG_FORBIDDEN"
    ):
        _snakemake_execution_options(options)


def test_executor_rejects_run_resume_options_without_redacted_scope() -> None:
    options = _run_resume_options()
    options["resumeScope"]["pathExposed"] = True

    with pytest.raises(
        WorkflowRuntimeCommandError, match="RUN_RESUME_EXECUTION_SCOPE_REDACTION_UNSAFE"
    ):
        _snakemake_execution_options(options)


def test_artifact_cache_adoption_skips_run_resume_execution_options(
    tmp_path: Path, monkeypatch
) -> None:
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
        raise AssertionError(
            "whole-run cache adoption must not run for run-resume execution options"
        )

    monkeypatch.setattr(
        "apps.remote_runner.executor_cache.try_adopt_cached_outputs", fail_adoption
    )
    monkeypatch.setattr(
        "apps.remote_runner.executor_cache.update_run_state", fail_adoption
    )

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

    assert result == {
        "adopted": False,
        "reason": "run_resume_cache_adoption_unavailable",
    }


def test_agent_run_resume_fails_closed_without_immutable_workspace_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    payload = b"@read\nACGT\n+\n!!!!\n"
    private_path = (
        Path(cfg.work_dir)
        / "agent-inputs"
        / "run-key"
        / "receipt-key"
        / "001-reads.fastq"
    )
    private_path.parent.mkdir(parents=True)
    private_path.write_bytes(payload)
    private_path.chmod(0o400)
    run_spec = {
        "pipelineId": "generated-tool-run-v1",
        "inputs": [
            {
                "uploadId": "upl_agent_resume",
                "filename": "reads.fastq",
                "role": "reads",
            }
        ],
    }
    verified_input = {
        "sourceType": "upload",
        "sourceId": "upl_agent_resume",
        "uploadId": "upl_agent_resume",
        "name": "",
        "filename": "reads.fastq",
        "role": "reads",
        "path": str(private_path),
        "sizeBytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mimeType": "application/fastq",
        "index": 0,
        "agentInputSnapshot": True,
    }
    authorization = AgentRunLaunchAuthorization(
        authorization_id="auth_agent_resume",
        run_spec=run_spec,
        runtime_lock_hash="a" * 64,
        runtime_proof_hash="b" * 64,
        verified_inputs=(verified_input,),
        input_materialization_event_proof={
            "eventId": "evt_agent_resume",
            "sequence": 1,
            "stateVersion": 1,
            "eventHash": "c" * 64,
            "prevEventHash": None,
            "createdAt": "2099-01-01T00:00:00Z",
        },
    )
    process_started = False

    def fail_if_process_started(*_args, **_kwargs):
        nonlocal process_started
        process_started = True
        raise AssertionError("Agent resume must not start without workspace proof")

    monkeypatch.setattr(subprocess, "Popen", fail_if_process_started)

    with pytest.raises(
        AgentRunLaunchGateError,
        match="AGENT_RUN_LAUNCH_GATE_FAILED: resume_workspace",
    ):
        _execute_snakemake_workflow(
            cfg,
            run_id="run_agent_resume",
            request_id="req_agent_resume",
            run_spec=run_spec,
            execution_options=_run_resume_options(),
            agent_launch_authorization=authorization,
            verified_inputs=[verified_input],
        )
    assert process_started is False


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
