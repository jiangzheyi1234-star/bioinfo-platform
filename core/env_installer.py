"""通过 screen 在远端后台安装 conda 环境。

纯 Core 层模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现（与 env_detector 一致风格）。
使用 screen -dmS 模式，复用 status.txt / heartbeat.txt / task.log 机制，
确保 SSH 断线或软件关闭后安装不中断。
"""

import logging
import re
import uuid

from core.env_detector import (
    SshRunFn,
    pin_create_env_to_conda_root,
    rewrite_install_cmd,
)

logger = logging.getLogger(__name__)

INSTALL_BASE = "~/.h2ometa/env_installs"

# ANSI 转义码正则（与 linux_settings_card._ANSI_RE 一致）
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")

# conda spinner 行正则（防御层，正常情况下 TERM=dumb 已消除 spinner）
# 匹配：纯 spinner 字符行，或以 spinner 字符结尾的 "状态描述: X" 行
_SPINNER_RE = re.compile(r"^[\s\-\\|/.:]+$")
_SPINNER_TAIL_RE = re.compile(r"^.+:\s*[\\|/\-]\s*$")

# 包装脚本模板（比 command_builder._WRAPPER_TEMPLATE 更简单，不需要 JOB_ID 变量）
#
# 关键环境变量：
#   TERM=dumb          — 禁止所有终端特性（光标移动、颜色），所有程序生效
#   CONDA_QUIET=1      — conda 不显示 spinner / 进度条，仍输出包列表和解析信息
#   PIP_PROGRESS_BAR=off — pip 不显示进度条
#
# 不用 tee（screen 后台无人看终端），直接写 LOG_FILE 避免 pipe 导致 \r 丢失。
_INSTALL_WRAPPER = r"""#!/bin/bash
set -euo pipefail

export TERM=dumb
export CONDA_QUIET=1
export PIP_PROGRESS_BAR=off

TASK_DIR="{task_dir}"
STATUS_FILE="$TASK_DIR/status.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
LOG_FILE="$TASK_DIR/task.log"

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

# ===== install command =====
{command}
# ===== install end =====
"""


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
        timeout: int = 15,
    ) -> dict:
        """启动后台安装。

        1. rewrite_install_cmd() 替换 conda 路径
        2. 生成包装脚本（status.txt + heartbeat + task.log + trap）
        3. 写到远端 ~/.h2ometa/env_installs/{tool_id}/install.sh
        4. screen -dmS h2o_install_{tool_id} bash install.sh

        Returns:
            {"job_id": str, "task_dir": str}
        """
        resolved_cmd = rewrite_install_cmd(install_cmd, conda_executable)
        resolved_cmd = pin_create_env_to_conda_root(resolved_cmd, conda_executable)

        task_dir_raw = f"{INSTALL_BASE}/{tool_id}"
        task_dir_expanded = f'"$(eval echo {_expand_path(task_dir_raw)})"'

        # 创建任务目录
        ssh_run_fn(f"mkdir -p {task_dir_expanded}", timeout)

        # 生成包装脚本
        # task_dir 在脚本内部用 eval echo 展开
        script = _INSTALL_WRAPPER.format(
            task_dir=f"$(eval echo {_expand_path(task_dir_raw)})",
            command=resolved_cmd,
        )

        # 写脚本到远端（用 heredoc 避免转义问题）
        script_path = f"{task_dir_raw}/install.sh"
        script_path_expanded = f'"$(eval echo {_expand_path(script_path)})"'

        # 使用 base64 编码避免 heredoc 中的特殊字符问题
        import base64
        encoded = base64.b64encode(script.encode()).decode()
        write_cmd = f"echo '{encoded}' | base64 -d > {script_path_expanded}"
        rc, _, stderr = ssh_run_fn(write_cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"写入安装脚本失败: {stderr[:200]}")

        # 启动 screen 会话
        job_id = f"h2o_install_{tool_id}"
        # 先杀掉可能存在的旧会话
        ssh_run_fn(f"screen -S {job_id} -X quit 2>/dev/null || true", timeout)
        screen_cmd = f"screen -dmS {job_id} bash {script_path_expanded}"
        rc, _, stderr = ssh_run_fn(screen_cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"启动 screen 会话失败: {stderr[:200]}")

        logger.info("后台安装已启动: job_id=%s, task_dir=%s", job_id, task_dir_raw)
        return {"job_id": job_id, "task_dir": task_dir_raw}

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
                return _sanitize_log(stdout)
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
        base_expanded = f'"$(eval echo {_expand_path(INSTALL_BASE)})"'
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


def _sanitize_log(text: str) -> str:
    """清理日志输出：去 ANSI 转义码，处理 \\r 覆写，过滤 spinner 行。"""
    text = _ANSI_RE.sub("", text)
    lines = []
    seen = set()  # 去重（spinner 重复行）
    # 用 \n 分割（不用 splitlines，因为它会把 \r 也当分隔符）
    for line in text.split("\n"):
        # \r 覆写：保留最后一个 \r 后的内容
        if "\r" in line:
            parts = line.split("\r")
            for p in reversed(parts):
                if p.strip():
                    line = p
                    break
            else:
                continue
        stripped = line.strip()
        if not stripped:
            continue
        # 过滤纯 spinner 字符行：  "- " "\ " "| " "/ "
        if _SPINNER_RE.match(stripped):
            continue
        # 过滤 "Collecting package metadata (repodata.json): \" 之类的 spinner 尾行
        if _SPINNER_TAIL_RE.match(stripped):
            continue
        # 去重：相同内容只保留一次（连续 spinner 残留）
        if stripped in seen:
            continue
        seen.add(stripped)
        lines.append(line)
    return "\n".join(lines)
