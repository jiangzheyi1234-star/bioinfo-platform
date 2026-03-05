"""工具执行引擎 — Phase 1 核心模块。

统一执行入口：UI 直接点击、向导引导、未来 Agent 调用，
都通过同一个 execute() 方法提交分析任务。

依赖关系:
  - PluginRegistry: 获取工具描述符
  - DataRegistry: 数据血缘注册和查询
  - ProjectManager: 当前项目信息
  - SSHService: 远端命令执行
  - JobQueue: 并发控制
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from core.data_registry import DataRegistry

logger = logging.getLogger(__name__)


# ── 协议定义（用于解耦和测试） ─────────────────────────────


class PluginRegistryProtocol(Protocol):
    """PluginRegistry 的最小接口"""

    def get_descriptor(self, tool_id: str) -> dict[str, Any]: ...


class ProjectManagerProtocol(Protocol):
    """ProjectManager 的最小接口"""

    @property
    def current_project(self) -> Any: ...

    @property
    def db(self) -> Any: ...


class SSHServiceProtocol(Protocol):
    """SSHService 的最小接口"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...


class JobQueueProtocol(Protocol):
    """JobQueue 的最小接口"""

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Any = None,
        metadata: Any = None,
    ) -> str: ...


# ── 数据类 ────────────────────────────────────────────────


@dataclass
class ExecutionRecord:
    """执行记录数据类"""

    execution_id: str
    sample_id: str
    tool_id: str
    tool_version: str
    parameters: dict[str, Any]
    status: str              # pending / running / completed / failed / retrying
    triggered_by: str        # manual / wizard / pipeline / agent
    created_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    retry_of: Optional[str] = None
    remote_job_id: Optional[str] = None


# ── 命令构建器 ────────────────────────────────────────────


class CommandBuilder:
    """命令行构建器 — 从 tool.yaml 模板和参数生成可执行命令"""

    @staticmethod
    def build(
        descriptor: dict[str, Any],
        params: dict[str, Any],
        input_paths: dict[str, str],
        sample_id: str,
        output_dir: str,
    ) -> str:
        """构建完整命令字符串

        Args:
            descriptor: 工具完整 YAML 描述符
            params: 合并后的参数（用户参数 + 默认值）
            input_paths: 输入名称 -> 文件路径映射
            sample_id: 样本 ID
            output_dir: 输出目录

        Returns:
            渲染完成的命令字符串
        """
        template = descriptor["command_template"]

        # 构建模板上下文
        context: dict[str, Any] = {**params}
        context["sample_id"] = sample_id
        context["output_dir"] = output_dir

        # 填充输入文件路径
        for inp_def in descriptor.get("inputs", []):
            inp_name = inp_def["name"]
            if inp_name in input_paths:
                context[inp_name] = input_paths[inp_name]

        # conda 环境名
        conda_env = descriptor.get("conda_env")
        if conda_env:
            context["conda_env"] = conda_env

        # 渲染模板（使用 str.format）
        try:
            cmd = template.format(**context)
        except KeyError as e:
            raise ValueError(f"命令模板缺少变量: {e}") from e

        return cmd.strip()


# ── 工具引擎 ──────────────────────────────────────────────


class ToolEngine(QObject):
    """统一工具执行引擎

    完整执行流程:
    1. 加载工具描述符 (PluginRegistry)
    2. 获取输入数据路径 (DataRegistry)
    3. 合并参数（用户参数 + 默认值）
    4. 构建命令 (CommandBuilder)
    5. 创建 ExecutionRecord 并写入 SQLite
    6. 记录 execution_io 输入关系
    7. 创建远端输出目录
    8. 提交到 JobQueue 排队执行

    Signals:
        execution_started(str): 执行已提交，参数为 execution_id
        execution_completed(str): 执行完成，参数为 execution_id
        execution_failed(str, str): 执行失败，参数为 execution_id 和错误信息
    """

    execution_started = pyqtSignal(str)      # execution_id
    execution_completed = pyqtSignal(str)     # execution_id
    execution_failed = pyqtSignal(str, str)   # execution_id, error

    def __init__(
        self,
        ssh_service: SSHServiceProtocol,
        plugin_registry: PluginRegistryProtocol,
        project_manager: ProjectManagerProtocol,
        data_registry: DataRegistry,
        job_queue: JobQueueProtocol,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._ssh = ssh_service
        self._plugins = plugin_registry
        self._projects = project_manager
        self._registry = data_registry
        self._queue = job_queue

    # ── 公开 API ──────────────────────────────────────────

    def execute(
        self,
        tool_id: str,
        input_data_ids: list[str],
        parameters: dict[str, Any],
        sample_id: str,
        triggered_by: str = "manual",
    ) -> str:
        """提交工具执行

        Args:
            tool_id: 工具标识 (如 "fastp", "kraken2")
            input_data_ids: 输入数据项 ID 列表
            parameters: 用户设置的参数
            sample_id: 关联的样本 ID
            triggered_by: 触发来源 (manual / wizard / pipeline / agent)

        Returns:
            新创建的 execution_id

        Raises:
            ValueError: 没有打开的项目或参数校验失败
        """
        # 1. 检查当前项目
        project = self._projects.current_project
        if project is None:
            raise ValueError("请先选择或创建项目")

        # 2. 加载工具描述符
        descriptor = self._plugins.get_descriptor(tool_id)

        # 3. 合并参数（用户参数覆盖默认值）
        merged_params = self._merge_defaults(descriptor, parameters)

        # 4. 获取输入文件路径
        input_paths = self._resolve_inputs(descriptor, input_data_ids)

        # 5. 构建输出目录
        output_dir = f"{project.remote_base}/intermediate/{sample_id}/{tool_id}"

        # 6. 构建命令
        command = CommandBuilder.build(
            descriptor, merged_params, input_paths, sample_id, output_dir,
        )

        # 7. 创建 ExecutionRecord
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"
        record = ExecutionRecord(
            execution_id=execution_id,
            sample_id=sample_id,
            tool_id=tool_id,
            tool_version=descriptor.get("version", "unknown"),
            parameters=merged_params,
            status="pending",
            triggered_by=triggered_by,
            created_at=time.time(),
        )

        # 8. 写入数据库
        self._save_record(record)

        # 9. 记录输入关系 (execution_io)
        for data_id in input_data_ids:
            self._registry.add_execution_io(execution_id, data_id, "input")

        # 10. 创建远端输出目录
        self._ssh.run(f"mkdir -p {output_dir}", timeout=15)

        # 11. 提交到 JobQueue
        self._queue.submit(
            execution_id=execution_id,
            command=command,
            metadata={"tool_id": tool_id, "sample_id": sample_id},
        )

        # 12. 更新状态为 running 并发信号
        self._update_status(execution_id, "running")
        self.execution_started.emit(execution_id)

        logger.info(
            "执行已提交: %s (tool=%s, sample=%s, triggered_by=%s)",
            execution_id, tool_id, sample_id, triggered_by,
        )
        return execution_id

    def on_job_completed(
        self,
        execution_id: str,
        descriptor: dict[str, Any],
        sample_id: str,
        output_dir: str,
    ) -> None:
        """任务完成回调 — 注册输出到 DataRegistry 并更新状态

        Args:
            execution_id: 执行 ID
            descriptor: 工具描述符
            sample_id: 样本 ID
            output_dir: 远端输出目录
        """
        try:
            # 注册所有声明的输出文件
            for output_def in descriptor.get("outputs", []):
                pattern = output_def.get("pattern", "")
                file_path = f"{output_dir}/{pattern.format(sample_id=sample_id)}"
                data_type = output_def.get("type", "unknown")
                tier = output_def.get("tier", "result")

                self._registry.register_output(
                    execution_id=execution_id,
                    file_path=file_path,
                    data_type=data_type,
                    sample_id=sample_id,
                    tier=tier,
                )

            # 更新执行状态
            self._update_status(execution_id, "completed")
            self._update_completed_at(execution_id)

            logger.info("执行完成: %s", execution_id)
            self.execution_completed.emit(execution_id)

        except Exception as e:
            logger.exception("处理完成回调时出错: %s", execution_id)
            self.on_job_failed(execution_id, str(e))

    def on_job_failed(self, execution_id: str, error: str) -> None:
        """任务失败回调 — 更新状态和错误信息

        Args:
            execution_id: 执行 ID
            error: 错误描述
        """
        self._update_status(execution_id, "failed")
        self._update_error(execution_id, error)

        logger.error("执行失败: %s — %s", execution_id, error)
        self.execution_failed.emit(execution_id, error)

    def get_record(self, execution_id: str) -> Optional[ExecutionRecord]:
        """获取执行记录

        Args:
            execution_id: 执行 ID

        Returns:
            执行记录，不存在时返回 None
        """
        db = self._projects.db
        row = db.execute(
            "SELECT * FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    # ── 内部方法 ──────────────────────────────────────────

    @staticmethod
    def _merge_defaults(
        descriptor: dict[str, Any],
        user_params: dict[str, Any],
    ) -> dict[str, Any]:
        """合并用户参数和默认值

        默认值来自 descriptor['parameters'] 中各参数的 default 字段。
        用户参数优先级更高。
        """
        merged: dict[str, Any] = {}
        for param_def in descriptor.get("parameters", []):
            name = param_def["name"]
            if name in user_params:
                merged[name] = user_params[name]
            elif "default" in param_def:
                merged[name] = param_def["default"]
        # 保留用户传入的、descriptor 中未声明的额外参数
        for k, v in user_params.items():
            if k not in merged:
                merged[k] = v
        return merged

    def _resolve_inputs(
        self,
        descriptor: dict[str, Any],
        input_data_ids: list[str],
    ) -> dict[str, str]:
        """将 input_data_ids 映射为 {输入名称: 文件路径}

        按 descriptor['inputs'] 的顺序，依次对应 input_data_ids。

        Raises:
            ValueError: 必需的输入数据缺失
        """
        inputs_def = descriptor.get("inputs", [])
        paths: dict[str, str] = {}

        for i, inp_def in enumerate(inputs_def):
            inp_name = inp_def["name"]
            required = inp_def.get("required", True)

            if i < len(input_data_ids):
                item = self._registry.get_item(input_data_ids[i])
                if item is None:
                    raise ValueError(f"输入数据不存在: {input_data_ids[i]}")
                paths[inp_name] = item.file_path
            elif required:
                raise ValueError(f"缺少必需的输入: {inp_name}")

        return paths

    def _save_record(self, record: ExecutionRecord) -> None:
        """将执行记录写入 SQLite"""
        db = self._projects.db
        db.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, tool_version, parameters, "
            "status, triggered_by, created_at, completed_at, error, "
            "retry_count, retry_of, remote_job_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.execution_id,
                record.sample_id,
                record.tool_id,
                record.tool_version,
                json.dumps(record.parameters, ensure_ascii=False),
                record.status,
                record.triggered_by,
                record.created_at,
                record.completed_at,
                record.error,
                record.retry_count,
                record.retry_of,
                record.remote_job_id,
            ),
        )
        db.commit()

    def _update_status(self, execution_id: str, status: str) -> None:
        """更新执行状态"""
        db = self._projects.db
        db.execute(
            "UPDATE executions SET status = ? WHERE execution_id = ?",
            (status, execution_id),
        )
        db.commit()

    def _update_completed_at(self, execution_id: str) -> None:
        """更新完成时间"""
        db = self._projects.db
        db.execute(
            "UPDATE executions SET completed_at = ? WHERE execution_id = ?",
            (time.time(), execution_id),
        )
        db.commit()

    def _update_error(self, execution_id: str, error: str) -> None:
        """更新错误信息"""
        db = self._projects.db
        db.execute(
            "UPDATE executions SET error = ? WHERE execution_id = ?",
            (error, execution_id),
        )
        db.commit()

    @staticmethod
    def _row_to_record(row) -> ExecutionRecord:
        """将数据库行转换为 ExecutionRecord"""
        params_str = row["parameters"]
        parameters = json.loads(params_str) if params_str else {}
        return ExecutionRecord(
            execution_id=row["execution_id"],
            sample_id=row["sample_id"],
            tool_id=row["tool_id"],
            tool_version=row["tool_version"],
            parameters=parameters,
            status=row["status"],
            triggered_by=row["triggered_by"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            retry_count=row["retry_count"],
            retry_of=row["retry_of"],
            remote_job_id=row["remote_job_id"],
        )
