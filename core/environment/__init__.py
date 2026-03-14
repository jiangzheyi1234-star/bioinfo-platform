"""环境管理模块 — conda 检测/安装、容器检测。"""

from core.environment.env_batch_checker import ToolCheckResult, check_all_envs, get_existing_env_paths

__all__ = ["ToolCheckResult", "check_all_envs", "get_existing_env_paths"]