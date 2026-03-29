"""Miniforge 自管 conda 远端后台初始化（可恢复）。"""

from __future__ import annotations

import base64
import logging
import time

from core.environment.h2o_env_paths import H2O_CONDA_EXE, H2O_CONDA_HOME, H2O_CONDARC
from core.environment.miniforge_condarc import build_condarc_template, build_miniforge_release_bases
from core.remote.server_capabilities import PreflightError, ServerCapabilities, SshRunFn
from core.utils import sanitize_log

logger = logging.getLogger(__name__)

MINIFORGE_RELEASE_API_URL = "https://api.github.com/repos/conda-forge/miniforge/releases/latest"
MINIFORGE_INSTALLER_MIN_BYTES = 1_000_000
TASK_DIR = "~/.h2ometa/runtime/miniforge_bootstrap"
JOB_ID = "h2o_bootstrap_conda"
INSTALL_SCRIPT = f"{TASK_DIR}/install.sh"
LOG_TAIL_LINES = 60
HEARTBEAT_STALE_SECONDS = 180

_STATUS_ORDER_HINT = ("status.txt", "exit_code.txt", "heartbeat.txt")

def _bootstrap_source_entries() -> str:
    entries = []
    for label, base in build_miniforge_release_bases():
        installer_url = f"{base}/${{MINIFORGE_VERSION}}/Miniforge3-Linux-${{ARCH}}.sh"
        checksum_url = f"{installer_url}.sha256"
        entries.append(f'    "{label}|{installer_url}|{checksum_url}"')
    return " \\\n".join(entries)


def _download_to_file_impl(downloader: str) -> str:
    if downloader == "curl":
        return r"""_download_to_file() {
    local url="$1"
    local destination="$2"

    rm -f "$destination"
    curl -fsSL --connect-timeout 15 --max-time 120 -o "$destination" "$url"
}"""
    return r"""_download_to_file() {
    local url="$1"
    local destination="$2"

    rm -f "$destination"
    wget -q --timeout=120 -O "$destination" "$url"
}"""


def _download_text_impl(downloader: str) -> str:
    if downloader == "curl":
        return r"""_download_text() {
    local url="$1"
    curl -fsSL --connect-timeout 15 --max-time 60 "$url"
}"""
    return r"""_download_text() {
    local url="$1"
    wget -q -O - --timeout=60 "$url"
}"""

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
RELEASE_API_URL="{release_api_url}"
INSTALLER=""
CHECKSUM_FILE=""
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
    rm -f "$INSTALLER" "$CHECKSUM_FILE" 2>/dev/null || true
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

{download_to_file_impl}

{download_text_impl}

_record_failure() {{
    local label="$1"
    local reason="$2"
    local item="[$label] $reason"
    echo "Miniforge source failed: $item" >&2
    if [ -z "${{FAILURE_SUMMARY:-}}" ]; then
        FAILURE_SUMMARY="$item"
    else
        FAILURE_SUMMARY="${{FAILURE_SUMMARY}} | $item"
    fi
}}

_resolve_latest_version() {{
    local payload=""
    local version=""
    if ! payload="$(_download_text "$RELEASE_API_URL")"; then
        return 1
    fi
    version="$(printf '%s' "$payload" | tr -d '\r\n' | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]\+\)".*/\1/p')"
    case "$version" in
        ""|*[!A-Za-z0-9._-]*)
            return 1
            ;;
    esac
    printf '%s\n' "$version"
    return 0
}}

_download_one() {{
    local label="$1"
    local installer_url="$2"
    local checksum_url="$3"
    local size=""
    local shebang=""
    local expected_sha256=""

    if ! _download_to_file "$installer_url" "$INSTALLER"; then
        _record_failure "$label" "installer download failed: $installer_url"
        return 1
    fi

    size="$(stat -c%s "$INSTALLER" 2>/dev/null || echo 0)"
    if [ "$size" -lt {installer_min_bytes} ]; then
        _record_failure "$label" "installer too small: $size bytes"
        return 1
    fi

    shebang="$(head -n 1 "$INSTALLER" 2>/dev/null || true)"
    if ! printf '%s\n' "$shebang" | grep -q '^#!'; then
        _record_failure "$label" "installer shebang check failed"
        return 1
    fi

    if ! _download_to_file "$checksum_url" "$CHECKSUM_FILE"; then
        _record_failure "$label" "checksum download failed: $checksum_url"
        return 1
    fi

    expected_sha256="$(grep -oE '[0-9a-fA-F]{{64}}' "$CHECKSUM_FILE" 2>/dev/null | head -n 1 | tr '[:upper:]' '[:lower:]')"
    if [ -z "$expected_sha256" ]; then
        _record_failure "$label" "checksum parse failed"
        return 1
    fi

    if ! printf '%s  %s\n' "$expected_sha256" "$INSTALLER" | sha256sum -c - >/dev/null 2>&1; then
        _record_failure "$label" "sha256 verify failed"
        return 1
    fi

    return 0
}}

INSTALLER="$(mktemp /tmp/miniforge_install.XXXXXX.sh)"
CHECKSUM_FILE="$(mktemp /tmp/miniforge_install.XXXXXX.sha256)"
FAILURE_SUMMARY=""
MINIFORGE_VERSION="$(_resolve_latest_version || true)"
if [ -z "$MINIFORGE_VERSION" ]; then
    _record_failure "latest-release" "latest release tag resolve failed via $RELEASE_API_URL"
    echo "all miniforge mirrors failed: $FAILURE_SUMMARY" >&2
    exit 4
fi
echo "Resolved Miniforge release tag: $MINIFORGE_VERSION"

DOWNLOAD_OK=0
for SOURCE in \
{source_entries}
do
    IFS='|' read -r LABEL URL SHA256_URL <<EOF
$SOURCE
EOF
    echo "Trying Miniforge source [$LABEL]: $URL"
    if _download_one "$LABEL" "$URL" "$SHA256_URL"; then
        DOWNLOAD_OK=1
        echo "Downloaded and verified Miniforge installer from [$LABEL]: $URL"
        break
    fi
done

if [ "$DOWNLOAD_OK" -ne 1 ]; then
    echo "all miniforge mirrors failed: $FAILURE_SUMMARY" >&2
    exit 4
fi

mkdir -p "$(dirname "$CONDA_HOME")"
bash "$INSTALLER" -b -p "$CONDA_HOME"

mkdir -p "$(dirname "$CONDARC_PATH")"
echo "$CONDARC_B64" | base64 -d > "$CONDARC_PATH"

"$CONDA_EXE" --version
"""


def _expand_path(path: str) -> str:
    return path.replace("~", "$HOME")


def submit(caps: ServerCapabilities, ssh_run_fn: SshRunFn, timeout: int = 20) -> dict:
    """提交后台 Miniforge 初始化任务（screen detached）。"""
    failures = caps.failures()
    if failures:
        raise PreflightError(failures)

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
        release_api_url=MINIFORGE_RELEASE_API_URL,
        installer_min_bytes=MINIFORGE_INSTALLER_MIN_BYTES,
        source_entries=_bootstrap_source_entries(),
        condarc_b64=base64.b64encode(build_condarc_template().encode()).decode(),
        download_to_file_impl=_download_to_file_impl(caps.downloader),
        download_text_impl=_download_text_impl(caps.downloader),
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
    cmd = (
        f'DIR={expanded}; '
        'STATUS="$(cat "$DIR/status.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
        'EXIT_CODE="$(cat "$DIR/exit_code.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
        'HEARTBEAT="$(cat "$DIR/heartbeat.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
        'printf "STATUS=%s\\nEXIT_CODE=%s\\nHEARTBEAT=%s\\n" "$STATUS" "$EXIT_CODE" "$HEARTBEAT"'
    )
    try:
        rc, stdout, _ = ssh_run_fn(cmd, timeout)
        if rc == 0 and stdout:
            for raw in stdout.splitlines():
                line = raw.strip()
                if line.startswith("STATUS="):
                    status = line[len("STATUS="):].strip()
                elif line.startswith("EXIT_CODE="):
                    exit_code = line[len("EXIT_CODE="):].strip()
                elif line.startswith("HEARTBEAT="):
                    heartbeat = line[len("HEARTBEAT="):].strip()
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
