"""工具执行引擎 — Phase 1/2 核心模块。

统一执行入口：UI 直接点击、向导引导、未来 Agent 调用，
都通过同一个 execute() 方法提交分析任务。

Phase 2 变更:
  - 统一使用外部 Jinja2 CommandBuilder（替换内部 str.format 版本）
  - execute() 新增 database_paths 参数
  - on_job_completed() 添加远程文件存在性验证（Risk 1 缓解）

依赖关系:
  - PluginRegistry: 获取工具描述符
  - DataRegistry: 数据血缘注册和查询
  - ProjectManager: 当前项目信息
  - SSHService: 远端命令执行
  - JobQueue: 并发控制
  - CommandBuilder: Jinja2 命令渲染 + 包装脚本
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from core.command_builder import CommandBuilder, CommandBuildError
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
    is_final_version: int = 0  # 标记为最终版本（用于导出和论文）
    archived_at: Optional[float] = None  # 文件已清理的时间戳


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
        context_register_fn=None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._ssh = ssh_service
        self._plugins = plugin_registry
        self._projects = project_manager
        self._registry = data_registry
        self._queue = job_queue
        # 可选回调：fn(execution_id, command, descriptor, sample_id, output_dir, task_dir)
        # 由 ServiceLocator 注入，用于在 job_queue.job_started 触发前注册执行上下文
        self._context_register_fn = context_register_fn

    # ── 公开 API ──────────────────────────────────────────

    def execute(
        self,
        tool_id: str,
        input_data_ids: list[str],
        parameters: dict[str, Any],
        sample_id: str,
        triggered_by: str = "manual",
        database_paths: Optional[dict[str, str]] = None,
    ) -> str:
        """提交工具执行

        Args:
            tool_id: 工具标识 (如 "fastp", "kraken2")
            input_data_ids: 输入数据项 ID 列表
            parameters: 用户设置的参数
            sample_id: 关联的样本 ID
            triggered_by: 触发来源 (manual / wizard / pipeline / agent)
            database_paths: 数据库路径映射，如 {"db": "/path/to/kraken2_db"}

        Returns:
            新创建的 execution_id

        Raises:
            ValueError: 没有打开的项目或参数校验失败
            CommandBuildError: 命令模板渲染失败
        """
        # 1. 检查当前项目
        project = self._projects.current_project
        if project is None:
            raise ValueError("请先选择或创建项目")

        # 2. 加载工具描述符
        descriptor = self._plugins.get_descriptor(tool_id)

        # 3. 合并参数（用户参数覆盖默认值）
        merged_params = self._merge_defaults(descriptor, parameters)

        # 4. 生成 execution_id（需要在构建输出目录前生成）
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        # 5. 获取输入文件路径
        input_paths = self._resolve_inputs(descriptor, input_data_ids)

        # 6. 构建输出目录（包含 execution_id 以支持多版本）
        output_dir = f"{project.remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"

        # 7. 解析输出路径（模板中可能引用输出变量名如 clean_1、report_html）
        output_paths = CommandBuilder.resolve_output_paths(
            descriptor, output_dir, sample_id,
        )
        all_paths = {**input_paths, **output_paths}

        # 8. 构建命令（使用 Jinja2 模板）
        command = CommandBuilder.build(
            descriptor=descriptor,
            parameters=merged_params,
            input_paths=all_paths,
            output_dir=output_dir,
            sample_id=sample_id,
            database_paths=database_paths,
        )

        # 9. 创建 ExecutionRecord
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

        # 9. 写入数据库
        self._save_record(record)

        # 10. 记录输入关系 (execution_io)
        for data_id in input_data_ids:
            self._registry.add_execution_io(execution_id, data_id, "input")

        # 11. 创建远端输出目录
        self._ssh.run(f"mkdir -p {output_dir}", timeout=15)

        # 11.5 注册执行上下文（供 ServiceLocator._on_dispatch 取用）
        # task_dir 即 output_dir，用于存放 run.sh / status.txt / heartbeat.txt
        task_dir = output_dir
        if self._context_register_fn is not None:
            self._context_register_fn(
                execution_id=execution_id,
                command=command,
                descriptor=descriptor,
                sample_id=sample_id,
                output_dir=output_dir,
                task_dir=task_dir,
            )

        # 12. 提交到 JobQueue
        self._queue.submit(
            execution_id=execution_id,
            command=command,
            metadata={"tool_id": tool_id, "sample_id": sample_id},
        )

        # 13. 更新状态为 running 并发信号
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

        Risk 1 缓解: 注册输出前通过 SSH 检查远程文件是否存在，
        避免 hostile 等工具实际输出文件名与 pattern 不一致的问题。

        Args:
            execution_id: 执行 ID
            descriptor: 工具描述符
            sample_id: 样本 ID
            output_dir: 远端输出目录
        """
        try:
            # 使用 resolve_output_paths 统一解析输出路径
            resolved_paths = CommandBuilder.resolve_output_paths(
                descriptor, output_dir, sample_id,
            )

            for output_def in descriptor.get("outputs", []):
                name = output_def["name"]
                file_path = resolved_paths.get(name, "")
                data_type = output_def.get("type", "unknown")
                tier = output_def.get("tier", "result")

                if not file_path:
                    logger.warning(
                        "输出 %s 无法解析路径，跳过注册 (execution=%s)",
                        name, execution_id,
                    )
                    continue

                # Risk 1 缓解: 验证远程文件是否存在
                try:
                    rc, _, _ = self._ssh.run(
                        f"test -f {file_path}", timeout=10,
                    )
                    if rc != 0:
                        logger.warning(
                            "输出文件不存在，跳过注册: %s (execution=%s)",
                            file_path, execution_id,
                        )
                        continue
                except Exception:
                    # SSH 检查失败时仍然注册（保守策略）
                    logger.debug(
                        "无法验证输出文件存在性，继续注册: %s", file_path,
                    )

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
            "retry_count, retry_of, remote_job_id, is_final_version, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                record.is_final_version,
                record.archived_at,
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

        # 处理新字段（向后兼容）
        try:
            is_final_version = row["is_final_version"]
        except (KeyError, IndexError):
            is_final_version = 0

        try:
            archived_at = row["archived_at"]
        except (KeyError, IndexError):
            archived_at = None

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
            is_final_version=is_final_version,
            archived_at=archived_at,
        )
