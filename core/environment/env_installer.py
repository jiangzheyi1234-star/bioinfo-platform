"""通过 screen 在远端后台安装 conda 环境。

纯 Core 层模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现（与 env_detector 一致风格）。
使用 screen -dmS 模式，复用 status.txt / heartbeat.txt / task.log 机制，
确保 SSH 断线或软件关闭后安装不中断。
"""

import base64
import logging
import shlex
import time

from core.utils import sanitize_log
from core.environment.env_detector import (
    SshRunFn,
    extract_env_name,
    pin_create_env_to_conda_root,
    rewrite_install_cmd,
)
from core.environment.h2o_env_paths import (
    H2O_ENVS_DIR,
    H2O_INSTALL_DIR,
    h2o_env_prefix,
    h2o_tmp_prefix,
    is_managed_conda_executable,
)

logger = logging.getLogger(__name__)

INSTALL_BASE = H2O_INSTALL_DIR


# 包装脚本模板（原子安装：tmp_prefix → verify → rename 到 final_prefix）
#
# 关键环境变量：
#   TERM=dumb            — 禁止终端控制字符
#   CONDA_QUIET=1        — conda 不显示 spinner / 进度条
#   PIP_PROGRESS_BAR=off — pip 不显示进度条
#   CONDARC              — 指向受控 condarc，隔离用户系统配置
#
# 原子安装逻辑：
#   1. 安装到 TMP_PREFIX（临时目录）
#   2. 验证工具可用（可选）
#   3. mv TMP_PREFIX → FINAL_PREFIX（只有验证通过才出现正式目录）
#   中途失败：只有 TMP_PREFIX 残留，FINAL_PREFIX 不受影响；下次运行先清理残留
_INSTALL_WRAPPER = r"""#!/bin/bash
set -euo pipefail

export TERM=dumb
export CONDA_QUIET=1
export PIP_PROGRESS_BAR=off
export CONDARC="$HOME/.h2ometa/runtime/condarc"

TASK_DIR="{task_dir}"
STATUS_FILE="$TASK_DIR/status.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
LOG_FILE="$TASK_DIR/task.log"
TMP_PREFIX="{tmp_prefix}"
FINAL_PREFIX="{final_prefix}"

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
        # 清理临时目录（安装失败或验证失败时）
        rm -rf "$TMP_PREFIX" 2>/dev/null || true
        echo "FAILED" > "$STATUS_FILE"
    fi
}}
trap _cleanup EXIT

exec > "$LOG_FILE" 2>&1

# 清理上次中断的残留临时目录
rm -rf "$TMP_PREFIX" 2>/dev/null || true

# ===== 安装到临时路径 =====
{command}
# ===== 安装结束 =====

{verify_block}

# 原子提交：验��通过后替换正式目录
rm -rf "$FINAL_PREFIX" 2>/dev/null || true
mv "$TMP_PREFIX" "$FINAL_PREFIX"
echo "环境已就绪: $FINAL_PREFIX"
"""

# verify_block 模板（有 verify_cmd 时使用）
_VERIFY_BLOCK = r"""# ===== 安装后验证 =====
if ! {conda_run_p} -- {verify_cmd} 2>&1 | grep -qE '{version_regex}'; then
    echo "ERROR: 工具验证失败 — {verify_cmd} 输出不匹配 '{version_regex}'" >&2
    exit 1
fi
echo "验证通过: {verify_cmd}"
# ===== 验证结束 ====="""


def _expand_path(path: str) -> str:
    """将 ~ 替换为 $HOME 用于 shell eval。"""
    return path.replace("~", "$HOME")


class EnvInstaller:
    """通过 screen 在远端后台安装 conda 环境。"""

    @staticmethod
    def submit(
        ssh_run_fn: SshRunFn,
        tool_id: str,
        install_cmd: str,
        conda_executable: str = "",
        verify_cmd: str = "",
        version_regex: str = "",
        timeout: int = 15,
    ) -> dict:
        """启动后台安装（原子模式：tmp_prefix → verify → rename）。

        1. rewrite_install_cmd() 替换 conda 路径
        2. 计算 final_prefix / tmp_prefix
        3. 生成包装脚本（status.txt + heartbeat + task.log + trap + verify）
        4. 写到远端 ~/.h2ometa/env_installs/{tool_id}/install.sh
        5. screen -dmS h2o_install_{tool_id} bash install.sh

        Args:
            verify_cmd:     安装后验证命令（来自 tool.yaml detection.command），如 "fastp --version"
            version_regex:  版本正则（来自 tool.yaml detection.version_regex），如 r"\\d+\\.\\d+"

        Returns:
            {"job_id": str, "task_dir": str, "final_prefix": str}
        """
        if not conda_executable:
            raise RuntimeError("未检测到 conda 可执行路径，无法提交环境安装任务")
        if not is_managed_conda_executable(conda_executable):
            raise RuntimeError(f"检测到非自管 conda 路径，已拒绝: {conda_executable}")

        resolved_cmd = rewrite_install_cmd(install_cmd, conda_executable)

        # 计算安装路径
        env_name = extract_env_name(resolved_cmd) or tool_id
        final_prefix = h2o_env_prefix(env_name)
        tmp_prefix = h2o_tmp_prefix(env_name)

        def _expand_remote_required(path: str) -> str:
            rc, stdout, _ = ssh_run_fn(f"eval echo {_expand_path(path)}", timeout)
            expanded = stdout.strip() if rc == 0 else ""
            if not expanded or expanded.startswith(("~", "$HOME")):
                raise RuntimeError(f"无法展开远端路径: {path}")
            return expanded

        # 安装到临时路径（原子安装的关键）
        tmp_prefix_for_cmd = _expand_remote_required(tmp_prefix)
        resolved_cmd = pin_create_env_to_conda_root(
            resolved_cmd, conda_executable, override_prefix=tmp_prefix_for_cmd
        )

        # 构建 verify_block
        verify_block = ""
        if verify_cmd and version_regex and tmp_prefix and conda_executable:
            conda_run_p = f"{conda_executable} run -p \"$TMP_PREFIX\""
            verify_block = _VERIFY_BLOCK.format(
                conda_run_p=conda_run_p,
                verify_cmd=verify_cmd,
                version_regex=version_regex,
            )

        task_dir_raw = f"{INSTALL_BASE}/{tool_id}"
        task_dir_expanded = f'"$(eval echo {_expand_path(task_dir_raw)})"'
        envs_dir_expanded = f'"$(eval echo {_expand_path(H2O_ENVS_DIR)})"'

        # 创建任务目录
        ssh_run_fn(f"mkdir -p {task_dir_expanded}", timeout)
        ssh_run_fn(f"mkdir -p {envs_dir_expanded}", timeout)

        # tmp_prefix / final_prefix 在脚本内部展开 $HOME
        def _to_shell(p: str) -> str:
            return p.replace("~", "$HOME") if p else ""

        # 生成包装脚本
        script = _INSTALL_WRAPPER.format(
            task_dir=f"$(eval echo {_expand_path(task_dir_raw)})",
            tmp_prefix=_to_shell(tmp_prefix) if tmp_prefix else _to_shell(final_prefix),
            final_prefix=_to_shell(final_prefix) if final_prefix else "",
            command=resolved_cmd,
            verify_block=verify_block,
        )

        # 写脚本���远端（base64 编码避免特殊字符问题）
        script_path = f"{task_dir_raw}/install.sh"
        script_path_expanded = f'"$(eval echo {_expand_path(script_path)})"'

        encoded = base64.b64encode(script.encode()).decode()
        write_cmd = f"echo '{encoded}' | base64 -d > {script_path_expanded}"
        rc, _, stderr = ssh_run_fn(write_cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"写入安装脚本失败: {stderr[:200]}")

        # 启动 screen 会话
        job_id = f"h2o_install_{tool_id}"
        ssh_run_fn(f"screen -S {job_id} -X quit 2>/dev/null || true", timeout)
        screen_cmd = f"screen -dmS {job_id} bash {script_path_expanded}"
        rc, _, stderr = ssh_run_fn(screen_cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"启动 screen 会话失败: {stderr[:200]}")

        logger.info(
            "后台安装已启动: job_id=%s, task_dir=%s, final_prefix=%s",
            job_id, task_dir_raw, final_prefix,
        )
        return {"job_id": job_id, "task_dir": task_dir_raw, "final_prefix": final_prefix}

    @staticmethod
    def check_status(ssh_run_fn: SshRunFn, task_dir: str, timeout: int = 10) -> dict:
        """读 status.txt。

        Returns:
            {"status": "RUNNING"/"DONE"/"FAILED"/"", "exit_code": str}
        """
        expanded = f'"$(eval echo {_expand_path(task_dir)})"'

        status = ""
        try:
            rc, stdout, _ = ssh_run_fn(
                f"cat {expanded}/status.txt 2>/dev/null", timeout,
            )
            if rc == 0:
                status = stdout.strip()
        except Exception as e:
            logger.debug("读取 status.txt 失败: %s", e)

        exit_code = ""
        if status in ("DONE", "FAILED"):
            try:
                rc, stdout, _ = ssh_run_fn(
                    f"cat {expanded}/exit_code.txt 2>/dev/null", timeout,
                )
                if rc == 0:
                    exit_code = stdout.strip()
            except Exception:
                pass

        return {"status": status, "exit_code": exit_code}

    @staticmethod
    def batch_probe(
        ssh_run_fn: SshRunFn,
        tool_ids: list[str],
        tail_lines: int = 120,
        timeout: int = 20,
    ) -> list[dict]:
        """批量探测多个工具安装任务状态（单次 SSH 往返）。"""
        clean_ids = [str(t).strip() for t in tool_ids if str(t).strip()]
        if not clean_ids:
            return []

        quoted_ids = " ".join(shlex.quote(tid) for tid in clean_ids)
        tail = max(int(tail_lines or 0), 0)
        cmd = (
            f'BASE="$(eval echo {_expand_path(INSTALL_BASE)})"; '
            f'TAIL={tail}; '
            'SCREEN_LIST="$(screen -ls 2>/dev/null || true)"; '
            f'for TOOL_ID in {quoted_ids}; do '
            '  TASK_DIR="$BASE/$TOOL_ID"; '
            '  STATUS="$(cat "$TASK_DIR/status.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            '  EXIT_CODE="$(cat "$TASK_DIR/exit_code.txt" 2>/dev/null | tr -d \'\\r\\n\')"; '
            '  SESSION_ALIVE=0; '
            '  echo "$SCREEN_LIST" | grep -q "h2o_install_${TOOL_ID}" && SESSION_ALIVE=1 || true; '
            '  LOG_SIZE=0; LOG_B64=""; '
            '  if [ "$STATUS" = "" ] || [ "$STATUS" = "RUNNING" ]; then '
            '    if [ -f "$TASK_DIR/task.log" ]; then '
            '      LOG_SIZE="$(wc -c < "$TASK_DIR/task.log" 2>/dev/null | tr -d \' \\r\\n\')"; '
            '      LOG_B64="$(tail -n "$TAIL" "$TASK_DIR/task.log" 2>/dev/null | base64 | tr -d \'\\r\\n\')"; '
            '    fi; '
            '  fi; '
            '  printf "%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n" "$TOOL_ID" "$STATUS" "$EXIT_CODE" "$SESSION_ALIVE" "${LOG_SIZE:-0}" "$LOG_B64"; '
            "done"
        )

        started = time.perf_counter()
        rc, stdout, stderr = ssh_run_fn(cmd, timeout)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if rc != 0:
            raise RuntimeError(f"批量轮询失败: {stderr[:200]}")

        rows: list[dict] = []
        for raw in (stdout or "").splitlines():
            line = raw.rstrip("\r")
            if not line:
                continue
            parts = line.split("\t", 5)
            if len(parts) < 6:
                continue
            tool_id, status, exit_code, alive_str, log_size_str, log_b64 = parts
            log_text = ""
            if log_b64:
                try:
                    log_text = sanitize_log(base64.b64decode(log_b64).decode("utf-8", errors="ignore"))
                except Exception:
                    log_text = ""
            try:
                log_size = int((log_size_str or "0").strip() or "0")
            except Exception:
                log_size = 0
            rows.append(
                {
                    "tool_id": tool_id.strip(),
                    "status": (status or "").strip().upper(),
                    "exit_code": (exit_code or "").strip(),
                    "session_alive": str(alive_str).strip() == "1",
                    "log_size": max(log_size, 0),
                    "log_text": log_text,
                }
            )
        logger.debug("batch_probe tool_count=%d row_count=%d duration_ms=%d", len(clean_ids), len(rows), elapsed_ms)
        return rows

    @staticmethod
    def read_log(
        ssh_run_fn: SshRunFn,
        task_dir: str,
        tail_lines: int = 50,
        timeout: int = 10,
    ) -> str:
        """tail -n task.log，返回清理后的文本。"""
        expanded = f'"$(eval echo {_expand_path(task_dir)})"'
        try:
            rc, stdout, _ = ssh_run_fn(
                f"tail -n {tail_lines} {expanded}/task.log 2>/dev/null",
                timeout,
            )
            if rc == 0:
                return sanitize_log(stdout)
        except Exception as e:
            logger.debug("读取 task.log 失败: %s", e)
        return ""

    @staticmethod
    def is_session_alive(ssh_run_fn: SshRunFn, job_id: str, timeout: int = 10) -> bool:
        """screen -ls | grep job_id"""
        try:
            rc, stdout, _ = ssh_run_fn(
                f"screen -ls | grep -q '{job_id}'", timeout,
            )
            return rc == 0
        except Exception:
            return False

    @staticmethod
    def cleanup(ssh_run_fn: SshRunFn, task_dir: str, timeout: int = 10) -> None:
        """rm -rf task_dir"""
        expanded = f'"$(eval echo {_expand_path(task_dir)})"'
        try:
            ssh_run_fn(f"rm -rf {expanded}", timeout)
        except Exception as e:
            logger.warning("清理任务目录失败: %s", e)

    @staticmethod
    def scan_running(ssh_run_fn: SshRunFn, timeout: int = 10) -> list[dict]:
        """扫描 ~/.h2ometa/env_installs/*/status.txt，返回安装状态列表。

        Returns:
            [{"tool_id": str, "task_dir": str, "status": str}]
        """
        results = []

        try:
            rc, stdout, _ = ssh_run_fn(
                f"for d in $(eval echo {_expand_path(INSTALL_BASE)})/*/; do "
                f'  [ -f "$d/status.txt" ] && echo "$(basename $d)|$(cat $d/status.txt)"; '
                f"done 2>/dev/null",
                timeout,
            )
            if rc == 0 and stdout.strip():
                for line in stdout.strip().splitlines():
                    line = line.strip()
                    if "|" in line:
                        parts = line.split("|", 1)
                        tool_id = parts[0]
                        status = parts[1].strip()
                        results.append({
                            "tool_id": tool_id,
                            "task_dir": f"{INSTALL_BASE}/{tool_id}",
                            "status": status,
                        })
        except Exception as e:
            logger.debug("扫描安装状态失败: %s", e)

        return results
