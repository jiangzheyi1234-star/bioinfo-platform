"""Execution/history helpers extracted from ToolBridgeService."""

from __future__ import annotations

import json
import logging
import shlex
import time
from pathlib import Path
from typing import Any

from core.data.execution_query_service import ExecutionQueryService

logger = logging.getLogger(__name__)


def set_service_locator(self, sl) -> None:
    self._service_locator = sl


def set_plugin_registry(self, pr) -> None:
    self._plugin_registry = pr


def find_latest_completed_execution(self, tool_ids: list[str]) -> dict | None:
    pm = self._get_project_manager()
    if pm is None or pm.current_project is None or not tool_ids:
        return None

    placeholders = ",".join("?" for _ in tool_ids)
    query = (
        "SELECT e.execution_id, e.tool_id, e.sample_id, e.parameters, e.created_at, "
        "e.completed_at, s.name AS sample_name "
        "FROM executions e "
        "LEFT JOIN samples s ON s.sample_id = e.sample_id "
        f"WHERE e.status = 'completed' AND e.tool_id IN ({placeholders}) "
        "ORDER BY COALESCE(e.completed_at, e.created_at) DESC LIMIT 1"
    )
    row = pm.db.execute(query, tuple(tool_ids)).fetchone()
    return dict(row) if row else None


def find_execution_input(self, execution_id: str, data_type: str = "") -> str:
    pm = self._get_project_manager()
    if pm is None or pm.current_project is None:
        return ""

    query = (
        "SELECT d.file_path "
        "FROM execution_io ei "
        "JOIN data_items d ON d.data_id = ei.data_id "
        "WHERE ei.execution_id = ? AND ei.direction = 'input' "
    )
    params: list[str] = [execution_id]
    if data_type:
        query += "AND d.data_type = ? "
        params.append(data_type)
    query += "ORDER BY d.created_at ASC LIMIT 1"

    row = pm.db.execute(query, tuple(params)).fetchone()
    return str(row["file_path"]) if row else ""


def read_remote_file(self, file_path: str) -> str:
    if not file_path:
        return ""

    ssh = self._get_ssh_service()
    if ssh is None or not getattr(ssh, "is_connected", False):
        return ""

    try:
        rc, out, _ = ssh.run(f"cat {shlex.quote(file_path)} 2>/dev/null", timeout=15)
        if rc == 0:
            return out
    except Exception:
        logger.exception("读取远端文件失败: %s", file_path)
    return ""


def count_remote_lines(self, file_path: str) -> int | None:
    if not file_path:
        return None

    ssh = self._get_ssh_service()
    if ssh is None or not getattr(ssh, "is_connected", False):
        return None

    try:
        rc, out, _ = ssh.run(f"wc -l < {shlex.quote(file_path)} 2>/dev/null", timeout=10)
        if rc == 0:
            return int((out or "0").strip())
    except Exception:
        logger.exception("统计远端文件行数失败: %s", file_path)
    return None


def safe_json_loads(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _strict_json_loads(raw: str, *, context: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"{context} JSON 解析失败") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{context} 必须是 JSON object")
    return data


def get_default_primer_result_dir(self) -> str:
    default_root = ""

    try:
        from config import get_config

        runtime_cfg = get_config().get("runtime", {})
        configured_root = str(runtime_cfg.get("primer_result_root", "") or "").strip()
        if configured_root:
            default_root = configured_root.rstrip("/")
    except Exception:
        logger.debug("无法从配置读取 runtime.primer_result_root，回退到插件默认值")

    if self._plugin_registry is not None:
        try:
            desc = self._plugin_registry.get_descriptor("primer_design")
            for param in desc.get("parameters", []):
                if param.get("name") == "workflow_root":
                    configured_root = str(param.get("default") or "").strip()
                    if configured_root and not default_root:
                        default_root = configured_root.rstrip("/")
                    break
        except Exception:
            logger.debug("无法从 primer_design 插件描述符读取 workflow_root，使用默认结果目录")

    if default_root:
        return f"{default_root.rstrip('/')}/my_result"
    return "my_result"


def get_tools(self) -> list[dict]:
    if not self._plugin_registry:
        logger.warning("PluginRegistry not initialized")
        return []

    tools: list[dict] = []
    try:
        for tool_id in self._plugin_registry.list_all_ids():
            desc = self._plugin_registry.get_descriptor(tool_id)
            tools.append(
                {
                    "id": tool_id,
                    "name": desc.get("name", tool_id),
                    "category": desc.get("category", "unknown"),
                    "description": desc.get("description", ""),
                    "version": desc.get("version", "unknown"),
                    "inputs_count": len(desc.get("inputs", [])),
                    "params_count": len(desc.get("parameters", [])),
                    "db_count": len(desc.get("databases", [])),
                }
            )
    except Exception:
        logger.exception("Failed to get tools")

    return tools


def get_tool_descriptor(self, tool_id: str) -> dict:
    if not self._plugin_registry:
        logger.warning("PluginRegistry not initialized")
        return {}

    try:
        return self._plugin_registry.get_descriptor(tool_id)
    except Exception:
        logger.exception("Failed to get descriptor for %s", tool_id)
        return {}


def _parse_execution_parameters(raw: str, *, execution_id: str, tool_id: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"执行参数不是合法 JSON: tool={tool_id}, execution_id={execution_id}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"执行参数必须是对象: tool={tool_id}, execution_id={execution_id}")
    return payload


def _parameter_items_from_dict(params: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": str(key), "value": str(value)}
        for key, value in params.items()
        if value not in ("", None)
    ]


def _resolve_result_archetype(tool_id: str) -> str:
    from core.execution.tool_bridge_types import _TOOL_ARCHETYPES

    normalized = str(tool_id or "").strip()
    if not normalized:
        raise RuntimeError("执行记录缺少 tool_id")
    archetype = _TOOL_ARCHETYPES.get(normalized)
    if archetype is None:
        raise RuntimeError(f"未定义结果 archetype: tool={normalized}")
    return archetype


def execute_tool(self, tool_id: str, params: dict, *, task_id: str | None = None):
    from core.execution.tool_bridge_types import ExecutionResult

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
            task_id=str(task_id or "").strip(),
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
    except ValueError as e:
        logger.warning("execute_tool ValueError: %s", e)
        return ExecutionResult(status="error", message=str(e))
    except Exception:
        logger.exception("Failed to start tool %s", tool_id)
        return ExecutionResult(status="error", message="内部错误，请查看日志")


def normalize_project_remote_base(self, pm) -> None:
    project = getattr(pm, "current_project", None)
    if project is None:
        return

    project_id = str(getattr(project, "project_id", "") or "").strip()
    current_remote_base = str(getattr(project, "remote_base", "") or "").strip()
    if not project_id:
        return

    needs_fix = (
        not current_remote_base
        or current_remote_base.startswith("~")
        or current_remote_base == "/h2ometa"
        or current_remote_base.startswith("/h2ometa/")
    )
    if not needs_fix:
        return

    ssh = self._get_ssh_service()
    if ssh is None or not getattr(ssh, "is_connected", False):
        return

    remote_home = ""
    try:
        rc, out, _ = ssh.run('printf "%s" "$HOME"', timeout=10)
        if rc == 0:
            remote_home = str(out or "").strip()
    except Exception:
        logger.exception("Failed to resolve remote HOME for project %s", project_id)

    if not remote_home or remote_home == "/":
        return

    normalized = f"{remote_home.rstrip('/')}/.h2ometa/projects/{project_id}"
    project.remote_base = normalized

    try:
        if hasattr(pm, "update_current_project_remote_base"):
            pm.update_current_project_remote_base(normalized)
        elif hasattr(pm, "_index") and project_id in pm._index:
            pm._index[project_id]["remote_base"] = normalized
            save_index = getattr(pm, "_save_index", None)
            if callable(save_index):
                save_index()
    except Exception:
        logger.exception("Failed to persist normalized remote_base for project %s", project_id)


def _descriptor_consumes_database_var(tool_id: str, descriptor: dict, param_name: str, db_id: str) -> None:
    command_template = str(descriptor.get("command_template", "") or "")
    marker = f"{{{{ {param_name} }}}}"
    compact_marker = f"{{{{{param_name}}}}}"
    if marker in command_template or compact_marker in command_template:
        return
    raise ValueError(
        f"工具 {tool_id} 声明了数据库绑定但命令模板未消费该变量: "
        f"db_id={db_id}, param={param_name}"
    )


def get_latest_sample_id(self, pm) -> str:
    try:
        db = pm.db
        cursor = db.cursor()
        cursor.execute("SELECT sample_id FROM samples ORDER BY rowid DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0]
    except Exception:
        logger.exception("查询最近样本 ID 失败")
    return ""


def build_database_paths(self, tool_id: str, descriptor: dict | None = None) -> dict:
    from config import get_config

    if self._plugin_registry is None:
        raise ValueError(f"工具 {tool_id} 无法解析数据库绑定: 插件注册表未初始化")

    cfg = get_config()
    db_cfg = cfg.get("databases", {}) if isinstance(cfg.get("databases", {}), dict) else {}
    db_root = str(db_cfg.get("db_root", "") or "").strip()
    overrides = db_cfg.get("overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}

    desc = descriptor or self._plugin_registry.get_descriptor(tool_id)
    db_decls = desc.get("databases", [])
    if not isinstance(db_decls, list):
        raise ValueError(f"工具 {tool_id} 的 databases 声明格式错误")

    paths: dict[str, str] = {}
    for decl in db_decls:
        if not isinstance(decl, dict):
            raise ValueError(f"工具 {tool_id} 的数据库声明格式错误: {decl!r}")

        db_id = str(decl.get("id", "")).strip()
        param_name = str(decl.get("param_name", "")).strip()
        if not db_id:
            raise ValueError(f"工具 {tool_id} 的数据库声明缺少 id")
        if not param_name:
            raise ValueError(f"工具 {tool_id} 的数据库声明缺少 param_name: db_id={db_id}")
        self._descriptor_consumes_database_var(tool_id, desc, param_name, db_id)

        info = self._database_service.get_info(db_id)
        if info is None:
            raise ValueError(f"工具 {tool_id} 引用未注册数据库: db_id={db_id}")

        resolved = self._database_service.resolve_binding_value(db_id, db_root, overrides=overrides)
        if resolved:
            paths[param_name] = resolved
            logger.debug(
                "数据库路径已匹配(binding): tool=%s, db_id=%s → %s=%s",
                tool_id,
                db_id,
                param_name,
                resolved,
            )

    return paths


def ensure_sample_id(self, pm, params: dict, descriptor: dict) -> str:
    explicit_sample_id = str(params.get("__sample_id", "")).strip()
    if explicit_sample_id:
        return explicit_sample_id

    registry = self._get_data_registry()
    if registry is None:
        return ""

    sample_name = str(params.get("__sample_name", "")).strip()
    if not sample_name:
        for inp in descriptor.get("inputs", []):
            path = str(params.get(inp.get("name", ""), "")).strip()
            if path:
                sample_name = Path(path).stem
                break
    if not sample_name:
        sample_name = f"detection_{time.strftime('%Y%m%d_%H%M%S')}"

    sample_metadata: dict[str, str] = {}
    for inp in descriptor.get("inputs", []):
        input_name = str(inp.get("name", "")).strip()
        path = str(params.get(input_name, "")).strip()
        if not path:
            continue
        sample_metadata[f"input_{input_name}"] = path

    return registry.add_sample(
        sample_name,
        source="detection_page",
        metadata=sample_metadata,
    )


def import_inputs(self, pm, sample_id: str, descriptor: dict, params: dict) -> list[str]:
    registry = self._get_data_registry()
    ssh = self._get_ssh_service()
    if registry is None or ssh is None or not getattr(ssh, "is_connected", False):
        raise ValueError("数据注册器或 SSH 未就绪")

    from core.data.data_importer import DataImporter

    importer = DataImporter(ssh_service=ssh, registry=registry)
    input_data_ids: list[str] = []

    for inp in descriptor.get("inputs", []):
        name = str(inp.get("name", ""))
        required = bool(inp.get("required", True))
        input_path = str(params.get(name, "")).strip()

        if not input_path:
            if required:
                raise ValueError(f"缺少必需输入: {name}")
            continue

        if input_path.startswith("/"):
            data_id = registry.register_input(
                file_path=input_path,
                sample_id=sample_id,
                data_type=str(inp.get("type", "unknown")),
                tier="intermediate",
                metadata={"source": "remote_upstream", "input_name": name},
            )
            input_data_ids.append(data_id)
            continue

        data_id = importer.import_file(
            local_path=input_path,
            sample_id=sample_id,
            data_type=str(inp.get("type", "unknown")),
            project_remote_base=pm.current_project.remote_base,
        )
        input_data_ids.append(data_id)

    return input_data_ids


def extract_run_params(descriptor: dict, params: dict) -> dict:
    run_params: dict = {}
    for p in descriptor.get("parameters", []):
        name = str(p.get("name", ""))
        if name and name in params:
            run_params[name] = params[name]
    return run_params


def extract_database_paths(descriptor: dict, params: dict) -> dict:
    db_paths: dict = {}
    for decl in descriptor.get("databases", []):
        var_name = str(decl.get("param_name", "")).strip()
        if not var_name:
            continue

        value = str(params.get(var_name, "")).strip()
        if value:
            db_paths[var_name] = value

    return db_paths


def validate_required_databases(tool_id: str, descriptor: dict, database_paths: dict) -> None:
    for decl in descriptor.get("databases", []):
        if not isinstance(decl, dict):
            raise ValueError(f"工具 {tool_id} 的数据库声明格式错误: {decl!r}")
        if not bool(decl.get("required", False)):
            continue
        db_id = str(decl.get("id", "")).strip()
        var_name = str(decl.get("param_name", "")).strip()
        if not db_id:
            raise ValueError(f"工具 {tool_id} 的数据库声明缺少 id")
        if not var_name:
            raise ValueError(f"工具 {tool_id} 的数据库声明缺少 param_name: db_id={db_id}")
        if not str(database_paths.get(var_name, "")).strip():
            raise ValueError(f"工具 {tool_id} 缺少必需数据库: db_id={db_id}, param={var_name}")


def get_execution_history(self) -> list[dict]:
    pm = self._get_project_manager()
    if not pm or not pm.current_project:
        return []

    try:
        db = pm.db
        superseded_ids = self._get_superseded_running_execution_ids(db)
        query_service = ExecutionQueryService(db)
        rows = query_service.get_execution_history_for_ui(limit=50)
        history = []
        for row in rows:
            execution_id = row["execution_id"]
            status = row["status"]
            error = row["error"]
            if execution_id in superseded_ids and status == "running":
                status = "failed"
                error = error or "Superseded by a later completed execution"

            history.append(
                {
                    "execution_id": execution_id,
                    "sample_id": row["sample_id"],
                    "sample_name": row["sample_name"],
                    "tool_id": row["tool_id"],
                    "status": status,
                    "parameters": row["parameters"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                    "error": error,
                }
            )
        return history
    except Exception:
        logger.exception("Failed to get execution history")
        return []


def _get_superseded_running_execution_ids(db) -> set[str]:
    rows = db.execute(
        """
        SELECT older.execution_id
        FROM executions AS older
        WHERE older.status = 'running'
          AND older.archived_at IS NULL
          AND EXISTS (
            SELECT 1
            FROM executions AS newer
            WHERE newer.tool_id = older.tool_id
              AND newer.sample_id = older.sample_id
              AND newer.status = 'completed'
              AND newer.archived_at IS NULL
              AND newer.created_at > older.created_at
          )
        """
    ).fetchall()
    return {row[0] for row in rows}


def delete_execution_history(self, execution_id: str) -> dict[str, str]:
    pm = self._get_project_manager()
    if not pm or not pm.current_project:
        return {"status": "error", "message": "请先打开项目"}

    try:
        query_service = ExecutionQueryService(pm.db)
        result = query_service.archive_execution(execution_id, now=time.time())
        if result.get("status") == "ok":
            logger.info("任务历史已归档: %s", execution_id)
        return result
    except Exception:
        logger.exception("Failed to delete execution history: %s", execution_id)
        return {"status": "error", "message": "删除任务记录失败"}
