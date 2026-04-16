"""Workflow-first runtime helpers for local bundle materialization and SSH launches."""

from __future__ import annotations

import json
import os
import posixpath
import shlex
from pathlib import Path
from typing import Any

from core.workflow.remote_job_utils import ensure_remote_dirs, expand_home_expr, write_remote_script
from core.execution.artifact_store import ArtifactStore
from core.remote.runtime_resolution import (
    build_runtime_env_exports,
    resolve_persisted_runtime_binding,
    resolve_remote_java,
    resolve_remote_nextflow,
)

_KNOWN_ARTIFACTS = (
    ".nextflow.log",
    "trace.txt",
    "report.html",
    "timeline.html",
    "dag.html",
)


def materialize_bundle(project_dir: Path, run_id: str, compiled_bundle: dict[str, Any]) -> dict[str, str]:
    run_dir = project_dir / "workflow_runs" / run_id
    bundle_dir = run_dir / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    files = compiled_bundle.get("files", {})
    if not isinstance(files, dict):
        raise RuntimeError("compiled bundle files must be an object")
    for relative_path, content in files.items():
        rel = str(relative_path or "").strip().replace("\\", "/")
        if not rel:
            continue
        target = bundle_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content or ""), encoding="utf-8")
    return {
        "run_dir": str(run_dir),
        "bundle_dir": str(bundle_dir),
        "artifacts_dir": str(run_dir / "artifacts"),
        "record_path": str(run_dir / "run_record.json"),
    }


def persist_run_record(record_path: str, payload: dict[str, Any]) -> None:
    path = Path(record_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_run_record(record_path: str) -> dict[str, Any]:
    path = Path(record_path)
    if not path.exists():
        raise RuntimeError(f"workflow run record not found: {record_path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"workflow run record is invalid JSON: {record_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"workflow run record must be an object: {record_path}")
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError(f"workflow run record is missing run_id: {record_path}")
    return payload


def load_project_run_records(project_dir: Path) -> dict[str, dict[str, Any]]:
    run_root = project_dir / "workflow_runs"
    if not run_root.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for record_path in sorted(run_root.glob("*/run_record.json")):
        payload = load_run_record(str(record_path))
        rows[str(payload["run_id"])] = payload
    return rows


def recursive_upload_directory(ssh_service: Any, local_dir: Path, remote_dir: str) -> None:
    sftp = ssh_service.sftp()
    try:
        _sftp_makedirs(sftp, remote_dir)
        for dirpath, _dirnames, filenames in os.walk(local_dir):
            relative = os.path.relpath(dirpath, local_dir)
            remote_subdir = remote_dir if relative == "." else posixpath.join(remote_dir, relative.replace(os.sep, "/"))
            _sftp_makedirs(sftp, remote_subdir)
            for filename in filenames:
                local_path = Path(dirpath) / filename
                remote_path = posixpath.join(remote_subdir, filename)
                sftp.put(str(local_path), remote_path)
    finally:
        sftp.close()


def submit_local_nextflow_run(
    ssh_run_fn,
    *,
    remote_task_dir: str,
    remote_bundle_dir: str,
    remote_work_dir: str,
    remote_output_dir: str,
    resume: bool,
    packaging_mode: str = "",
    container_runtime: str = "",
    resolved_runtime: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    ensure_remote_dirs(ssh_run_fn, [remote_task_dir, remote_bundle_dir, remote_work_dir, remote_output_dir], timeout)
    normalized_packaging = str(packaging_mode or "").strip()
    normalized_runtime = str(container_runtime or "").strip()
    if normalized_packaging or normalized_runtime:
        if normalized_packaging != "container" or normalized_runtime != "docker":
            raise RuntimeError("执行型 workflow 当前仅支持 Docker 作为后端；不再允许 podman/conda/host fallback")
        rc_docker, _stdout_docker, _stderr_docker = ssh_run_fn("docker ps >/dev/null 2>&1", timeout)
        if rc_docker != 0:
            raise RuntimeError("Docker 未就绪；当前 workflow profile 要求 Docker 作为执行后端，请先在终端完成修复并重新验证")
    binding = None
    if isinstance(resolved_runtime, dict) and resolved_runtime:
        binding = resolve_persisted_runtime_binding(ssh_run_fn, resolved_runtime, timeout=timeout)
        nextflow_bin = str(binding.get("nextflow_command") or binding.get("nextflow_path") or "").strip()
        java_info = {"home": str(binding.get("java_home") or "").strip()}
        enable_nxf_agent_mode = bool(binding.get("agent_mode_supported", False))
    else:
        nextflow_info = resolve_remote_nextflow(ssh_run_fn, timeout=timeout)
        if not nextflow_info.get("usable", False):
            raise RuntimeError(str(nextflow_info.get("message") or "Nextflow 未就绪"))
        java_info = resolve_remote_java(ssh_run_fn, timeout=timeout)
        if not java_info.get("usable", False):
            raise RuntimeError(str(java_info.get("message") or "Java 未就绪"))
        nextflow_bin = str(nextflow_info.get("path") or nextflow_info.get("command") or "nextflow")
        enable_nxf_agent_mode = bool(nextflow_info.get("agent_mode_supported", False))
    script = _build_local_nextflow_launcher(
        remote_task_dir=remote_task_dir,
        remote_bundle_dir=remote_bundle_dir,
        remote_work_dir=remote_work_dir,
        remote_output_dir=remote_output_dir,
        resume=resume,
        nextflow_bin=nextflow_bin,
        runtime_env_exports=build_runtime_env_exports(java_info),
        enable_nxf_agent_mode=enable_nxf_agent_mode,
    )
    script_path = write_remote_script(
        ssh_run_fn,
        f"{remote_task_dir}/launch.sh",
        script,
        timeout,
        label="workflow launch script",
    )
    rc, stdout, stderr = ssh_run_fn(
        f"nohup bash -lc {shlex.quote(f'bash {script_path}')} >/dev/null 2>&1 & echo $!",
        timeout,
    )
    launcher_pid = str(stdout or "").strip()
    if rc != 0 or not launcher_pid:
        raise RuntimeError(f"启动 workflow launcher 失败: {(stderr or stdout or '').strip()[:200]}")
    return {
        "task_dir": remote_task_dir,
        "bundle_dir": remote_bundle_dir,
        "work_dir": remote_work_dir,
        "output_dir": remote_output_dir,
        "launcher_pid": launcher_pid,
    }


def query_local_nextflow_run(ssh_run_fn, *, remote_task_dir: str, timeout: int = 15) -> dict[str, Any]:
    command = (
        "echo __STATUS__; cat " + shlex.quote(f"{remote_task_dir}/status.txt") + " 2>/dev/null || true; "
        "echo __EXIT__; cat " + shlex.quote(f"{remote_task_dir}/exit_code.txt") + " 2>/dev/null || true; "
        "echo __PID__; cat " + shlex.quote(f"{remote_task_dir}/pid") + " 2>/dev/null || true; "
        "echo __NFPID__; cat " + shlex.quote(f"{remote_task_dir}/nextflow.pid") + " 2>/dev/null || true; "
        "echo __HEARTBEAT__; cat " + shlex.quote(f"{remote_task_dir}/heartbeat.txt") + " 2>/dev/null || true; "
        "echo __LOG__; tail -n 60 " + shlex.quote(f"{remote_task_dir}/task.log") + " 2>/dev/null || true"
    )
    rc, out, err = ssh_run_fn(command, timeout)
    if rc != 0:
        raise RuntimeError((err or out or "query run status failed").strip()[:200])
    sections = _split_marked_sections(out)
    status = str(sections.get("__STATUS__", "")).strip().upper() or "UNKNOWN"
    exit_code = str(sections.get("__EXIT__", "")).strip()
    stage = "running"
    if status == "DONE":
        stage = "completed"
    elif status == "FAILED":
        stage = "failed"
    elif status == "CANCELLED":
        stage = "cancelled"
    elif status in {"PENDING", "PREPARING", "SUBMITTED"}:
        stage = "pending"
    return {
        "raw_status": status,
        "stage": stage,
        "exit_code": exit_code,
        "launcher_pid": str(sections.get("__PID__", "")).strip(),
        "nextflow_pid": str(sections.get("__NFPID__", "")).strip(),
        "heartbeat": str(sections.get("__HEARTBEAT__", "")).strip(),
        "log_tail": str(sections.get("__LOG__", "")).strip(),
    }


def cancel_local_nextflow_run(ssh_run_fn, *, remote_task_dir: str, timeout: int = 20) -> dict[str, Any]:
    command = f"""
TASK_DIR=$(eval echo {expand_home_expr(remote_task_dir)})
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
CANCEL_FILE="$TASK_DIR/cancel_requested"
PID_FILE="$TASK_DIR/pid"
NEXTFLOW_PID_FILE="$TASK_DIR/nextflow.pid"
touch "$CANCEL_FILE"
launcher_pid=""
nextflow_pid=""
if [ -f "$PID_FILE" ]; then
  launcher_pid=$(cat "$PID_FILE" 2>/dev/null || true)
fi
if [ -f "$NEXTFLOW_PID_FILE" ]; then
  nextflow_pid=$(cat "$NEXTFLOW_PID_FILE" 2>/dev/null || true)
fi
for pid in "$nextflow_pid" "$launcher_pid"; do
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null || true
  fi
done
sleep 2
for pid in "$nextflow_pid" "$launcher_pid"; do
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
done
echo "CANCELLED" > "$STATUS_FILE"
echo "130" > "$EXIT_CODE_FILE"
printf '__LAUNCHER__\\n%s\\n__NEXTFLOW__\\n%s\\n' "$launcher_pid" "$nextflow_pid"
""".strip()
    rc, out, err = ssh_run_fn(command, timeout)
    if rc != 0:
        raise RuntimeError((err or out or "cancel run failed").strip()[:200])
    sections = _split_marked_sections(out)
    return {
        "raw_status": "CANCELLED",
        "stage": "cancelled",
        "exit_code": "130",
        "launcher_pid": str(sections.get("__LAUNCHER__", "")).strip(),
        "nextflow_pid": str(sections.get("__NEXTFLOW__", "")).strip(),
    }


def download_run_artifacts(
    ssh_service: Any,
    *,
    project_dir: Path,
    run_id: str,
    remote_bundle_dir: str,
    remote_output_dir: str = "",
) -> list[dict[str, Any]]:
    artifact_root = project_dir / "workflow_runs" / run_id / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for name in _KNOWN_ARTIFACTS:
        remote_path = posixpath.join(remote_bundle_dir, name)
        local_path = artifact_root / name
        available = False
        error = ""
        try:
            if ArtifactStore.remote_file_exists(ssh_service, remote_path):
                ssh_service.download(remote_path, str(local_path))
                available = local_path.exists()
            else:
                error = "remote_file_not_found"
        except Exception as exc:
            error = str(exc)
        item = {
            "name": name,
            "remote_path": remote_path,
            "local_path": str(local_path),
            "available": available,
            **ArtifactStore.infer_artifact_metadata(name),
        }
        if error:
            item["error"] = error
        artifacts.append(item)
    if remote_output_dir:
        artifacts.extend(_download_output_artifacts(ssh_service, artifact_root, remote_output_dir))
    return artifacts


def _split_marked_sections(text: str) -> dict[str, str]:
    current = ""
    sections: dict[str, list[str]] = {}
    for line in str(text or "").splitlines():
        if line.startswith("__") and line.endswith("__"):
            current = line.strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _build_local_nextflow_launcher(
    *,
    remote_task_dir: str,
    remote_bundle_dir: str,
    remote_work_dir: str,
    remote_output_dir: str,
    resume: bool,
    nextflow_bin: str,
    runtime_env_exports: str,
    enable_nxf_agent_mode: bool,
) -> str:
    task_dir_expr = f"$(eval echo {expand_home_expr(remote_task_dir)})"
    bundle_dir_expr = f"$(eval echo {expand_home_expr(remote_bundle_dir)})"
    work_dir_expr = f"$(eval echo {expand_home_expr(remote_work_dir)})"
    output_dir_expr = f"$(eval echo {expand_home_expr(remote_output_dir)})"
    resume_line = '  -resume \\\n' if resume else ""
    return f"""#!/bin/bash
set -euo pipefail

TASK_DIR="{task_dir_expr}"
BUNDLE_DIR="{bundle_dir_expr}"
WORK_DIR="{work_dir_expr}"
OUTPUT_DIR="{output_dir_expr}"
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
PID_FILE="$TASK_DIR/pid"
NEXTFLOW_PID_FILE="$TASK_DIR/nextflow.pid"
CANCEL_FILE="$TASK_DIR/cancel_requested"
LOG_FILE="$TASK_DIR/task.log"
NEXTFLOW_BIN={shlex.quote(nextflow_bin)}

echo "PENDING" > "$STATUS_FILE"
echo "$$" > "$PID_FILE"
exec > "$LOG_FILE" 2>&1

{runtime_env_exports.rstrip()}
{"export NXF_AGENT_MODE=true" if enable_nxf_agent_mode else ""}

_heartbeat() {{
  while true; do
    date +%s > "$HEARTBEAT_FILE"
    sleep 15
  done
}}
_heartbeat &
HB_PID=$!

_forward_cancel() {{
  touch "$CANCEL_FILE"
  if [ -n "${{NF_PID:-}}" ] && kill -0 "${{NF_PID}}" 2>/dev/null; then
    kill "${{NF_PID}}" 2>/dev/null || true
  fi
}}
trap _forward_cancel INT TERM

_cleanup() {{
  local ec=$?
  kill $HB_PID 2>/dev/null || true
  if [ -f "$CANCEL_FILE" ]; then
    ec=130
  fi
  echo "$ec" > "$EXIT_CODE_FILE"
  if [ "$ec" -eq 130 ]; then
    echo "CANCELLED" > "$STATUS_FILE"
  elif [ "$ec" -eq 0 ]; then
    echo "DONE" > "$STATUS_FILE"
  else
    echo "FAILED" > "$STATUS_FILE"
  fi
}}
trap _cleanup EXIT

mkdir -p "$TASK_DIR" "$BUNDLE_DIR" "$WORK_DIR" "$OUTPUT_DIR"
rm -f "$CANCEL_FILE"
cd "$BUNDLE_DIR"
echo "RUNNING" > "$STATUS_FILE"

"$NEXTFLOW_BIN" -C resolved.config run main.nf \\
  -params-file params/run.yaml \\
  -work-dir "$WORK_DIR" \\
{resume_line}  -with-report report.html \\
  -with-timeline timeline.html \\
  -with-trace trace.txt \\
  -with-dag dag.html &
NF_PID=$!
echo "$NF_PID" > "$NEXTFLOW_PID_FILE"

while kill -0 "$NF_PID" 2>/dev/null; do
  date +%s > "$HEARTBEAT_FILE"
  sleep 10
done

wait "$NF_PID"
"""


def _sftp_makedirs(sftp, remote_path: str) -> None:
    parts = remote_path.split("/")
    current = ""
    for part in parts:
        if not part:
            current = "/"
            continue
        current = f"{current}/{part}" if current != "/" else f"/{part}"
        try:
            sftp.stat(current)
        except OSError:
            try:
                sftp.mkdir(current)
            except OSError:
                pass


def _download_output_artifacts(ssh_service: Any, artifact_root: Path, remote_output_dir: str) -> list[dict[str, Any]]:
    quoted = shlex.quote(remote_output_dir)
    rc, stdout, stderr = ssh_service.run(
        f"find {quoted} -maxdepth 3 -type f | sort | head -n 200",
        timeout=15,
    )
    if rc != 0:
        return [
            {
                "name": "published_outputs",
                "remote_path": remote_output_dir,
                "local_path": "",
                "available": False,
                "error": (stderr or stdout or "find remote outputs failed").strip()[:200],
                **ArtifactStore.infer_artifact_metadata("published_outputs.txt"),
            }
        ]
    artifacts: list[dict[str, Any]] = []
    for remote_path in [line.strip() for line in stdout.splitlines() if line.strip()]:
        name = posixpath.relpath(remote_path, remote_output_dir)
        local_path = artifact_root / "published" / name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        available = False
        error = ""
        try:
            ssh_service.download(remote_path, str(local_path))
            available = local_path.exists()
        except Exception as exc:
            error = str(exc)
        item = {
            "name": f"published/{name}",
            "remote_path": remote_path,
            "local_path": str(local_path),
            "available": available,
            **ArtifactStore.infer_artifact_metadata(name),
        }
        if error:
            item["error"] = error
        artifacts.append(item)
    return artifacts
