"""Workbench/live-view helpers extracted from ToolBridgeService."""

from __future__ import annotations

import copy
import json
import logging

from core.execution.tool_bridge_specs import (
    DETECTION_WORKFLOW_ORDER,
    DETECTION_WORKFLOW_SPECS,
    INTEGRATED_ANALYSIS_FEATURE_ORDER,
)
from core.execution.workbench_view_builders import build_multiplex_view, build_primer_view

logger = logging.getLogger(__name__)


def _build_primer_view_from_artifacts(self, artifacts, remote_result_dir, description, status, parameters):
    base = self.base_integrated_workbench_config()["views"]["primer_design"]
    primer_result_text = self._read_local_artifact_text(artifacts, "primer_result_final_2.txt")
    parsed_rows = self.parse_primer_result_text(primer_result_text)
    if not parsed_rows:
        return None

    all_candidates_count = self._count_local_artifact_lines(artifacts, "primer_result.txt") or len(parsed_rows)
    filtered_count = self._count_local_artifact_lines(artifacts, "primer_result_final.txt") or len(parsed_rows)
    dimer_count = self._count_local_artifact_lines(artifacts, "dimer_score.txt") or len(parsed_rows)
    return build_primer_view(
        base_view=base,
        primer_result_final_2_text=primer_result_text,
        all_candidates_count=all_candidates_count,
        filtered_count=filtered_count,
        dimer_count=dimer_count,
        description=description,
        status=status,
        parameters=parameters,
        artifacts=artifacts,
        remote_result_dir=remote_result_dir,
    )


def _build_multiplex_view_from_artifacts(self, artifacts, remote_result_dir, description, status, parameters):
    multiplex_text = self._read_local_artifact_text(artifacts, "multiplex_panel.txt")
    parsed_rows = self.parse_multiplex_result_text(multiplex_text)
    if not parsed_rows:
        return None
    synthesis_count = self._count_local_artifact_lines(artifacts, "synthesis_order.txt")
    optimization_count = self._count_local_artifact_lines(artifacts, "optimization_log.txt")
    return build_multiplex_view(
        multiplex_panel_text=multiplex_text,
        synthesis_count=synthesis_count,
        optimization_count=optimization_count,
        description=description,
        status=status,
        parameters=parameters,
        artifacts=artifacts,
        remote_result_dir=remote_result_dir,
    )


def get_live_primer_design_view(self):
    execution = self.find_latest_completed_execution(["primer_design"])
    if not execution:
        return None
    try:
        return self._build_result_view_for_execution(str(execution["execution_id"] or ""), execution)
    except Exception:
        logger.exception("Failed to build live primer workflow view: %s", execution["execution_id"])
        return None


def build_primer_view_from_result_dir(self, remote_result_dir: str):
    normalized_dir = (remote_result_dir or "").strip().rstrip("/")
    if not normalized_dir:
        return None
    artifacts = self._cache_remote_artifacts("primer_design", normalized_dir)
    return self._build_primer_view_from_artifacts(
        artifacts=artifacts,
        remote_result_dir=normalized_dir,
        description=f"当前结果来自远程目录：{normalized_dir}",
        status={"state": "completed", "label": "已加载远程结果", "detail": "结果文件已同步到当前项目本地，并从本地结果构建视图。"},
        parameters=[
            {"label": "结果目录", "value": normalized_dir},
            {"label": "结果来源", "value": "远程目录同步到本地"},
            {"label": "主文件", "value": "primer_result_final_2.txt"},
        ],
    )


def get_primer_view_for_execution(self, execution_id: str):
    normalized_execution_id = str(execution_id or "").strip()
    if not normalized_execution_id:
        return None
    row = self._get_execution_result_row(normalized_execution_id)
    if row is None or str(row["tool_id"] or "") != "primer_design":
        return None
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_execution_id))
    if not artifacts:
        return None
    ctx = self._build_execution_result_context(row, artifacts)
    return self._build_primer_view_from_artifacts(
        artifacts=artifacts,
        remote_result_dir=ctx["remote_result_dir"],
        description="用途：基于本地已同步的 primer 结果展示推荐引物、靶区位置与产物信息。\n实现：仅读取当前项目内缓存的结果工件，不在结果展示阶段触发远端查询。",
        status={"state": "completed", "label": "结果可用", "detail": "已从本地结果缓存加载 primer 产物，可直接查看与导出。"},
        parameters=[{"label": "任务 ID", "value": normalized_execution_id}],
    )


def build_multiplex_view_from_result_dir(self, remote_result_dir: str):
    normalized_dir = (remote_result_dir or "").strip().rstrip("/")
    if not normalized_dir:
        return None
    artifacts = self._cache_remote_artifacts("multiplex_primer_panel", normalized_dir)
    return self._build_multiplex_view_from_artifacts(
        artifacts=artifacts,
        remote_result_dir=normalized_dir,
        description=f"查看最终多重引物池结果与相关报告：{normalized_dir}",
        status={"state": "completed", "label": "结果可用", "detail": "结果文件已同步到当前项目本地，可直接打开本地文件。"},
        parameters=[{"label": "结果目录", "value": normalized_dir}],
    )


def get_live_multiplex_primer_panel_view(self):
    execution = self.find_latest_completed_execution(["multiplex_primer_panel"])
    if not execution:
        return None
    try:
        return self._build_result_view_for_execution(str(execution["execution_id"] or ""), execution)
    except Exception:
        logger.exception("Failed to build live multiplex workflow view: %s", execution["execution_id"])
        return None


def get_multiplex_view_for_execution(self, execution_id: str):
    normalized_execution_id = str(execution_id or "").strip()
    if not normalized_execution_id:
        return None
    row = self._get_execution_result_row(normalized_execution_id)
    if row is None or str(row["tool_id"] or "") != "multiplex_primer_panel":
        return None
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_execution_id))
    if not artifacts:
        return None
    ctx = self._build_execution_result_context(row, artifacts)
    return self._build_multiplex_view_from_artifacts(
        artifacts=artifacts,
        remote_result_dir=ctx["remote_result_dir"],
        description="用途：用于查看本地已同步的多重引物池结果、合成清单与相关评分。\n实现：仅消费当前项目中的本地结果工件，不在结果展示阶段访问远端环境。",
        status={"state": "completed", "label": "结果可用", "detail": "已从本地结果缓存加载 multiplex 产物。"},
        parameters=[{"label": "任务 ID", "value": normalized_execution_id}],
    )


def get_integrated_workbench_config(self) -> dict:
    config = self.base_integrated_workbench_config()
    pm = self._get_project_manager()
    project = getattr(pm, "current_project", None) if pm is not None else None
    config["project_id"] = str(getattr(project, "project_id", "") or "").strip()
    config["project_name"] = str(getattr(project, "name", "") or "").strip()
    features = config.setdefault("features", [])
    views = config.setdefault("views", {})
    self._ensure_detection_workbench_entries(features, views)

    for feature in features:
        if feature.get("id") == "primer_design":
            feature["name"] = "病原体引物设计"
            feature["description"] = "上传病原体基因组，自动筛选保守特异靶点并设计引物对，输出每病原体的推荐引物。"

    primer_view = views.get("primer_design")
    if isinstance(primer_view, dict):
        primer_view["title"] = "病原体引物设计"
        primer_view["description"] = "上传病原体基因组序列，系统自动完成保守靶点筛选、特异性过滤和候选引物设计，最终输出每病原体的推荐引物对。"

    if not any(feature.get("id") == "multiplex_primer_panel" for feature in features):
        features.insert(
            1,
            {
                "id": "multiplex_primer_panel",
                "name": "多重引物池设计",
                "badge": "",
                "description": "一体化完成候选引物生成与多重引物池优化，自动消解交叉二聚体冲突并输出池结果与合成订单。",
                "status": "active",
            },
        )

    views.setdefault(
        "multiplex_primer_panel",
        {
            "tool_ids": ["multiplex_primer_panel"],
            "title": "多重引物池设计",
            "description": "用途：用于靶向病原体多重 PCR 方案设计，输出可直接用于实验与交付的池化结果和合成清单。\n实现：流程内自动执行候选引物合并、迭代优化、交叉二聚体评估、扩增子冲突检查、Tm/GC 一致性检查和覆盖验证。",
            "status": {
                "state": "ready",
                "label": "等待运行",
                "detail": "系统按你的流程自动执行 16 个步骤（候选生成→池优化→冲突评估→最终报告），完成后可直接查看 multiplex_panel 与 synthesis_order。",
            },
            "summary": [
                {"label": "入池病原体", "value": "0/0", "tone": "primary"},
                {"label": "订单条目", "value": "0", "tone": "primary"},
                {"label": "质量", "value": "-", "tone": "accent"},
                {"label": "优化轮次", "value": "ready", "tone": "accent"},
            ],
            "table": {
                "title": "分析结果",
                "subtitle": "",
                "columns": self._build_multiplex_columns([]),
                "rows": [],
            },
            "artifacts": [
                "multiplex_panel.txt",
                "synthesis_order.txt",
                "pool_cross_dimer.txt",
                "optimization_log.txt",
            ],
            "charts": [],
            "provenance": {
                "parameters": [
                    {"label": "输入", "value": "病原体序列（流程内自动生成候选引物）", "description": "你只需提供病原体序列，系统会在流程内自动完成候选引物设计并进入多重池优化。"},
                    {"label": "约束", "value": "cross-dimer / Tm / amplicon length", "description": "联合约束引物间互作、退火温度一致性和扩增子长度范围。"},
                    {"label": "输出", "value": "multiplex_panel.txt / synthesis_order.txt", "description": "输出最终入池方案与可直接使用的合成订单。"},
                    {"label": "优化轮次", "value": "运行后生成", "description": "表示算法迭代优化的次数，用于消解冲突并满足约束；该值由实际任务日志统计。"},
                ],
            },
        },
    )

    live_primer_view = self.get_live_primer_design_view()
    if live_primer_view is not None:
        views["primer_design"] = live_primer_view

    live_multiplex_view = self.get_live_multiplex_primer_panel_view()
    if live_multiplex_view is not None:
        views["multiplex_primer_panel"] = live_multiplex_view

    for workflow_id in DETECTION_WORKFLOW_ORDER:
        live_detection_view = self._get_live_detection_workflow_view(workflow_id)
        if live_detection_view is not None:
            views[workflow_id] = live_detection_view

    live_targeted_view = self._get_live_targeted_seq_view()
    if live_targeted_view is not None:
        views["targeted_sequencing"] = live_targeted_view

    _sort_integrated_workbench_features(features)
    return config


def get_remote_primer_results(self, remote_result_dir: str) -> dict:
    view = self.build_primer_view_from_result_dir(remote_result_dir)
    if view is None:
        return {"status": "error", "message": "未能从该远程目录读取 primer_result_final_2.txt，请检查 SSH 连接和目录路径。"}
    return {"status": "ok", "view": view}


def _ensure_detection_workbench_entries(self, features: list[dict], views: dict[str, dict]) -> None:
    placeholder_index = next(
        (idx for idx, feature in enumerate(features) if feature.get("id") == "target_screening"),
        len(features),
    )
    for workflow_id in DETECTION_WORKFLOW_ORDER:
        spec = DETECTION_WORKFLOW_SPECS[workflow_id]
        if not any(feature.get("id") == workflow_id for feature in features):
            features.insert(placeholder_index, copy.deepcopy(spec["feature"]))
            placeholder_index += 1
        views.setdefault(workflow_id, copy.deepcopy(spec["view"]))
        if isinstance(views.get(workflow_id), dict):
            views[workflow_id].setdefault("feature_id", workflow_id)


def _sort_integrated_workbench_features(features: list[dict]) -> None:
    if not isinstance(features, list) or not features:
        return
    order_map = {feature_id: index for index, feature_id in enumerate(INTEGRATED_ANALYSIS_FEATURE_ORDER)}
    ordered = []
    seen_feature_ids = set()
    fallback_features = []

    for feature in features:
        feature_id = str(feature.get("id") or "").strip() if isinstance(feature, dict) else ""
        if feature_id in order_map and feature_id not in seen_feature_ids:
            seen_feature_ids.add(feature_id)
            ordered.append((order_map[feature_id], feature))
            continue
        fallback_features.append(feature)

    ordered.sort(key=lambda item: item[0])
    sorted_features = [item[1] for item in ordered]
    sorted_features.extend(fallback_features)
    features[:] = sorted_features


def _build_detection_workflow_view_for_execution(self, workflow_id: str, execution_id: str):
    spec = DETECTION_WORKFLOW_SPECS.get(workflow_id)
    if spec is None:
        return None
    row = self._get_execution_result_row(execution_id)
    if row is None:
        return None
    try:
        view = self._build_result_view_for_execution(execution_id, row)
        if str(view.get("feature_id") or "") != workflow_id:
            raise RuntimeError(
                f"workflow 结果路由不匹配: expected={workflow_id}, actual={view.get('feature_id')}, execution_id={execution_id}"
            )
        return view
    except Exception:
        logger.exception("Failed to build detection workflow result view: %s / %s", workflow_id, execution_id)
        return None


def _get_live_detection_workflow_view(self, workflow_id: str):
    pm = self._get_project_manager()
    if pm is None or pm.current_project is None:
        return None

    spec = DETECTION_WORKFLOW_SPECS.get(workflow_id)
    if spec is None:
        return None

    target_eid = None
    if workflow_id == "unknown_sample_detection":
        try:
            rows = pm.db.execute(
                "SELECT execution_id, tool_id, parameters FROM executions "
                "WHERE tool_id IN ('unknown_sample_detection', 'centrifuge', 'kraken2') "
                "AND status = 'completed' "
                "ORDER BY rowid DESC",
            ).fetchall()
        except Exception:
            rows = []
        for row in rows or []:
            if row["tool_id"] == workflow_id:
                target_eid = row["execution_id"]
                break
        if target_eid is None:
            legacy_workflow = spec.get("legacy_workflow")
            for row in rows or []:
                try:
                    params = json.loads(row["parameters"] or "{}")
                except Exception:
                    continue
                if params.get("workflow") == legacy_workflow:
                    target_eid = row["execution_id"]
                    break
    else:
        try:
            row = pm.db.execute(
                "SELECT execution_id FROM executions WHERE tool_id = ? AND status = 'completed' ORDER BY rowid DESC LIMIT 1",
                (workflow_id,),
            ).fetchone()
        except Exception:
            row = None
        if row:
            target_eid = row["execution_id"]

    if target_eid is None:
        return None
    return self._build_detection_workflow_view_for_execution(workflow_id, target_eid)


def _get_live_unknown_sample_detection_view(self):
    return self._get_live_detection_workflow_view("unknown_sample_detection")


def _get_live_targeted_seq_view(self):
    pm = self._get_project_manager()
    if pm is None or pm.current_project is None:
        return None
    try:
        rows = pm.db.execute(
            "SELECT execution_id, parameters FROM executions "
            "WHERE tool_id IN ('centrifuge', 'kraken2') AND status = 'completed' "
            "ORDER BY rowid DESC",
        ).fetchall()
    except Exception:
        return None

    target_eid = None
    for r in (rows or []):
        try:
            params = json.loads(r["parameters"] or "{}")
        except Exception:
            params = {}
        if params.get("workflow", "") != "unknown_detection":
            target_eid = r["execution_id"]
            break

    if target_eid is None:
        return None
    try:
        row = self._get_execution_result_row(target_eid)
        if row is None:
            return None
        return self._build_result_view_for_execution(target_eid, row)
    except Exception:
        logger.exception("Failed to build live targeted sequencing view: %s", target_eid)
        return None
