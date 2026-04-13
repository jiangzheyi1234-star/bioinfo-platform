# core/command_builder.py
"""命令构建器 — 将 tool.yaml 描述符 + 用户参数渲染为可在远端执行的 shell 命令。

职责:
  1. 使用 Jinja2 渲染 command_template
  2. 生成通用包装脚本: 状态文件 + 心跳 + trap + 日志分离
  3. 处理 conda 环境激活
"""
import logging
from typing import Any, Dict, Optional

from jinja2 import BaseLoader, Environment, TemplateSyntaxError, UndefinedError

from core.environment.env_detector import expected_env_path
from core.environment.h2o_env_paths import H2O_CONDA_EXE, is_managed_conda_executable
from core.plugins.runtime_metadata import derive_conda_env_name

logger = logging.getLogger(__name__)

# Jinja2 环境配置: trim_blocks + lstrip_blocks 处理模板缩进
_JINJA_ENV = Environment(
    loader=BaseLoader(),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30

# conda/mamba 执行器 — 默认使用 conda，可由外部覆盖为 "mamba" 以获得更快依赖解析。
# 覆盖方式: import core.command_builder as cb; cb.CONDA_RUNNER = "mamba"
CONDA_RUNNER = "conda"

# 包装脚本模板
_WRAPPER_TEMPLATE = r"""#!/bin/bash
set -euo pipefail

TASK_DIR="{task_dir}"
JOB_ID="{job_id}"
STATUS_FILE="$TASK_DIR/status.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
LOG_FILE="$TASK_DIR/task.log"

# 创建任务目录
mkdir -p "$TASK_DIR"

# 写入运行状态
echo "RUNNING" > "$STATUS_FILE"

# 心跳进程: 每 {heartbeat_interval} 秒写入时间戳
_heartbeat() {{
    while true; do
        date +%s > "$HEARTBEAT_FILE"
        sleep {heartbeat_interval}
    done
}}
_heartbeat &
HB_PID=$!

# 清理函数: 停止心跳，写入退出码
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

# 日志重定向: stdout + stderr → task.log（同时保留终端输出）
exec > >(tee -a "$LOG_FILE") 2>&1

# ===== 用户命令开始 =====
{command}
# ===== 用户命令结束 =====
"""


class CommandBuildError(Exception):
    """命令构建失败异常。"""


class CommandBuilder:
    """命令构建器 — 渲染模板并生成包装脚本。

    用法::

        cmd = CommandBuilder.build(descriptor, params, input_paths, output_dir, sample_id)
        wrapped = CommandBuilder.wrap(cmd, job_id, task_dir)
    """

    @staticmethod
    def build(
        descriptor: Dict[str, Any],
        parameters: Dict[str, Any],
        input_paths: Dict[str, str],
        output_dir: str,
        sample_id: str,
        database_paths: Optional[Dict[str, str]] = None,
        conda_executable: str = "",
        workflow_dir: str = "",
    ) -> str:
        """渲染 command_template，生成纯命令字符串（不含包装）。

        Args:
            descriptor: 完整的 tool.yaml 字典。
            parameters: 用户参数（已与默认值合并）。
            input_paths: 输入文件路径映射，如 {"reads_1": "/path/to/r1.fq.gz"}。
            output_dir: 输出目录的远端绝对路径。
            sample_id: 样本 ID。
            database_paths: 数据库路径映射，如 {"db": "/path/to/kraken2_db"}。
            conda_executable: conda 绝对路径，优先于 CONDA_RUNNER 常量。

        Returns:
            渲染后的命令字符串。

        Raises:
            CommandBuildError: 模板渲染失败。
        """
        template_str = descriptor.get("command_template")
        if not template_str:
            raise CommandBuildError(
                f"插件 {descriptor.get('id', '?')} 缺少 command_template"
            )

        # 构建模板上下文
        context: Dict[str, Any] = {}
        context.update(parameters)
        context["sample_id"] = sample_id
        context["output_dir"] = output_dir

        # 输入文件: 支持 {reads_1} 和 {input_reads_1} 两种引用方式
        for name, path in input_paths.items():
            context[name] = path
            context[f"input_{name}"] = path

        # 数据库路径
        if database_paths:
            context.update(database_paths)

        # conda 环境名
        conda_env = derive_conda_env_name(descriptor)
        if conda_env:
            context["conda_env"] = conda_env

        # conda 执行器路径 — 对 conda_env 工具必须为自管路径，避免裸 conda 回退。
        if conda_env:
            if not is_managed_conda_executable(conda_executable):
                raise CommandBuildError("运行环境未就绪，请先在系统设置完成运行环境初始化")
            runner = conda_executable
        else:
            runner = conda_executable or CONDA_RUNNER
        if not runner:
            runner = H2O_CONDA_EXE
        context["conda_executable"] = runner

        # workflow 目录（自研脚本上传后的远端路径）
        if workflow_dir:
            context["workflow_dir"] = workflow_dir

        try:
            template = _JINJA_ENV.from_string(template_str)
            rendered = template.render(**context)
        except (TemplateSyntaxError, UndefinedError) as exc:
            raise CommandBuildError(
                f"模板渲染失败 (插件: {descriptor.get('id', '?')}): {exc}"
            ) from exc

        # 清理: 去除多余空行，保留有效命令
        lines = [line for line in rendered.splitlines() if line.strip()]
        command = "\n".join(lines)

        # conda 激活包装：仅允许自管 conda 路径，不再回退裸 conda。
        if conda_env:
            runner = conda_executable
            env_prefix = expected_env_path(conda_executable, conda_env)
            if not env_prefix:
                raise CommandBuildError("未能构建 conda 环境前缀路径")
            command = f"{runner} run -p {env_prefix} bash -c '{_escape_single_quotes(command)}'"

        logger.debug("已构建命令 (插件: %s): %s", descriptor.get("id"), command[:200])
        return command

    @staticmethod
    def merge_defaults(
        descriptor: Dict[str, Any],
        user_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将用户参数与 tool.yaml 默认值合并。

        用户参数优先；缺失的参数使用 tool.yaml 中的 default 值。

        Args:
            descriptor: 完整的 tool.yaml 字典。
            user_params: 用户提供的参数。

        Returns:
            合并后的参数字典。
        """
        merged: Dict[str, Any] = {}
        for param_def in descriptor.get("parameters", []):
            name = param_def["name"]
            if name in user_params:
                merged[name] = user_params[name]
            elif "default" in param_def:
                merged[name] = param_def["default"]
        return merged

    @staticmethod
    def resolve_output_paths(
        descriptor: Dict[str, Any],
        output_dir: str,
        sample_id: str,
    ) -> Dict[str, str]:
        """根据 tool.yaml outputs 的 pattern 解析输出文件路径。

        Args:
            descriptor: 完整的 tool.yaml 字典。
            output_dir: 输出目录远端路径。
            sample_id: 样本 ID。

        Returns:
            {output_name: resolved_path} 映射。
        """
        paths: Dict[str, str] = {}
        for output_def in descriptor.get("outputs", []):
            name = output_def["name"]
            pattern = output_def.get("pattern", "")
            resolved = pattern.replace("{output_dir}", output_dir).replace(
                "{sample_id}", sample_id
            )
            paths[name] = resolved
        return paths

    @staticmethod
    def wrap(command: str, job_id: str, task_dir: str) -> str:
        """将纯命令包装为带心跳、trap、日志的完整 bash 脚本。

        Args:
            command: 渲染后的用户命令。
            job_id: 任务标识符（用于 screen 会话名）。
            task_dir: 远端任务目录路径。

        Returns:
            完整的包装脚本字符串。
        """
        return _WRAPPER_TEMPLATE.format(
            task_dir=task_dir,
            job_id=job_id,
            heartbeat_interval=HEARTBEAT_INTERVAL,
            command=command,
        )


def _escape_single_quotes(s: str) -> str:
    """转义字符串中的单引号，用于包裹在 bash -c '...' 中。"""
    return s.replace("'", "'\\''")
