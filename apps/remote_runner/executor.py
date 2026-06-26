from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .artifact_input_lineage import record_run_input_artifact_lineage
from .executor_artifacts import _collect_artifacts
from .executor_cache import try_complete_from_artifact_cache
from .executor_inputs import _build_run_outputs, _resolve_run_inputs
from .executor_outcomes import _mark_cancelled, _mark_failed
from .executor_paths import (
    _process_group_recorder,
    _resolve_execution_result_dir,
    _resolve_execution_work_dir,
)
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
from .workflow_engine_adapter import (
    SnakemakeEngineAdapter,
    WorkflowRuntimeCommandError,
    normalize_forcerun_rules,
)

_ORIGINAL_SUBPROCESS_RUN = getattr(subprocess, "run")
RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION = "run-job-execution-options.v1"
SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION = "snakemake-rule-rerun-options.v1"
RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION = "rule-output-adoption-scope.v1"
_PLAN_HASH = re.compile(r"^[a-f0-9]{64}$")
_SAFE_OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

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
        pipeline_id = str(run_spec.get("pipelineId") or "")
        if pipeline_id == GENERATED_TOOL_RUN_PIPELINE_ID:
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

def _patched_subprocess_run_command() -> Callable[..., object] | None:
    current = getattr(subprocess, "run")
    return current if current is not _ORIGINAL_SUBPROCESS_RUN else None


def _snakemake_execution_options(execution_options: dict | None) -> dict[str, Any]:
    if not execution_options:
        return {"forcerun_rules": None, "rerun_incomplete": False, "output_adoption_scope": None}
    if execution_options.get("schemaVersion") != RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("RUN_JOB_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    snakemake = execution_options.get("snakemake")
    if not isinstance(snakemake, dict):
        return {"forcerun_rules": None, "rerun_incomplete": False, "output_adoption_scope": None}
    if snakemake.get("schemaVersion") != SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("SNAKEMAKE_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    raw_rules = snakemake.get("forcerunRules")
    if raw_rules is not None and not isinstance(raw_rules, list):
        raise WorkflowRuntimeCommandError("SNAKEMAKE_FORCERUN_RULES_INVALID")
    forcerun_rules = normalize_forcerun_rules(raw_rules)
    rerun_incomplete = bool(snakemake.get("rerunIncomplete"))
    output_adoption_scope = (
        _rule_output_adoption_scope(execution_options)
        if rerun_incomplete or forcerun_rules
        else None
    )
    return {
        "forcerun_rules": forcerun_rules,
        "rerun_incomplete": rerun_incomplete,
        "output_adoption_scope": output_adoption_scope,
    }


def _rule_output_adoption_scope(execution_options: dict) -> dict[str, Any]:
    scope = execution_options.get("outputAdoptionScope")
    if not isinstance(scope, dict):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    if scope.get("schemaVersion") != RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_SCHEMA_UNSUPPORTED")
    if scope.get("mode") != "rule-partial-rerun":
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_MODE_UNSUPPORTED")
    if scope.get("pathExposed") or scope.get("storageUriExposed"):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REDACTION_UNSAFE")
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    if not _PLAN_HASH.fullmatch(source_plan_hash):
        raise WorkflowRuntimeCommandError("RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED")
    raw_keys = scope.get("outputKeys")
    if not isinstance(raw_keys, list):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_KEYS_INVALID")
    output_keys: list[str] = []
    seen: set[str] = set()
    for raw_key in raw_keys:
        output_key = str(raw_key or "").strip()
        if not _SAFE_OUTPUT_KEY.fullmatch(output_key):
            raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_KEY_UNSAFE")
        if output_key not in seen:
            output_keys.append(output_key)
            seen.add(output_key)
    if not output_keys:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    declared_count = _safe_int(scope.get("outputCount"))
    if declared_count and declared_count != len(output_keys):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_COUNT_MISMATCH")
    return {"output_keys": output_keys}


def _scoped_artifact_collection(
    output_schema: dict | None,
    outputs: dict[str, str] | None,
    *,
    output_adoption_scope: dict[str, Any] | None,
) -> tuple[dict | None, dict[str, str] | None]:
    if output_adoption_scope is None:
        return output_schema, outputs
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict):
        return output_schema, outputs
    output_keys = list(output_adoption_scope.get("output_keys") or [])
    output_key_set = set(output_keys)
    artifacts = output_schema.get("artifacts")
    if not isinstance(artifacts, list):
        return output_schema, outputs
    missing_outputs = [key for key in output_keys if key not in outputs]
    if missing_outputs:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_UNKNOWN_OUTPUT")
    scoped_artifacts = []
    seen_artifact_keys: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_key = str(artifact.get("key") or "").strip()
        if artifact_key in output_key_set:
            scoped_artifacts.append(artifact)
            seen_artifact_keys.add(artifact_key)
    if seen_artifact_keys != output_key_set:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_UNKNOWN_ARTIFACT")
    return {**output_schema, "artifacts": scoped_artifacts}, {
        key: value for key, value in outputs.items() if key in output_key_set
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
