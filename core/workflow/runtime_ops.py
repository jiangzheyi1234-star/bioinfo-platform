"""Workflow-first runtime helpers for local bundle materialization and SSH launches."""

from __future__ import annotations

import json
import os
import posixpath
import shlex
from pathlib import Path
from typing import Any

from core.environment.detached_job import ensure_remote_dirs, expand_home_expr, write_remote_script
from core.execution.artifact_store import ArtifactStore

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
    timeout: int = 20,
) -> dict[str, Any]:
    ensure_remote_dirs(ssh_run_fn, [remote_task_dir, remote_bundle_dir, remote_work_dir, remote_output_dir], timeout)
    script = _build_local_nextflow_launcher(
        remote_task_dir=remote_task_dir,
        remote_bundle_dir=remote_bundle_dir,
        remote_work_dir=remote_work_dir,
        remote_output_dir=remote_output_dir,
    )
    script_path = write_remote_script(
        ssh_run_fn,
        f"{remote_task_dir}/launch.sh",
        script,
        timeout,
        label="workflow launch script",
    )
    rc, stdout, stderr = ssh_run_fn(
        f"nohup bash {script_path} >/dev/null 2>&1 & echo $!",
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
        "echo __PID__; cat " + shlex.quote(f"{remote_task_dir}/launcher.pid") + " 2>/dev/null || true; "
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
    elif status in {"PENDING", "PREPARING", "SUBMITTED"}:
        stage = "pending"
    return {
        "raw_status": status,
        "stage": stage,
        "exit_code": exit_code,
        "launcher_pid": str(sections.get("__PID__", "")).strip(),
        "heartbeat": str(sections.get("__HEARTBEAT__", "")).strip(),
        "log_tail": str(sections.get("__LOG__", "")).strip(),
    }


def download_run_artifacts(ssh_service: Any, *, project_dir: Path, run_id: str, remote_bundle_dir: str) -> list[dict[str, Any]]:
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


def _build_local_nextflow_launcher(*, remote_task_dir: str, remote_bundle_dir: str, remote_work_dir: str, remote_output_dir: str) -> str:
    task_dir_expr = f"$(eval echo {expand_home_expr(remote_task_dir)})"
    bundle_dir_expr = f"$(eval echo {expand_home_expr(remote_bundle_dir)})"
    work_dir_expr = f"$(eval echo {expand_home_expr(remote_work_dir)})"
    output_dir_expr = f"$(eval echo {expand_home_expr(remote_output_dir)})"
    return f"""#!/bin/bash
set -euo pipefail

TASK_DIR="{task_dir_expr}"
BUNDLE_DIR="{bundle_dir_expr}"
WORK_DIR="{work_dir_expr}"
OUTPUT_DIR="{output_dir_expr}"
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
PID_FILE="$TASK_DIR/launcher.pid"
LOG_FILE="$TASK_DIR/task.log"

echo "PENDING" > "$STATUS_FILE"
echo "$$" > "$PID_FILE"
exec > "$LOG_FILE" 2>&1

_heartbeat() {{
  while true; do
    date +%s > "$HEARTBEAT_FILE"
    sleep 15
  done
}}
_heartbeat &
HB_PID=$!

_cleanup() {{
  local ec=$?
  kill $HB_PID 2>/dev/null || true
  echo "$ec" > "$EXIT_CODE_FILE"
  if [ "$ec" -eq 0 ]; then
    echo "DONE" > "$STATUS_FILE"
  else
    echo "FAILED" > "$STATUS_FILE"
  fi
}}
trap _cleanup EXIT

mkdir -p "$TASK_DIR" "$BUNDLE_DIR" "$WORK_DIR" "$OUTPUT_DIR"
cd "$BUNDLE_DIR"
echo "RUNNING" > "$STATUS_FILE"

nextflow -C resolved.config run main.nf \\
  -params-file params/run.yaml \\
  -work-dir "$WORK_DIR" \\
  -resume \\
  -with-report report.html \\
  -with-timeline timeline.html \\
  -with-trace trace.txt \\
  -with-dag dag.html \\
  -bg

while true; do
  date +%s > "$HEARTBEAT_FILE"
  if grep -q "Execution complete -- Goodbye" .nextflow.log 2>/dev/null; then
    exit 0
  fi
  if grep -q "Session aborted" .nextflow.log 2>/dev/null || grep -q "^ERROR ~" .nextflow.log 2>/dev/null; then
    exit 1
  fi
  sleep 10
done
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
