"""Remote workflow runtime bootstrap helpers."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from core.environment.detached_job import clear_remote_status_files, ensure_remote_dirs, write_remote_script

from .bootstrap import BOOTSTRAP_DIR

WORKFLOW_BOOTSTRAP_BASE = "~/.bioflow/runtime_bootstrap"
WORKFLOW_BOOTSTRAP_PREFIX = "h2o_workflow_bootstrap_"
DOCKER_BOOTSTRAP_BASE = "~/.bioflow/docker_runtime_bootstrap"
DOCKER_BOOTSTRAP_JOB_ID = "h2o_docker_runtime_bootstrap"
_BOOTSTRAP_TIMEOUT = 20
_LOG_TAIL_LINES = 120
_WORKFLOW_PROGRESS_SPECS: dict[str, list[dict[str, str]]] = {
    "personal_docker": [
        {"key": "java", "label": "校验 Java 17-24"},
        {"key": "docker", "label": "验证 Docker"},
        {"key": "nextflow", "label": "准备 Nextflow"},
        {"key": "runtime_dirs", "label": "创建运行目录"},
        {"key": "verification", "label": "验证安装"},
    ],
    "personal_podman": [
        {"key": "java", "label": "校验 Java 17-24"},
        {"key": "podman", "label": "验证 Podman"},
        {"key": "nextflow", "label": "准备 Nextflow"},
        {"key": "runtime_dirs", "label": "创建运行目录"},
        {"key": "verification", "label": "验证安装"},
    ],
    "personal_conda": [
        {"key": "java", "label": "校验 Java"},
        {"key": "nextflow", "label": "安装 Nextflow"},
        {"key": "micromamba", "label": "安装 Micromamba"},
        {"key": "runtime_dirs", "label": "创建运行目录"},
        {"key": "verification", "label": "验证安装"},
    ],
    "hpc_slurm_apptainer": [
        {"key": "java", "label": "校验 Java"},
        {"key": "sbatch", "label": "校验 Slurm"},
        {"key": "apptainer", "label": "验证 Apptainer"},
        {"key": "nextflow", "label": "准备 Nextflow"},
        {"key": "runtime_dirs", "label": "创建运行目录"},
        {"key": "verification", "label": "验证安装"},
    ],
    "hpc_slurm_conda": [
        {"key": "java", "label": "校验 Java"},
        {"key": "sbatch", "label": "校验 Slurm"},
        {"key": "nextflow", "label": "安装 Nextflow"},
        {"key": "micromamba", "label": "安装 Micromamba"},
        {"key": "runtime_dirs", "label": "创建运行目录"},
        {"key": "verification", "label": "验证安装"},
    ],
}


def workflow_bootstrap_task_dir(profile_kind: str) -> str:
    normalized_profile_kind = str(profile_kind or "").strip()
    if not normalized_profile_kind:
        raise RuntimeError("workflow bootstrap profile_kind is required")
    return f"{WORKFLOW_BOOTSTRAP_BASE}/{normalized_profile_kind}"


def docker_bootstrap_task_dir() -> str:
    return DOCKER_BOOTSTRAP_BASE


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


def submit_docker_runtime_bootstrap(ssh_run_fn: Any) -> dict[str, Any]:
    task_dir = docker_bootstrap_task_dir()
    wrapper_script_path = f"{task_dir}/wrapper.sh"
    ensure_remote_dirs(ssh_run_fn, [task_dir], _BOOTSTRAP_TIMEOUT)
    clear_remote_status_files(
        ssh_run_fn,
        task_dir,
        _BOOTSTRAP_TIMEOUT,
        filenames=("status.txt", "exit_code.txt", "heartbeat.txt", "pid.txt", "task.log"),
    )
    wrapper_script = _docker_bootstrap_wrapper_script(task_dir=task_dir)
    remote_wrapper_path = write_remote_script(
        ssh_run_fn,
        wrapper_script_path,
        wrapper_script,
        _BOOTSTRAP_TIMEOUT,
        label="docker runtime bootstrap wrapper.sh",
    )
    quoted_task_dir = shlex.quote(task_dir)
    rc, stdout, stderr = ssh_run_fn(
        f"cd $(eval echo {quoted_task_dir}) && nohup bash {remote_wrapper_path} >/dev/null 2>&1 & echo $!",
        _BOOTSTRAP_TIMEOUT,
    )
    if rc != 0:
        raise RuntimeError(f"启动 Docker 协助安装失败: {(stderr or stdout or '').strip()[:200]}")
    pid = str(stdout or "").strip().splitlines()
    return {
        "job_id": DOCKER_BOOTSTRAP_JOB_ID,
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


def read_docker_bootstrap_status(ssh_run_fn: Any, *, task_dir: str) -> tuple[dict[str, Any], bool, str]:
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


def build_workflow_runtime_progress(*, profile_kind: str, stage: str, log_text: str) -> dict[str, Any]:
    spec = _WORKFLOW_PROGRESS_SPECS.get(profile_kind, _WORKFLOW_PROGRESS_SPECS["personal_conda"])
    step_statuses = _parse_step_statuses(log_text)
    steps: list[dict[str, str]] = []
    for item in spec:
        steps.append(
            {
                "key": item["key"],
                "label": item["label"],
                "status": step_statuses.get(item["key"], "pending"),
            }
        )
    if stage == "done":
        steps = [
            {
                **item,
                "status": "done" if item["status"] in {"pending", "running"} else item["status"],
            }
            for item in steps
        ]
    elif stage == "failed":
        steps = _apply_failed_terminal_state(steps)
    return {
        "kind": "workflow_runtime",
        "profile_kind": profile_kind,
        "steps": steps,
    }


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


def _docker_bootstrap_wrapper_script(*, task_dir: str) -> str:
    quoted_task_dir = shlex.quote(task_dir)
    return f"""#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(eval echo {quoted_task_dir})"
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
PID_FILE="$TASK_DIR/pid.txt"
LOG_FILE="$TASK_DIR/task.log"
INSTALL_SCRIPT="$TASK_DIR/get-docker.sh"

mkdir -p "$TASK_DIR"
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
export DEBIAN_FRONTEND=noninteractive

echo "==> 检查当前用户与 sudo 权限"
CURRENT_USER="$(id -un)"
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
  SUDO="sudo -n"
else
  echo "ERROR: 需要 root 或免密 sudo 才能协助安装 Docker"
  exit 1
fi

echo "==> 检查发行版"
if [ ! -f /etc/os-release ]; then
  echo "ERROR: 当前系统缺少 /etc/os-release，无法判断是否支持 Docker 协助安装"
  exit 1
fi
. /etc/os-release
OS_HINT="$ID $ID_LIKE"
case " $OS_HINT " in
  *" debian "*|*" ubuntu "*|*" rhel "*|*" centos "*|*" fedora "*|*" rocky "*|*" almalinux "*)
    ;;
  *)
    echo "ERROR: 当前发行版不在实验性 Docker 协助安装支持范围内: ${ID:-unknown}"
    exit 1
    ;;
esac

if command -v docker >/dev/null 2>&1; then
  echo "==> Docker 已安装，跳过安装阶段"
else
  echo "==> 下载 Docker 官方安装脚本"
  rm -f "$INSTALL_SCRIPT"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com -o "$INSTALL_SCRIPT"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$INSTALL_SCRIPT" https://get.docker.com
  else
    echo "ERROR: 缺少 curl/wget，无法下载 Docker 安装脚本"
    exit 1
  fi
  chmod +x "$INSTALL_SCRIPT"

  echo "==> 执行 Docker 安装脚本（实验性）"
  if [ -n "$SUDO" ]; then
    $SUDO sh "$INSTALL_SCRIPT"
  else
    sh "$INSTALL_SCRIPT"
  fi
fi

echo "==> 启动 Docker 服务"
if command -v systemctl >/dev/null 2>&1; then
  if [ -n "$SUDO" ]; then
    $SUDO systemctl enable --now docker || true
  else
    systemctl enable --now docker || true
  fi
fi

if getent group docker >/dev/null 2>&1; then
  echo "==> 将当前用户加入 docker 组"
  if [ -n "$SUDO" ]; then
    $SUDO usermod -aG docker "$CURRENT_USER" || true
  else
    usermod -aG docker "$CURRENT_USER" || true
  fi
fi

echo "==> 验证 Docker"
if docker ps >/dev/null 2>&1; then
  echo "Docker 已可直接使用"
  exit 0
fi

echo "Docker 已安装，但当前 SSH 会话可能尚未获得 docker 组权限；请断开并重新连接后重新检查。"
exit 0
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


def _parse_step_statuses(log_text: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for raw in str(log_text or "").splitlines():
        if not raw.startswith("STEP="):
            continue
        payload = raw[len("STEP="):].strip()
        if ":" not in payload:
            continue
        key, status = payload.split(":", 1)
        normalized_key = key.strip()
        normalized_status = status.strip()
        if not normalized_key or normalized_status not in {"pending", "running", "done", "failed"}:
            continue
        statuses[normalized_key] = normalized_status
    return statuses


def _apply_failed_terminal_state(steps: list[dict[str, str]]) -> list[dict[str, str]]:
    failed_seen = False
    normalized: list[dict[str, str]] = []
    for item in steps:
        next_item = dict(item)
        if next_item["status"] == "failed":
            failed_seen = True
        elif next_item["status"] == "running":
            next_item["status"] = "failed"
            failed_seen = True
        elif failed_seen and next_item["status"] == "pending":
            next_item["status"] = "pending"
        normalized.append(next_item)
    return normalized
