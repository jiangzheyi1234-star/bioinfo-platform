"""流水线编排器 — 线性多阶段工具执行。

接收有序的 PipelineStage 列表，依次调用 ToolEngine.execute()，
并将上一阶段的输出自动关联为下一阶段的输入。

典型用法::

    runner = PipelineRunner(tool_engine=engine, data_registry=registry)
    run_id = runner.run(
        stages=[stage_fastp, stage_hostile, stage_kraken2],
        sample_id="smp_xxx",
        initial_input_ids=["dat_raw_r1", "dat_raw_r2"],
    )
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml
from core.qt_compat import QObject, pyqtSignal

from core.data.data_registry import DataRegistry

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """流水线单阶段定义"""

    tool_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    database_paths: dict[str, str] = field(default_factory=dict)
    input_type: str = "fastq"  # 从上一步输出中匹配的数据类型
    required: bool = True


class PipelineRunner(QObject):
    """线性流水线执行器

    状态机:
      1. 执行 stage[0] → tool_engine.execute()
      2. 收到 execution_completed → 用 DataRegistry.find_compatible() 找输出
      3. 将输出作为 stage[1] 的输入 → tool_engine.execute()
      4. 重复直到所有 stage 完成或失败

    Signals:
        stage_completed(str, int, int): pipeline_run_id, stage_idx, total
        pipeline_completed(str): pipeline_run_id
        pipeline_failed(str, int, str): pipeline_run_id, stage_idx, error
    """

    stage_completed = pyqtSignal(str, int, int)   # run_id, stage_idx, total
    pipeline_completed = pyqtSignal(str)           # run_id
    pipeline_failed = pyqtSignal(str, int, str)    # run_id, stage_idx, error

    def __init__(
        self,
        tool_engine: Any,       # ToolEngine (使用 Any 避免循环导入)
        data_registry: DataRegistry,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._engine = tool_engine
        self._registry = data_registry

        # 活跃流水线: run_id -> _RunState
        self._active_runs: dict[str, "_RunState"] = {}

        # 连接 ToolEngine 信号
        self._engine.execution_completed.connect(self._on_execution_completed)
        self._engine.execution_failed.connect(self._on_execution_failed)

    def run(
        self,
        stages: list[PipelineStage],
        sample_id: str,
        initial_input_ids: list[str],
    ) -> str:
        """启动流水线

        Args:
            stages: 有序阶段列表
            sample_id: 样本 ID
            initial_input_ids: 初始输入数据 ID 列表（如 raw FASTQ）

        Returns:
            pipeline_run_id

        Raises:
            ValueError: 参数校验失败
        """
        if not stages:
            raise ValueError("流水线至少需要一个阶段")
        if not sample_id:
            raise ValueError("sample_id 不能为空")
        if not initial_input_ids:
            raise ValueError("初始输入数据不能为空")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        state = _RunState(
            run_id=run_id,
            stages=stages,
            sample_id=sample_id,
            current_stage=0,
            current_input_ids=list(initial_input_ids),
        )
        self._active_runs[run_id] = state

        logger.info(
            "流水线启动: %s (%d 阶段, sample=%s)",
            run_id, len(stages), sample_id,
        )

        # 启动第一阶段
        self._execute_stage(state)
        return run_id

    def get_active_runs(self) -> list[str]:
        """获取所有活跃流水线 run_id"""
        return list(self._active_runs.keys())

    # ── 内部方法 ──────────────────────────────────────────────

    def _execute_stage(self, state: "_RunState") -> None:
        """执行当前阶段"""
        stage = state.stages[state.current_stage]

        logger.info(
            "流水线 %s: 执行阶段 %d/%d (%s)",
            state.run_id, state.current_stage + 1,
            len(state.stages), stage.tool_id,
        )

        try:
            execution_id = self._engine.execute(
                tool_id=stage.tool_id,
                input_data_ids=state.current_input_ids,
                parameters=stage.parameters,
                sample_id=state.sample_id,
                triggered_by="pipeline",
                database_paths=stage.database_paths or None,
            )

            # 记录 execution_id → run_id 映射
            state.execution_to_stage[execution_id] = state.current_stage
            state.current_execution_id = execution_id

        except Exception as e:
            logger.exception(
                "流水线 %s: 阶段 %d 执行失败",
                state.run_id, state.current_stage,
            )
            self._fail(state, str(e))

    def _on_execution_completed(self, execution_id: str) -> None:
        """ToolEngine 完成信号回调"""
        state = self._find_state_by_execution(execution_id)
        if state is None:
            return  # 不属于流水线的执行

        stage_idx = state.execution_to_stage[execution_id]

        logger.info(
            "流水线 %s: 阶段 %d 完成 (execution=%s)",
            state.run_id, stage_idx + 1, execution_id,
        )

        self.stage_completed.emit(state.run_id, stage_idx, len(state.stages))

        # 检查是否所有阶段都已完成
        if stage_idx + 1 >= len(state.stages):
            logger.info("流水线 %s: 全部完成", state.run_id)
            self._active_runs.pop(state.run_id, None)
            self.pipeline_completed.emit(state.run_id)
            return

        # 查找本阶段输出作为下一阶段输入
        next_stage = state.stages[stage_idx + 1]
        compatible = self._registry.find_compatible(
            state.sample_id, next_stage.input_type,
        )

        if not compatible:
            self._fail(
                state,
                f"阶段 {stage_idx + 1} 输出中无 {next_stage.input_type} 类型数据",
            )
            return

        # 使用最新的兼容数据作为下一阶段的输入
        state.current_input_ids = [compatible[0].data_id]
        state.current_stage = stage_idx + 1

        # 执行下一阶段
        self._execute_stage(state)

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        """ToolEngine 失败信号回调"""
        state = self._find_state_by_execution(execution_id)
        if state is None:
            return

        logger.error(
            "流水线 %s: 阶段 %d 失败: %s",
            state.run_id, state.current_stage, error,
        )
        self._fail(state, error)

    def _fail(self, state: "_RunState", error: str) -> None:
        """标记流水线失败"""
        self._active_runs.pop(state.run_id, None)
        self.pipeline_failed.emit(state.run_id, state.current_stage, error)

    def _find_state_by_execution(
        self, execution_id: str,
    ) -> Optional["_RunState"]:
        """通过 execution_id 查找所属的流水线状态"""
        for state in self._active_runs.values():
            if execution_id in state.execution_to_stage:
                return state
        return None

    # ── 从 YAML 加载 ─────────────────────────────────────────

    @classmethod
    def load_stages_from_yaml(
        cls,
        yaml_path: str,
        path_name: str,
        user_params: Optional[dict[str, dict[str, Any]]] = None,
        user_db_paths: Optional[dict[str, dict[str, str]]] = None,
    ) -> list[PipelineStage]:
        """从 analysis_paths.yaml 加载流水线阶段定义

        Args:
            yaml_path: YAML 文件路径
            path_name: 流水线路径名称 (如 "read_based")
            user_params: 用户参数覆盖 {tool_id: {param: value}}
            user_db_paths: 用户数据库路径 {tool_id: {db_name: path}}

        Returns:
            PipelineStage 列表
        """
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        paths = data.get("paths", {})
        if path_name not in paths:
            raise ValueError(f"流水线路径不存在: {path_name}")

        path_def = paths[path_name]
        stages: list[PipelineStage] = []
        user_params = user_params or {}
        user_db_paths = user_db_paths or {}

        for stage_def in path_def.get("stages", []):
            tool_id = stage_def["tool_id"]
            stages.append(PipelineStage(
                tool_id=tool_id,
                parameters=user_params.get(tool_id, {}),
                database_paths=user_db_paths.get(tool_id, {}),
                input_type=stage_def.get("input_type", "fastq"),
                required=stage_def.get("required", True),
            ))

        return stages


@dataclass
class _RunState:
    """流水线运行状态（内部使用）"""

    run_id: str
    stages: list[PipelineStage]
    sample_id: str
    current_stage: int
    current_input_ids: list[str]
    current_execution_id: str = ""
    execution_to_stage: dict[str, int] = field(default_factory=dict)
