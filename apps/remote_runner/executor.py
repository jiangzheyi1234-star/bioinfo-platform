from __future__ import annotations

import time
import json
import subprocess
import threading
from pathlib import Path

from .config import RemoteRunnerConfig, build_workflow_runtime_environment, get_workflow_profile_dir
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .pipeline import PipelineRegistryError, get_pipeline, validate_run_spec_for_pipeline
from .workflow_resources import build_workflow_resource_config
from .storage import (
    append_log_lines,
    fetch_upload,
    persist_artifact,
    update_run_state,
)


_EXECUTION_LOCK = threading.Lock()


def _snakemake_command(cfg: RemoteRunnerConfig) -> list[str]:
    snakemake_command = str(cfg.snakemake_command or "").strip()
    if not snakemake_command:
        raise RuntimeError("snakemake command not configured")
    return [snakemake_command]


def _snakemake_environment(cfg: RemoteRunnerConfig) -> dict[str, str]:
    return build_workflow_runtime_environment(cfg)


def _snakemake_profile_args(cfg: RemoteRunnerConfig) -> list[str]:
    workflow_profile_dir = get_workflow_profile_dir(cfg)
    if workflow_profile_dir is None:
        return []
    return ["--workflow-profile", str(workflow_profile_dir)]


def _snakemake_execution_args(
    cfg: RemoteRunnerConfig,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
) -> list[str]:
    profile_args = _snakemake_profile_args(cfg)
    command = [
        *_snakemake_command(cfg),
        "--snakefile",
        str(snakefile),
        "--directory",
        str(work_dir),
    ]
    if profile_args:
        command.extend(profile_args)
    else:
        command.extend(["--cores", "1", "--use-conda"])
    command.extend(["--configfile", str(config_path)])
    return command


def start_run_execution(cfg: RemoteRunnerConfig, *, run_id: str, request_id: str, run_spec: dict) -> None:
    thread = threading.Thread(
        target=run_snakemake_execution,
        kwargs={
            "cfg": cfg,
            "run_id": run_id,
            "request_id": request_id,
            "run_spec": run_spec,
        },
        daemon=True,
    )
    try:
        thread.start()
    except Exception as exc:
        _mark_failed(
            cfg,
            run_id=run_id,
            request_id=request_id,
            message="Failed to start run executor.",
            scope="startup",
            code="RUN_EXECUTOR_START_FAILED",
            stderr=str(exc) or "Failed to start run executor.",
        )


def run_snakemake_execution(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict,
) -> None:
    with _EXECUTION_LOCK:
        result_dir = Path(cfg.results_dir) / run_id
        work_dir = Path(cfg.work_dir) / run_id
        logs_dir = Path(cfg.logs_dir)
        config_path = work_dir / "run-config.json"
        stdout_log = logs_dir / f"{run_id}.stdout.log"
        stderr_log = logs_dir / f"{run_id}.stderr.log"
        dry_run_cmd: list[str] | None = None
        run_cmd: list[str] | None = None
        output_schema: dict | None = None
        run_outputs: dict[str, str] | None = None
        try:
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
            )
            dry_run_cmd = [*_snakemake_execution_args(cfg, snakefile=snakefile, work_dir=work_dir, config_path=config_path), "-n"]

            dry_run = subprocess.run(
                dry_run_cmd,
                capture_output=True,
                text=True,
                env=_snakemake_environment(cfg),
            )
            append_log_lines(cfg, run_id, "stdout", [line for line in dry_run.stdout.splitlines() if line])
            append_log_lines(cfg, run_id, "stderr", [line for line in dry_run.stderr.splitlines() if line])
            if dry_run.returncode != 0:
                _mark_failed(
                    cfg,
                    run_id=run_id,
                    request_id=request_id,
                    message="Snakemake dry-run failed.",
                    scope="validate",
                    stderr=dry_run.stderr,
                )
                return

            update_run_state(
                cfg,
                run_id=run_id,
                status="running",
                stage="snakemake",
                message="Executing Snakemake workflow.",
                request_id=request_id,
            )
            run_cmd = _snakemake_execution_args(cfg, snakefile=snakefile, work_dir=work_dir, config_path=config_path)
            run_result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                env=_snakemake_environment(cfg),
            )
            stdout_log.write_text(run_result.stdout or "", encoding="utf-8")
            stderr_log.write_text(run_result.stderr or "", encoding="utf-8")
            append_log_lines(cfg, run_id, "stdout", [line for line in run_result.stdout.splitlines() if line])
            append_log_lines(cfg, run_id, "stderr", [line for line in run_result.stderr.splitlines() if line])
            if run_result.returncode != 0:
                _mark_failed(
                    cfg,
                    run_id=run_id,
                    request_id=request_id,
                    message="Snakemake execution failed.",
                    scope="workflow",
                    stderr=run_result.stderr,
                    result_dir=str(result_dir),
                )
                return

            _collect_artifacts(cfg, run_id, output_schema=output_schema, outputs=run_outputs)
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
            )
        except Exception as exc:
            detail = str(exc).strip()
            lowered = detail.lower()
            message = "Run executor crashed during startup."
            code = "RUN_EXECUTOR_CRASHED"
            if "snakemake command not configured" in lowered:
                message = "Snakemake command is not configured."
                code = "WORKFLOW_RUNTIME_MISSING"
            elif isinstance(exc, FileNotFoundError) or "no such file or directory" in lowered:
                if dry_run_cmd is not None and run_cmd is None:
                    message = "Failed to launch Snakemake dry-run."
                    code = "SNAKEMAKE_DRY_RUN_LAUNCH_FAILED"
                elif run_cmd is not None:
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
            )


def _collect_artifacts(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    output_schema: dict | None,
    outputs: dict[str, str] | None,
) -> list[dict]:
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict) or not outputs:
        raise ValueError("MANIFEST_OUTPUTS_REQUIRED")
    raw_artifacts = output_schema.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ValueError("OUTPUT_ARTIFACTS_REQUIRED")
    artifacts = []
    for artifact in raw_artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("OUTPUT_ARTIFACT_INVALID")
        key = str(artifact.get("key") or "").strip()
        if key not in outputs:
            raise ValueError(f"OUTPUT_ARTIFACT_KEY_UNKNOWN: {key}")
        path = Path(outputs[key])
        kind = str(artifact.get("kind") or "").strip()
        mime_type = str(artifact.get("mimeType") or "").strip()
        if not kind or not mime_type:
            raise ValueError(f"OUTPUT_ARTIFACT_METADATA_REQUIRED: {key}")
        directory = bool(artifact.get("directory")) or kind == "directory" or mime_type == "inode/directory"
        if not path.exists() or (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError(f"OUTPUT_ARTIFACT_MISSING: {key}")
        artifacts.append(persist_artifact(cfg, run_id=run_id, kind=kind, path=path, mime_type=mime_type))
    return artifacts


def _build_run_outputs(execution: dict, result_dir: Path) -> dict[str, str]:
    configured = execution.get("outputs") if isinstance(execution, dict) else None
    if not isinstance(configured, dict) or not configured:
        raise ValueError("EXECUTION_OUTPUTS_REQUIRED")
    outputs: dict[str, str] = {}
    for key, value in configured.items():
        name = str(key or "").strip()
        relative = str(value or "").strip()
        if not name or not relative:
            continue
        candidate = (result_dir / relative).resolve()
        if result_dir.resolve() not in [candidate, *candidate.parents]:
            raise ValueError("OUTPUT_PATH_OUTSIDE_RESULT_DIR")
        outputs[name] = str(candidate)
    if not outputs:
        raise ValueError("OUTPUTS_REQUIRED")
    return outputs


def _resolve_run_inputs(cfg: RemoteRunnerConfig, run_spec: dict) -> list[dict]:
    raw_inputs = run_spec.get("inputs") or []
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("INPUT_REQUIRED")
    resolved: list[dict] = []
    for index, item in enumerate(raw_inputs):
        if not isinstance(item, dict):
            raise ValueError("INPUT_INVALID")
        upload_id = str(item.get("uploadId") or "").strip()
        if not upload_id:
            raise ValueError("INPUT_UPLOAD_ID_REQUIRED")
        upload = fetch_upload(cfg, upload_id)
        if upload is None:
            raise ValueError("INPUT_NOT_FOUND")
        path = Path(str(upload["path"]))
        if not path.exists():
            raise ValueError("INPUT_FILE_MISSING")
        resolved.append(
            {
                "uploadId": upload["uploadId"],
                "filename": str(item.get("filename") or upload["filename"]),
                "role": str(item.get("role") or "input"),
                "path": str(path),
                "sizeBytes": upload["sizeBytes"],
                "sha256": upload["sha256"],
                "mimeType": upload["mimeType"],
                "index": index,
            }
        )
    return resolved


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
) -> None:
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage=scope,
        message=message,
        request_id=request_id,
        result_dir=result_dir,
        last_error={
            "code": code or ("WORKFLOW_RUNTIME_MISSING" if scope == "validate" else "WORKFLOW_EXECUTION_FAILED"),
            "message": stderr.strip() or message,
            "requestId": request_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": scope,
            "stage": scope,
        },
    )
