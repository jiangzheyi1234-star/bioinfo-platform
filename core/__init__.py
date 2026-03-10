"""Core 模块 — H2OMeta 核心功能

包含：
- 项目管理
- 数据注册
- 工具执行
- 流水线编排
- 执行清理
- SSH 服务
- 环境检测
- 环境安装
"""

from core.execution_cleaner import ExecutionCleaner, ExecutionDiskUsage
from core import env_detector
from core import env_installer

__all__ = [
    "ExecutionCleaner",
    "ExecutionDiskUsage",
    "env_detector",
    "env_installer",
]
