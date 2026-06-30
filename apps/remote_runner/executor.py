from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .artifact_input_lineage import record_run_input_artifact_lineage
from .executor_artifacts import _collect_artifacts
from .executor_cache import try_complete_from_artifact_cache
from .executor_execution_options import (
    _finalize_run_after_artifact_collection, _scoped_artifact_collection,
    _snakemake_execution_options,
    _target_paths_from_output_keys,
)
from .executor_error_handling import mark_workflow_startup_exception
from .executor_inputs import _build_run_outputs, _resolve_run_inputs
from .executor_outcomes import _mark_cancelled, _mark_failed
from .executor_paths import _process_group_recorder, _resolve_execution_result_dir, _resolve_execution_work_dir
from .executor_rule_events import run_snakemake_with_rule_events
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .pipeline import PipelineRegistryError, get_pipeline, validate_run_spec_for_pipeline
from .rule_execution_projection import (
    mark_run_rules_failed,
    mark_run_rules_running,
    mark_run_rules_succeeded,
    seed_run_rules_from_config,
    seed_run_rules_from_graph,
)
from .storage import append_log_lines, update_run_state
from .workflow_resources import build_workflow_resource_config
from .resource_pool import ResourcePool, ResourceRequest, get_default_resource_pool
from .execution_query_storage import fetch_run
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
    attempt_number: int | None = None,
    attempt_work_dir: str | None = None,
    execution_options: dict | None = None,
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
            attempt_number=attempt_number,
            attempt_work_dir=attempt_work_dir,
            execution_options=execution_options,
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
    attempt_number: int | None = None,
    attempt_work_dir: str | None = None,
    execution_options: dict | None = None,
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
    snakemake_event_log = logs_dir / f"{log_stem}.snakemake-events.jsonl"
    engine_stage: str | None = None
    output_schema: dict | None = None
    run_outputs: dict[str, str] | None = None
    try:
        snakemake_execution_options = _snakemake_execution_options(execution_options)
        output_adoption_scope = snakemake_execution_options.pop("output_adoption_scope")
        resume_scope = snakemake_execution_options.pop("resume_scope")
        engine = SnakemakeEngineAdapter(
            cfg,
            run_command=subprocess.run if subprocess.run is not _ORIGINAL_SUBPROCESS_RUN else None,
            should_cancel=should_cancel_attempt,
            on_process_started=_process_group_recorder(
                cfg,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            ),
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        snakemake_event_log.unlink(missing_ok=True)
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
        if resume_scope is not None:
            result_dir = _resolve_run_resume_result_dir(cfg, run_id=run_id)
            config_path = work_dir / "run-config.json"
        result_dir.mkdir(parents=True, exist_ok=True)
        pipeline_id = str(run_spec.get("pipelineId") or "")
        if resume_scope is not None:
            resume_context = _prepare_run_resume_workflow_context(
                cfg,
                run_id=run_id,
                run_spec=run_spec,
                work_dir=work_dir,
                result_dir=result_dir,
                resume_scope=resume_scope,
            )
            snakefile = resume_context["snakefile"]
            config_path = resume_context["configPath"]
            output_schema = resume_context["outputSchema"]
            run_outputs = resume_context["outputs"]
            if pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
                seed_run_rules_from_config(
                    cfg,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    lease_generation=lease_generation,
                    attempt_number=attempt_number,
                    config_path=config_path,
                )
            else:
                seed_run_rules_from_graph(
                    cfg,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    lease_generation=lease_generation,
                    attempt_number=attempt_number,
                    graph=dict(resume_context.get("graph") or {}),
                )
        elif pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
            resolved_inputs = _resolve_run_inputs(cfg, run_spec, input_work_dir=work_dir / "inputs")
            record_run_input_artifact_lineage(cfg, run_id=run_id, resolved_inputs=resolved_inputs, attempt_id=attempt_id)
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
            seed_run_rules_from_config(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                config_path=config_path,
            )
        else:
            pipeline = get_pipeline(cfg, pipeline_id)
            validate_run_spec_for_pipeline(pipeline, run_spec)
            resolved_inputs = _resolve_run_inputs(cfg, run_spec, input_work_dir=work_dir / "inputs")
            record_run_input_artifact_lineage(cfg, run_id=run_id, resolved_inputs=resolved_inputs, attempt_id=attempt_id)
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
            seed_run_rules_from_graph(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                graph=dict(pipeline.ui_schema.get("graph") or {}),
            )
        snakemake_execution_options["target_paths"] = _target_paths_from_output_keys(
            run_outputs,
            output_adoption_scope=output_adoption_scope,
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
            **snakemake_execution_options,
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
            mark_run_rules_failed(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                stderr=dry_run.stderr,
            )
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

        cache_adoption = try_complete_from_artifact_cache(
            cfg,
            run_id=run_id,
            request_id=request_id,
            run_spec=run_spec,
            execution_options=execution_options,
            output_schema=output_schema,
            run_outputs=run_outputs,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            result_dir=str(result_dir),
        )
        if cache_adoption["adopted"]:
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
        mark_run_rules_running(
            cfg,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
        )
        engine_stage = "run"
        run_result, rule_event_projection = run_snakemake_with_rule_events(
            cfg,
            engine,
            snakefile=snakefile,
            work_dir=work_dir,
            config_path=config_path,
            event_log_path=snakemake_event_log,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            **snakemake_execution_options,
        )
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
            if not rule_event_projection["projected"]:
                mark_run_rules_failed(
                    cfg,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    lease_generation=lease_generation,
                    attempt_number=attempt_number,
                    stderr=run_result.stderr,
                )
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

        if not rule_event_projection["projected"]:
            mark_run_rules_succeeded(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
            )
        artifact_output_schema, artifact_outputs = _scoped_artifact_collection(
            output_schema,
            run_outputs,
            output_adoption_scope=output_adoption_scope,
        )
        _collect_artifacts(
            cfg,
            run_id,
            output_schema=artifact_output_schema,
            outputs=artifact_outputs,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            request_id=request_id,
            result_dir=str(result_dir),
            finalize_run=_finalize_run_after_artifact_collection(
                attempt_id=attempt_id,
                output_adoption_scope=output_adoption_scope,
            ),
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
        mark_workflow_startup_exception(
            cfg,
            run_id=run_id,
            request_id=request_id,
            exc=exc,
            result_dir=result_dir,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            engine_stage=engine_stage,
        )


def _prepare_run_resume_workflow_context(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    run_spec: dict,
    work_dir: Path,
    result_dir: Path,
    resume_scope: dict,
) -> dict[str, Any]:
    config_path = work_dir / "run-config.json"
    if not config_path.is_file():
        raise WorkflowRuntimeCommandError("RUN_RESUME_RUN_CONFIG_NOT_FOUND")
    config = _read_run_resume_config(config_path)
    outputs = _run_resume_outputs(config, result_dir=result_dir, resume_scope=resume_scope)
    pipeline_id = str(run_spec.get("pipelineId") or "")
    if pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
        snakefile = work_dir / "workflow" / "Snakefile"
        output_schema = _generated_run_resume_output_schema(config, outputs)
        graph = {}
    else:
        pipeline = get_pipeline(cfg, pipeline_id)
        validate_run_spec_for_pipeline(pipeline, run_spec)
        snakefile = pipeline.snakefile
        output_schema = pipeline.output_schema
        graph = dict(pipeline.ui_schema.get("graph") or {})
    if not snakefile.is_file():
        raise WorkflowRuntimeCommandError("RUN_RESUME_SNAKEFILE_NOT_FOUND")
    return {
        "snakefile": snakefile,
        "configPath": config_path,
        "outputs": outputs,
        "outputSchema": output_schema,
        "graph": graph,
    }


def _read_run_resume_config(config_path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RUN_CONFIG_INVALID") from exc
    if not isinstance(parsed, dict):
        raise WorkflowRuntimeCommandError("RUN_RESUME_RUN_CONFIG_INVALID")
    return parsed


def _run_resume_outputs(
    config: dict[str, Any],
    *,
    result_dir: Path,
    resume_scope: dict,
) -> dict[str, str]:
    raw_outputs = config.get("outputs")
    if not isinstance(raw_outputs, dict) or not raw_outputs:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RUN_CONFIG_OUTPUTS_MISSING")
    required_keys = {str(key) for key in resume_scope.get("outputKeys") or []}
    outputs: dict[str, str] = {}
    result_root = result_dir.resolve(strict=False)
    for key, raw_path in raw_outputs.items():
        output_key = str(key or "").strip()
        output_path = str(raw_path or "").strip()
        if not output_key or not output_path:
            raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_REFERENCE_INVALID")
        path = Path(output_path)
        if not path.is_absolute():
            path = result_dir / path
        resolved = path.resolve(strict=False)
        if not _is_relative_to(resolved, result_root):
            raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_PATH_OUTSIDE_RESULT_DIR")
        outputs[output_key] = str(resolved)
    missing_keys = required_keys - set(outputs)
    if missing_keys:
        raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_SCOPE_UNKNOWN")
    return outputs


def _generated_run_resume_output_schema(config: dict[str, Any], outputs: dict[str, str]) -> dict[str, Any]:
    workflow = config.get("workflow") if isinstance(config.get("workflow"), dict) else {}
    workflow_outputs = workflow.get("outputs") if isinstance(workflow.get("outputs"), dict) else {}
    artifacts: list[dict[str, Any]] = []
    for key, output_path in outputs.items():
        spec = workflow_outputs.get(key) if isinstance(workflow_outputs.get(key), dict) else {}
        artifact = {
            "key": key,
            "name": Path(output_path).name,
            "kind": str(spec.get("kind") or "file"),
            "mimeType": str(spec.get("mimeType") or "application/octet-stream"),
        }
        for flag in ("temp", "protected", "directory"):
            if spec.get(flag) is True:
                artifact[flag] = True
        artifacts.append(artifact)
    if not artifacts:
        raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_ARTIFACTS_REQUIRED")
    return {"type": "object", "artifacts": artifacts}


def _resolve_run_resume_result_dir(cfg: RemoteRunnerConfig, *, run_id: str) -> Path:
    run = fetch_run(cfg, run_id)
    if run is None:
        raise WorkflowRuntimeCommandError("RUN_NOT_FOUND")
    raw_result_dir = str(run.get("resultDir") or "").strip()
    if not raw_result_dir:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RESULT_DIR_REQUIRED")
    result_dir = Path(raw_result_dir)
    if not result_dir.is_absolute():
        result_dir = Path(cfg.results_dir) / result_dir
    resolved = result_dir.resolve(strict=False)
    if not _is_relative_to(resolved, Path(cfg.results_dir).resolve(strict=False)):
        raise WorkflowRuntimeCommandError("RUN_RESUME_RESULT_DIR_OUTSIDE_MANAGED_ROOT")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
