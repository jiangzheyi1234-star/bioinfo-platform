"""Remote workflow runtime bootstrap helpers."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from core.environment.detached_job import clear_remote_status_files, ensure_remote_dirs, write_remote_script

from .bootstrap import BOOTSTRAP_DIR

WORKFLOW_BOOTSTRAP_BASE = "~/.bioflow/runtime_bootstrap"
WORKFLOW_BOOTSTRAP_PREFIX = "h2o_workflow_bootstrap_"
_BOOTSTRAP_TIMEOUT = 20
_LOG_TAIL_LINES = 120


def workflow_bootstrap_task_dir(profile_kind: str) -> str:
    normalized_profile_kind = str(profile_kind or "").strip()
    if not normalized_profile_kind:
        raise RuntimeError("workflow bootstrap profile_kind is required")
    return f"{WORKFLOW_BOOTSTRAP_BASE}/{normalized_profile_kind}"


def submit_workflow_runtime_bootstrap(ssh_run_fn: Any, *, profile_kind: str) -> dict[str, Any]:
    normalized_profile_kind = str(profile_kind or "").strip()
    if not normalized_profile_kind:
        raise RuntimeError("workflow bootstrap profile_kind is required")
    local_install_script = BOOTSTRAP_DIR / "install.sh"
    if not local_install_script.exists():
        raise RuntimeError(f"workflow bootstrap asset is missing: {local_install_script}")

    task_dir = workflow_bootstrap_task_dir(normalized_profile_kind)
    install_script_path = f"{task_dir}/install.sh"
    wrapper_script_path = f"{task_dir}/wrapper.sh"
    ensure_remote_dirs(ssh_run_fn, [task_dir], _BOOTSTRAP_TIMEOUT)
    clear_remote_status_files(
        ssh_run_fn,
        task_dir,
        _BOOTSTRAP_TIMEOUT,
        filenames=("status.txt", "exit_code.txt", "heartbeat.txt", "pid.txt", "task.log"),
    )
    write_remote_script(
        ssh_run_fn,
        install_script_path,
        local_install_script.read_text(encoding="utf-8"),
        _BOOTSTRAP_TIMEOUT,
        label="workflow bootstrap install.sh",
    )
    wrapper_script = _workflow_bootstrap_wrapper_script(
        task_dir=task_dir,
        profile_kind=normalized_profile_kind,
        install_script_path=install_script_path,
    )
    remote_wrapper_path = write_remote_script(
        ssh_run_fn,
        wrapper_script_path,
        wrapper_script,
        _BOOTSTRAP_TIMEOUT,
        label="workflow bootstrap wrapper.sh",
    )
    quoted_task_dir = shlex.quote(task_dir)
    rc, stdout, stderr = ssh_run_fn(
        f"cd $(eval echo {quoted_task_dir}) && nohup bash {remote_wrapper_path} >/dev/null 2>&1 & echo $!",
        _BOOTSTRAP_TIMEOUT,
    )
    if rc != 0:
        raise RuntimeError(f"启动 workflow runtime bootstrap 失败: {(stderr or stdout or '').strip()[:200]}")
    pid = str(stdout or "").strip().splitlines()
    return {
        "job_id": f"{WORKFLOW_BOOTSTRAP_PREFIX}{normalized_profile_kind}",
        "task_dir": task_dir,
        "already_running": False,
        "launcher_pid": pid[-1] if pid else "",
    }


def read_workflow_bootstrap_status(ssh_run_fn: Any, *, task_dir: str) -> tuple[dict[str, Any], bool, str]:
    quoted_task_dir = shlex.quote(task_dir)
    rc, stdout, _ = ssh_run_fn(
        (
            f'DIR=$(eval echo {quoted_task_dir}); '
            'STATUS="$(cat "$DIR/status.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            'EXIT_CODE="$(cat "$DIR/exit_code.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            'HEARTBEAT="$(cat "$DIR/heartbeat.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            'PID="$(cat "$DIR/pid.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            f'LOG_PREVIEW="$(tail -n {_LOG_TAIL_LINES} "$DIR/task.log" 2>/dev/null)"; '
            'printf "STATUS=%s\\nEXIT_CODE=%s\\nHEARTBEAT=%s\\nPID=%s\\nLOG_PREVIEW<<EOF\\n%s\\nEOF\\n" "$STATUS" "$EXIT_CODE" "$HEARTBEAT" "$PID" "$LOG_PREVIEW"'
        ),
        10,
    )
    raw_status: dict[str, Any] = {
        "status": "",
        "exit_code": "",
        "heartbeat": "",
        "pid": "",
        "log_preview": "",
    }
    if rc == 0 and stdout:
        raw_status = _parse_status_payload(stdout)
    pid = str(raw_status.get("pid") or "").strip()
    session_alive = False
    if pid:
        check_rc, _, _ = ssh_run_fn(f"kill -0 {shlex.quote(pid)} >/dev/null 2>&1", 10)
        session_alive = check_rc == 0
    log_text = str(raw_status.get("log_preview") or "")
    return raw_status, session_alive, log_text


def _workflow_bootstrap_wrapper_script(*, task_dir: str, profile_kind: str, install_script_path: str) -> str:
    quoted_profile_kind = shlex.quote(profile_kind)
    quoted_task_dir = shlex.quote(task_dir)
    quoted_install_script = shlex.quote(install_script_path)
    return f"""#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(eval echo {quoted_task_dir})"
PROFILE_KIND={quoted_profile_kind}
INSTALL_SCRIPT="$(eval echo {quoted_install_script})"
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
PID_FILE="$TASK_DIR/pid.txt"
LOG_FILE="$TASK_DIR/task.log"

mkdir -p "$TASK_DIR"
echo "$PROFILE_KIND" > "$TASK_DIR/profile_kind.txt"
echo "$$" > "$PID_FILE"
echo "RUNNING" > "$STATUS_FILE"

_heartbeat() {{
  while true; do
    date +%s > "$HEARTBEAT_FILE"
    sleep 30
  done
}}

_heartbeat &
HB_PID=$!

_cleanup() {{
  local ec=$?
  kill "$HB_PID" 2>/dev/null || true
  echo "$ec" > "$EXIT_CODE_FILE"
  if [ "$ec" -eq 0 ]; then
    echo "DONE" > "$STATUS_FILE"
  else
    echo "FAILED" > "$STATUS_FILE"
  fi
}}

trap _cleanup EXIT

exec > "$LOG_FILE" 2>&1
bash "$INSTALL_SCRIPT" "$PROFILE_KIND"
"""


def _parse_status_payload(payload: str) -> dict[str, Any]:
    lines = str(payload or "").splitlines()
    result: dict[str, Any] = {
        "status": "",
        "exit_code": "",
        "heartbeat": "",
        "pid": "",
        "log_preview": "",
    }
    collecting_log = False
    log_lines: list[str] = []
    for raw in lines:
        if collecting_log:
            if raw == "EOF":
                collecting_log = False
                continue
            log_lines.append(raw)
            continue
        if raw.startswith("STATUS="):
            result["status"] = raw[len("STATUS="):].strip()
        elif raw.startswith("EXIT_CODE="):
            result["exit_code"] = raw[len("EXIT_CODE="):].strip()
        elif raw.startswith("HEARTBEAT="):
            result["heartbeat"] = raw[len("HEARTBEAT="):].strip()
        elif raw.startswith("PID="):
            result["pid"] = raw[len("PID="):].strip()
        elif raw.startswith("LOG_PREVIEW<<EOF"):
            collecting_log = True
    result["log_preview"] = "\n".join(log_lines).strip()
    return result
