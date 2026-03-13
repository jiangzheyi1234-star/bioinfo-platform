"""Core 模块 — H2OMeta 核心功能

子包结构:
  - execution/: 执行链 (ToolEngine, JobDispatcher, CommandBuilder...)
  - data/: 数据管理 (DataRegistry, ProjectManager, DataImporter...)
  - remote/: SSH 连接 (SSHService, SSHReconnector, StorageManager)
  - pipeline/: 流程编排 (PipelineRunner, PipelineReconstructor, ProjectExporter)
  - environment/: 环境管理 (env_detector, env_installer, ContainerDetector)
  - plugins/: 插件系统 (PluginRegistry, TaskManager)

使用示例:
    from core.execution.tool_engine import ToolEngine
    from core.data.data_registry import DataRegistry
    from core.remote.ssh_service import SSHService
"""

from core.data.execution_cleaner import ExecutionCleaner, ExecutionDiskUsage
from core import environment

__all__ = [
    "ExecutionCleaner",
    "ExecutionDiskUsage",
    "environment",
]