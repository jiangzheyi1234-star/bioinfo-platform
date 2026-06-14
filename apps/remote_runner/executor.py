from __future__ import annotations

import time
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import RemoteRunnerConfig
from .executor_artifacts import _collect_artifacts
from .executor_inputs import _build_run_outputs, _resolve_run_inputs
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .pipeline import PipelineRegistryError, get_pipeline, validate_run_spec_for_pipeline
from .run_execution_storage import record_run_attempt_process_group
from .workflow_resources import build_workflow_resource_config
from .storage import (
    append_log_lines,
    update_run_state,
)
from .resource_pool import ResourcePool, ResourceRequest, get_default_resource_pool
from .workflow_engine_adapter import (
    SnakemakeEngineAdapter,
    WorkflowRuntimeCommandError,
)


_ORIGINAL_SUBPROCESS_RUN = getattr(subprocess, "run")


def run_snakemake_execution(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict,
    attempt_id: str | None = None,
    lease_generation: int | None = None,
    attempt_work_dir: str | None = None,
    should_cancel_attempt: Callable[[], bool] | None = None,
    resource_pool: ResourcePool | None = None,
    resource_request: ResourceRequest | None = None,
) -> None:
    pool = resource_pool or get_default_resource_pool()
    task_id = attempt_id or run_id
    request = resource_request or ResourceRequest()
    pool.acquire(task_id, request)
    try:
        _execute_snakemake_workflow(
            cfg,
            run_id=run_id,
            request_id=request_id,
            run_spec=run_spec,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_work_dir=attempt_work_dir,
            should_cancel_attempt=should_cancel_attempt,
        )
    finally:
        pool.release(task_id)


def _execute_snakemake_workflow(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict,
    attempt_id: str | None = None,
    lease_generation: int | None = None,
    attempt_work_dir: str | None = None,
    should_cancel_attempt: Callable[[], bool] | None = None,
) -> None:
    result_dir = _resolve_execution_result_dir(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    work_dir = _resolve_execution_work_dir(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_work_dir=attempt_work_dir,
    )
    logs_dir = Path(cfg.logs_dir)
    config_path = work_dir / "run-config.json"
    log_stem = f"{run_id}.{attempt_id}" if attempt_id else run_id
    stdout_log = logs_dir / f"{log_stem}.stdout.log"
    stderr_log = logs_dir / f"{log_stem}.stderr.log"
    engine_stage: str | None = None
    output_schema: dict | None = None
    run_outputs: dict[str, str] | None = None
    try:
        engine = SnakemakeEngineAdapter(
            cfg,
            run_command=_patched_subprocess_run_command(),
            should_cancel=should_cancel_attempt,
            on_process_started=_process_group_recorder(
                cfg,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            ),
        )
        result_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        update_run_state(
            cfg,
            run_id=run_id,
            status="running",
            stage="validate",
            message="Validating pipeline and run inputs.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        pipeline_id = str(run_spec.get("pipelineId") or "")
        if pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
            resolved_inputs = _resolve_run_inputs(cfg, run_spec)
            generated = prepare_generated_tool_workflow(
                cfg,
                run_id=run_id,
                request_id=request_id,
                run_spec=run_spec,
                resolved_inputs=resolved_inputs,
                work_dir=work_dir,
                result_dir=result_dir,
                require_workflow_ready=True,
            )
            snakefile = generated.snakefile
            config_path = generated.config_path
            output_schema = generated.output_schema
            run_outputs = generated.outputs
        else:
            pipeline = get_pipeline(cfg, pipeline_id)
            validate_run_spec_for_pipeline(pipeline, run_spec)
            resolved_inputs = _resolve_run_inputs(cfg, run_spec)
            workflow_resource_config = build_workflow_resource_config(
                cfg,
                workflow_resource_spec=pipeline.resource_schema,
                bindings=dict(run_spec.get("resourceBindings") or {}),
            )
            snakefile = pipeline.snakefile
            run_outputs = _build_run_outputs(pipeline.execution, result_dir)
            output_schema = pipeline.output_schema
            config_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "request_id": request_id,
                        "project_id": str(run_spec.get("projectId") or "proj_default"),
                        "pipeline_id": pipeline.pipeline_id,
                        "pipeline_version": pipeline.version,
                        "params": dict(run_spec.get("params") or {}),
                        "databases": workflow_resource_config["config"],
                        "resources": workflow_resource_config["resources"],
                        "resourceConfig": workflow_resource_config["config"],
                        "inputs": resolved_inputs,
                        "outputs": run_outputs,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        update_run_state(
            cfg,
            run_id=run_id,
            status="running",
            stage="validate",
            message="Validating Snakemake workflow.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        engine_stage = "dry_run"
        dry_run = engine.dry_run(
            snakefile=snakefile,
            work_dir=work_dir,
            config_path=config_path,
        )
        append_log_lines(cfg, run_id, "stdout", [line for line in dry_run.stdout.splitlines() if line])
        append_log_lines(cfg, run_id, "stderr", [line for line in dry_run.stderr.splitlines() if line])
        if dry_run.returncode != 0:
            if should_cancel_attempt is not None and should_cancel_attempt():
                _mark_cancelled(
                    cfg,
                    run_id=run_id,
                    request_id=request_id,
                    stderr=dry_run.stderr,
                    result_dir=str(result_dir),
                    attempt_id=attempt_id,
                    lease_generation=lease_generation,
                )
                return
            _mark_failed(
                cfg,
                run_id=run_id,
                request_id=request_id,
                message="Snakemake dry-run failed.",
                scope="validate",
                stderr=dry_run.stderr,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            )
            return

        update_run_state(
            cfg,
            run_id=run_id,
            status="running",
            stage="snakemake",
            message="Executing Snakemake workflow.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        engine_stage = "run"
        run_result = engine.run(
            snakefile=snakefile,
            work_dir=work_dir,
            config_path=config_path,
        )
        stdout_log.write_text(run_result.stdout or "", encoding="utf-8")
        stderr_log.write_text(run_result.stderr or "", encoding="utf-8")
        append_log_lines(cfg, run_id, "stdout", [line for line in run_result.stdout.splitlines() if line])
        append_log_lines(cfg, run_id, "stderr", [line for line in run_result.stderr.splitlines() if line])
        if run_result.returncode != 0:
            if should_cancel_attempt is not None and should_cancel_attempt():
                _mark_cancelled(
                    cfg,
                    run_id=run_id,
                    request_id=request_id,
                    stderr=run_result.stderr,
                    result_dir=str(result_dir),
                    attempt_id=attempt_id,
                    lease_generation=lease_generation,
                )
                return
            _mark_failed(
                cfg,
                run_id=run_id,
                request_id=request_id,
                message="Snakemake execution failed.",
                scope="workflow",
                stderr=run_result.stderr,
                result_dir=str(result_dir),
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            )
            return

        _collect_artifacts(
            cfg,
            run_id,
            output_schema=output_schema,
            outputs=run_outputs,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            request_id=request_id,
            result_dir=str(result_dir),
            finalize_run=attempt_id is not None,
        )
        if attempt_id is None:
            update_run_state(
                cfg,
                run_id=run_id,
                status="completed",
                stage="finalize",
                message="Snakemake execution completed.",
                request_id=request_id,
                result_dir=str(result_dir),
            )
    except (PipelineRegistryError, ValueError) as exc:
        _mark_failed(
            cfg,
            run_id=run_id,
            request_id=request_id,
            message="Run validation failed.",
            scope="validate",
            code=str(exc) or "RUN_VALIDATION_FAILED",
            stderr=str(exc) or "Run validation failed.",
            result_dir=str(result_dir),
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
    except (WorkflowRuntimeCommandError, OSError, subprocess.SubprocessError) as exc:
        detail = str(exc).strip()
        lowered = detail.lower()
        message = "Run executor crashed during startup."
        code = "RUN_EXECUTOR_CRASHED"
        if isinstance(exc, WorkflowRuntimeCommandError):
            message = "Snakemake command is not configured."
            code = "WORKFLOW_RUNTIME_MISSING"
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


def _patched_subprocess_run_command() -> Callable[..., object] | None:
    current = getattr(subprocess, "run")
    return current if current is not _ORIGINAL_SUBPROCESS_RUN else None


def _process_group_recorder(
    cfg: RemoteRunnerConfig,
    *,
    attempt_id: str | None,
    lease_generation: int | None,
) -> Callable[[int], None] | None:
    if not str(attempt_id or "").strip() or lease_generation is None:
        return None

    def record(process_group_id: int) -> None:
        record_run_attempt_process_group(
            cfg,
            str(attempt_id),
            lease_generation=int(lease_generation),
            process_group_id=str(process_group_id),
        )

    return record


def _resolve_execution_work_dir(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_work_dir: str | None,
) -> Path:
    has_attempt_context = any(
        value is not None and str(value).strip()
        for value in (attempt_id, lease_generation, attempt_work_dir)
    )
    if not has_attempt_context:
        return Path(cfg.work_dir) / run_id
    if not str(attempt_id or "").strip():
        raise ValueError("RUN_ATTEMPT_ID_REQUIRED")
    if lease_generation is None:
        raise ValueError("RUN_LEASE_GENERATION_REQUIRED")
    normalized_work_dir = str(attempt_work_dir or "").strip()
    if not normalized_work_dir:
        raise ValueError("RUN_ATTEMPT_WORK_DIR_REQUIRED")
    return Path(normalized_work_dir)


def _resolve_execution_result_dir(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
) -> Path:
    if attempt_id is None and lease_generation is None:
        return Path(cfg.results_dir) / run_id
    if not str(attempt_id or "").strip():
        raise ValueError("RUN_ATTEMPT_ID_REQUIRED")
    if lease_generation is None:
        raise ValueError("RUN_LEASE_GENERATION_REQUIRED")
    return Path(cfg.results_dir) / "attempts" / str(attempt_id) / f"generation-{int(lease_generation)}"


def _mark_failed(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    message: str,
    scope: str,
    stderr: str,
    code: str | None = None,
    result_dir: str = "",
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> None:
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage=scope,
        message=message,
        request_id=request_id,
        result_dir=result_dir,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        last_error={
            "code": code or ("WORKFLOW_RUNTIME_MISSING" if scope == "validate" else "WORKFLOW_EXECUTION_FAILED"),
            "message": stderr.strip() or message,
            "requestId": request_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": scope,
            "stage": scope,
        },
    )


def _mark_cancelled(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    stderr: str,
    result_dir: str = "",
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> None:
    update_run_state(
        cfg,
        run_id=run_id,
        status="canceled",
        stage="cancel",
        message="Run execution cancelled.",
        request_id=request_id,
        result_dir=result_dir,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        last_error={
            "code": "RUN_CANCELLED",
            "message": stderr.strip() or "Run execution cancelled.",
            "requestId": request_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": "workflow",
            "stage": "cancel",
        },
    )
