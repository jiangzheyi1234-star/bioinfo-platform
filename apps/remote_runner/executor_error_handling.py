from __future__ import annotations

import subprocess
from pathlib import Path

from .config import RemoteRunnerConfig
from .executor_outcomes import _mark_failed
from .workflow_engine_adapter import WorkflowRuntimeCommandError


def mark_workflow_startup_exception(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    exc: WorkflowRuntimeCommandError | OSError | subprocess.SubprocessError,
    result_dir: Path,
    attempt_id: str | None,
    lease_generation: int | None,
    engine_stage: str | None,
) -> None:
    detail = str(exc).strip()
    lowered = detail.lower()
    message = "Run executor crashed during startup."
    code = "RUN_EXECUTOR_CRASHED"
    if isinstance(exc, WorkflowRuntimeCommandError):
        if "snakemake command not configured" in lowered:
            message = "Snakemake command is not configured."
            code = "WORKFLOW_RUNTIME_MISSING"
        else:
            code = detail.split(":", 1)[0] or "WORKFLOW_RUNTIME_COMMAND_FAILED"
            message = "Run execution options are invalid."
    elif isinstance(exc, FileNotFoundError) or "no such file or directory" in lowered:
        if engine_stage == "dry_run":
            message = "Failed to launch Snakemake dry-run."
            code = "SNAKEMAKE_DRY_RUN_LAUNCH_FAILED"
        elif engine_stage == "run":
            message = "Failed to launch Snakemake execution."
            code = "SNAKEMAKE_EXECUTION_LAUNCH_FAILED"
    _mark_failed(
        cfg,
        run_id=run_id,
        request_id=request_id,
        message=message,
        scope="startup",
        code=code,
        stderr=detail or "Run executor crashed during startup.",
        result_dir=str(result_dir),
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
