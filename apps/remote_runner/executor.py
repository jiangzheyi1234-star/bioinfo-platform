from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
import time

from .config import RemoteRunnerConfig, build_workflow_runtime_environment
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .pipeline import PipelineRegistryError, get_pipeline, validate_run_spec_for_pipeline
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
    thread.start()


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
        try:
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
            else:
                pipeline = get_pipeline(cfg, pipeline_id)
                validate_run_spec_for_pipeline(pipeline, run_spec)
                resolved_inputs = _resolve_run_inputs(cfg, run_spec)
                snakefile = pipeline.snakefile
                config_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "request_id": request_id,
                            "project_id": str(run_spec.get("projectId") or "proj_default"),
                            "pipeline_id": pipeline.pipeline_id,
                            "pipeline_version": pipeline.version,
                            "params": dict(run_spec.get("params") or {}),
                            "inputs": resolved_inputs,
                            "outputs": {
                                "report": str(result_dir / "run-report.html"),
                                "summary": str(result_dir / "summary.tsv"),
                                "raw_log": str(result_dir / "raw-log.txt"),
                            },
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
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
            )
            return

        update_run_state(
            cfg,
            run_id=run_id,
            status="running",
            stage="validate",
            message="Validating Snakemake workflow.",
            request_id=request_id,
        )

        dry_run_cmd = [
            *_snakemake_command(cfg),
            "--snakefile",
            str(snakefile),
            "--directory",
            str(work_dir),
            "--cores",
            "1",
            "--use-conda",
            "--configfile",
            str(config_path),
            "-n",
        ]
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
        run_cmd = [
            *_snakemake_command(cfg),
            "--snakefile",
            str(snakefile),
            "--directory",
            str(work_dir),
            "--cores",
            "1",
            "--use-conda",
            "--configfile",
            str(config_path),
        ]
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

        _collect_artifacts(cfg, run_id, result_dir)
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Snakemake execution completed.",
            request_id=request_id,
            result_dir=str(result_dir),
        )


def _collect_artifacts(cfg: RemoteRunnerConfig, run_id: str, result_dir: Path) -> list[dict]:
    artifacts = []
    mime_map = {
        ".html": "text/html",
        ".tsv": "text/tab-separated-values",
        ".txt": "text/plain",
    }
    kind_map = {
        ".html": "report",
        ".tsv": "table",
        ".txt": "log",
    }
    for path in sorted(result_dir.iterdir()):
        if not path.is_file():
            continue
        mime_type = mime_map.get(path.suffix, "application/octet-stream")
        kind = kind_map.get(path.suffix, "file")
        artifacts.append(persist_artifact(cfg, run_id=run_id, kind=kind, path=path, mime_type=mime_type))
    return artifacts


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
