"""Miniforge 自管 conda 远端后台初始化（可恢复）。"""

from __future__ import annotations

import base64
import logging
import time

from core.environment.env_detector import SshRunFn
from core.environment.h2o_env_paths import H2O_CONDA_EXE, H2O_CONDA_HOME, H2O_CONDARC
from core.utils import sanitize_log

logger = logging.getLogger(__name__)

TASK_DIR = "~/.h2ometa/runtime/miniforge_bootstrap"
JOB_ID = "h2o_bootstrap_conda"
INSTALL_SCRIPT = f"{TASK_DIR}/install.sh"
LOG_TAIL_LINES = 60
HEARTBEAT_STALE_SECONDS = 180

_STATUS_ORDER_HINT = ("status.txt", "exit_code.txt", "heartbeat.txt")

_CONDARC_TEMPLATE = """\
channels:
  - conda-forge
  - bioconda
channel_priority: strict
remote_connect_timeout_secs: 30
remote_read_timeout_secs: 60
remote_max_retries: 5
"""

_BOOTSTRAP_WRAPPER = r"""#!/bin/bash
set -euo pipefail

export TERM=dumb
export CONDA_QUIET=1
export PIP_PROGRESS_BAR=off

TASK_DIR="{task_dir}"
STATUS_FILE="$TASK_DIR/status.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
LOG_FILE="$TASK_DIR/task.log"
CONDA_HOME="{conda_home}"
CONDA_EXE="{conda_exe}"
CONDARC_PATH="{condarc_path}"
INSTALLER="/tmp/miniforge_install.sh"
CONDARC_B64='{condarc_b64}'

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
    kill $HB_PID 2>/dev/null || true
    echo "$ec" > "$EXIT_CODE_FILE"
    if [ "$ec" -eq 0 ]; then
        echo "DONE" > "$STATUS_FILE"
    else
        echo "FAILED" > "$STATUS_FILE"
    fi
}}
trap _cleanup EXIT

exec > "$LOG_FILE" 2>&1

ARCH="$(uname -m || true)"
if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "aarch64" ]; then
    echo "Unsupported arch: ${{ARCH:-unknown}}" >&2
    exit 2
fi

if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$INSTALLER" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${{ARCH}}.sh"
elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$INSTALLER" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${{ARCH}}.sh"
else
    echo "curl/wget not found" >&2
    exit 3
fi

mkdir -p "$(dirname "$CONDA_HOME")"
bash "$INSTALLER" -b -p "$CONDA_HOME"
rm -f "$INSTALLER"

mkdir -p "$(dirname "$CONDARC_PATH")"
echo "$CONDARC_B64" | base64 -d > "$CONDARC_PATH"

"$CONDA_EXE" config --add channels bioconda || true
"$CONDA_EXE" config --set channel_priority strict || true
"$CONDA_EXE" --version
"""


def _expand_path(path: str) -> str:
    return path.replace("~", "$HOME")


def submit(ssh_run_fn: SshRunFn, timeout: int = 20) -> dict:
    """提交后台 Miniforge 初始化任务（screen detached）。"""
    alive = is_session_alive(ssh_run_fn, JOB_ID, timeout=timeout)
    status = check_status(ssh_run_fn, TASK_DIR, timeout=timeout)
    status_text = (status.get("status") or "").strip().upper()
    heartbeat = (status.get("heartbeat") or "").strip()
    if alive:
        # 优先以 screen 会话存活判定“已有任务运行中”，避免 status 文件异常导致重复提交。
        return {
            "job_id": JOB_ID,
            "task_dir": TASK_DIR,
            "already_running": True,
            "status": status.get("status", ""),
        }
    if status_text == "RUNNING" and is_heartbeat_fresh(heartbeat):
        # 会话探测可能瞬时失败；若 RUNNING 且心跳新鲜，判定任务仍在执行，避免重复下载。
        return {
            "job_id": JOB_ID,
            "task_dir": TASK_DIR,
            "already_running": True,
            "status": status.get("status", ""),
        }

    task_dir_expanded = f'"$(eval echo {_expand_path(TASK_DIR)})"'
    script_path_expanded = f'"$(eval echo {_expand_path(INSTALL_SCRIPT)})"'

    ssh_run_fn(f"mkdir -p {task_dir_expanded}", timeout)
    ssh_run_fn(f"rm -f {task_dir_expanded}/status.txt {task_dir_expanded}/exit_code.txt {task_dir_expanded}/heartbeat.txt", timeout)

    script = _BOOTSTRAP_WRAPPER.format(
        task_dir=f"$(eval echo {_expand_path(TASK_DIR)})",
        conda_home=f"$(eval echo {_expand_path(H2O_CONDA_HOME)})",
        conda_exe=f"$(eval echo {_expand_path(H2O_CONDA_EXE)})",
        condarc_path=f"$(eval echo {_expand_path(H2O_CONDARC)})",
        condarc_b64=base64.b64encode(_CONDARC_TEMPLATE.encode()).decode(),
    )
    encoded = base64.b64encode(script.encode()).decode()

    rc, _, stderr = ssh_run_fn(f"echo '{encoded}' | base64 -d > {script_path_expanded}", timeout)
    if rc != 0:
        raise RuntimeError(f"写入 Miniforge 安装脚本失败: {stderr[:200]}")
    ssh_run_fn(f"chmod +x {script_path_expanded}", timeout)

    ssh_run_fn(f"screen -S {JOB_ID} -X quit 2>/dev/null || true", timeout)
    rc, _, stderr = ssh_run_fn(f"screen -dmS {JOB_ID} bash {script_path_expanded}", timeout)
    if rc != 0:
        raise RuntimeError(f"启动 Miniforge 后台任务失败: {stderr[:200]}")
    logger.info("Miniforge 后台初始化已提交: job_id=%s task_dir=%s", JOB_ID, TASK_DIR)
    return {
        "job_id": JOB_ID,
        "task_dir": TASK_DIR,
        "already_running": False,
        "status": status.get("status", ""),
    }


def check_status(ssh_run_fn: SshRunFn, task_dir: str = TASK_DIR, timeout: int = 10) -> dict:
    """按 status/exit_code/heartbeat 顺序读取任务状态。"""
    expanded = f'"$(eval echo {_expand_path(task_dir)})"'
    status = ""
    exit_code = ""
    heartbeat = ""
    try:
        rc, stdout, _ = ssh_run_fn(f"cat {expanded}/status.txt 2>/dev/null", timeout)
        if rc == 0:
            status = stdout.strip()
    except Exception:
        pass
    if status in ("DONE", "FAILED"):
        try:
            rc, stdout, _ = ssh_run_fn(f"cat {expanded}/exit_code.txt 2>/dev/null", timeout)
            if rc == 0:
                exit_code = stdout.strip()
        except Exception:
            pass
    try:
        rc, stdout, _ = ssh_run_fn(f"cat {expanded}/heartbeat.txt 2>/dev/null", timeout)
        if rc == 0:
            heartbeat = stdout.strip()
    except Exception:
        pass
    return {
        "status": status,
        "exit_code": exit_code,
        "heartbeat": heartbeat,
        "order": _STATUS_ORDER_HINT,
    }


def read_log(ssh_run_fn: SshRunFn, task_dir: str = TASK_DIR, tail_lines: int = LOG_TAIL_LINES, timeout: int = 10) -> str:
    expanded = f'"$(eval echo {_expand_path(task_dir)})"'
    try:
        rc, stdout, _ = ssh_run_fn(f"tail -n {tail_lines} {expanded}/task.log 2>/dev/null", timeout)
        if rc == 0:
            return sanitize_log(stdout)
    except Exception:
        pass
    return ""


def is_session_alive(ssh_run_fn: SshRunFn, job_id: str = JOB_ID, timeout: int = 10) -> bool:
    try:
        rc, _, _ = ssh_run_fn(f"screen -ls | grep -q '{job_id}'", timeout)
        return rc == 0
    except Exception:
        return False


def is_heartbeat_fresh(heartbeat_value: str, stale_seconds: int = HEARTBEAT_STALE_SECONDS) -> bool:
    try:
        ts = int((heartbeat_value or "").strip())
    except Exception:
        return False
    return (time.time() - ts) <= stale_seconds
