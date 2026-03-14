"""环境批量检测器 — conda 环境批量检测。

职责：
  - 批量检测工具 conda 环境是否就绪
  - 环境路径解析与匹配

此模块无 Qt 依赖，可独立测试。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from core.environment import env_detector

if TYPE_CHECKING:
    from paramiko import SSHClient

logger = logging.getLogger(__name__)


@dataclass
class ToolCheckResult:
    tool_id: str
    env_name: str
    ok: bool


def check_all_envs(
    ssh_run_fn: Callable[[str, int], tuple[int, str, str]],
    tools: list[dict],
    conda_executable: str = "",
) -> tuple[list[ToolCheckResult], list[str]]:
    """批量检测工具 conda 环境是否就绪。

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        tools: [{"id": ..., "conda_env": ...}, ...]
        conda_executable: 检测到的 conda 绝对路径

    Returns:
        tuple[list[ToolCheckResult], list[str]]: (检测结果列表, conda环境路径列表)
    """
    results: list[ToolCheckResult] = []
    conda_envs: list[str] = []

    conda_exe = conda_executable or "conda"
    cmd = f"{conda_exe} env list --json"

    try:
        rc, stdout, stderr = ssh_run_fn(cmd, 30)
        exit_code = rc

        logger.debug("conda cmd=%r exit=%d out_len=%d", cmd, exit_code, len(stdout))

        if exit_code == 0 and stdout:
            json_start = stdout.find("{")
            if json_start >= 0:
                data = json.loads(stdout[json_start:])
                conda_envs = data.get("envs", [])
                logger.info("conda env list 成功，共 %d 个环境", len(conda_envs))

    except json.JSONDecodeError as e:
        logger.warning("JSON 解析失败 cmd=%r: %s", cmd, e)
    except Exception as e:
        logger.debug("cmd=%r 失败: %s", cmd, e)

    if not conda_envs:
        logger.warning("所有候选命令均未取到 conda 环境列表")

    conda_root = env_detector.infer_conda_root(conda_exe)
    logger.debug("conda 根目录（原始）：%s", conda_root or "(未知)")

    if conda_root and "~" in conda_root:
        try:
            _, stdout, _ = ssh_run_fn(f"eval echo {conda_root}", 10)
            expanded = stdout.strip()
            if expanded and not expanded.startswith("~"):
                conda_root = expanded
                logger.debug("conda 根目录（展开后）：%s", conda_root)
        except Exception as e:
            logger.debug("展开 ~ 失败: %s", e)

    if conda_root:
        filtered_envs: list[str] = []
        for path in conda_envs:
            p = path.rstrip("/")
            if p == conda_root or p.startswith(conda_root + "/"):
                filtered_envs.append(p)
        conda_envs = filtered_envs
        if filtered_envs:
            logger.debug("过滤后保留 %d 个环境（仅当前 conda 根目录）", len(conda_envs))
        else:
            logger.warning("过滤后没有环境，按严格模式处理为 0 个环境")

    env_paths_set = {p.rstrip("/") for p in conda_envs}
    env_names_set: set[str] = set()
    for path in conda_envs:
        name = path.rstrip("/").split("/")[-1]
        env_names_set.add(name)

    logger.debug("已知环境名: %s", env_names_set)

    for tool in tools:
        tool_id = tool.get("id", "")
        conda_env = tool.get("conda_env", "")

        if not conda_env:
            results.append(ToolCheckResult(tool_id=tool_id, env_name="(系统路径)", ok=True))
            continue

        if conda_root:
            expected_path = f"{conda_root}/envs/{conda_env}"
        else:
            expected_path = ""

        if expected_path:
            ok = expected_path in env_paths_set
            if not ok and conda_env in env_names_set:
                logger.warning(
                    "tool=%s conda_env=%s 命中同名环境但路径不匹配，expected=%s",
                    tool_id, conda_env, expected_path,
                )
        else:
            ok = conda_env in env_names_set
        logger.debug("tool=%s conda_env=%s expected=%s ok=%s", tool_id, conda_env, expected_path, ok)
        results.append(ToolCheckResult(tool_id=tool_id, env_name=conda_env, ok=ok))

    return results, conda_envs


def get_existing_env_paths(
    ssh_run_fn: Callable[[str, int], tuple[int, str, str]],
    conda_executable: str,
) -> set[str]:
    """获取远端所有已存在的 conda 环境路径集合。"""
    if not conda_executable:
        return set()

    try:
        cmd = f"{conda_executable} env list --json"
        rc, stdout, stderr = ssh_run_fn(cmd, 30)
        exit_code = rc

        if exit_code == 0 and stdout:
            json_start = stdout.find("{")
            if json_start >= 0:
                data = json.loads(stdout[json_start:])
                return {p.rstrip("/") for p in data.get("envs", [])}
    except Exception as e:
        logger.debug("获取环境列表失败: %s", e)

    return set()