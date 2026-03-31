"""Execution orchestration seam extracted from ToolBridgeService."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def execute_tool(self, tool_id: str, params: dict):
    from core.execution.tool_bridge_service import ExecutionResult

    try:
        if self._service_locator is None:
            return ExecutionResult(status="error", message="服务未就绪")

        pm = self._get_project_manager()
        if pm is not None and pm.current_project is None:
            self._ensure_default_project(pm)

        tool_engine = self._get_tool_engine()
        if tool_engine is None and pm is not None and pm.current_project is not None:
            sl = self._service_locator
            if hasattr(sl, "_rebuild_registry_and_engine"):
                sl._rebuild_registry_and_engine()
            tool_engine = self._get_tool_engine()

        if tool_engine is None:
            return ExecutionResult(status="error", message="ToolEngine 未初始化，请先连接 SSH 或创建项目")

        pm = self._get_project_manager()
        if pm is None or pm.current_project is None:
            return ExecutionResult(status="no_project", message="请先选择或创建项目")

        if hasattr(pm, "backup_current_project"):
            try:
                pm.backup_current_project(reason="before_run")
            except Exception:
                logger.exception("Failed to backup project state before running %s", tool_id)

        descriptor = self._plugin_registry.get_descriptor(tool_id)
        sample_id = self.ensure_sample_id(pm, params, descriptor)
        if not sample_id:
            return ExecutionResult(status="no_sample", message="无法确定样本，请先创建项目样本")

        self.normalize_project_remote_base(pm)
        input_data_ids = self.import_inputs(pm, sample_id, descriptor, params)
        run_params = self.extract_run_params(descriptor, params)
        database_paths = self.build_database_paths(tool_id, descriptor)
        database_paths.update(self.extract_database_paths(descriptor, params))
        self.validate_required_databases(tool_id, descriptor, database_paths)

        execution_id = tool_engine.execute(
            tool_id=tool_id,
            input_data_ids=input_data_ids,
            parameters=run_params,
            sample_id=sample_id,
            triggered_by="manual",
            database_paths=database_paths,
        )

        logger.info("工具已提交执行: tool=%s execution_id=%s sample=%s", tool_id, execution_id, sample_id)
        return ExecutionResult(
            status="ok",
            execution_id=execution_id,
            sample_id=sample_id,
            message=f"任务已提交 ({execution_id[:16]}...)",
        )
    except ValueError as exc:
        logger.warning("execute_tool ValueError: %s", exc)
        return ExecutionResult(status="error", message=str(exc))
    except Exception:
        logger.exception("Failed to start tool %s", tool_id)
        return ExecutionResult(status="error", message="内部错误，请查看日志")
