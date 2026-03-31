"""Unified result-view builders extracted from ToolBridgeService."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from core.execution.single_tool_result_parsers import parse_fastp_json, parse_prokka_stats_text
from core.execution.single_tool_view_builder import (
    build_artifact_result_view,
    build_single_tool_view,
    normalize_result_view,
    section_from_view,
)
from core.execution.tool_bridge_specs import DETECTION_WORKFLOW_ORDER, DETECTION_WORKFLOW_SPECS, TARGETED_RESULT_TOOL_IDS
from core.pipeline.chart_data_parser import ChartDataParser


def _build_result_view_for_execution(self, execution_id: str, execution_row: Any | None = None) -> dict:
    row = execution_row or self._get_execution_result_row(execution_id)
    if row is None:
        raise RuntimeError(f"未找到执行记录: {execution_id}")

    tool_id = str(row["tool_id"] or "").strip()
    feature_id = self._resolve_detection_workflow_id_for_execution(execution_id) or tool_id
    try:
        archetype = self._resolve_result_archetype(feature_id)
    except RuntimeError:
        archetype = self._resolve_result_archetype(tool_id)

    if archetype == "qc_report":
        return self._build_qc_report_view_for_execution(execution_id, row)
    if archetype == "taxonomy_profile":
        return self._build_taxonomy_profile_view_for_execution(execution_id, row)
    if archetype == "html_report":
        return self._build_html_report_view_for_execution(execution_id, row)
    if archetype == "annotation_table":
        return self._build_annotation_table_view_for_execution(execution_id, row)
    if archetype == "quality_assessment":
        return self._build_quality_assessment_view_for_execution(execution_id, row)
    if archetype == "workflow_product":
        return self._build_workflow_product_view_for_execution(
            execution_id=execution_id,
            execution_row=row,
            feature_id=feature_id,
        )
    if archetype == "artifact_collection":
        return self._build_artifact_collection_view_for_execution(execution_id, row)
    raise RuntimeError(
        f"未支持的结果 archetype: tool={tool_id}, feature_id={feature_id}, archetype={archetype}, execution_id={execution_id}"
    )


def _build_artifact_backed_view_for_execution(
    self,
    execution_row: Any,
    *,
    archetype: str,
    description: str,
    status_detail: str,
) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    descriptor = self._require_tool_descriptor(tool_id)
    ctx = self._build_execution_result_context(execution_row)
    artifacts = ctx["artifacts"]
    return build_artifact_result_view(
        feature_id=tool_id,
        tool_id=tool_id,
        archetype=archetype,
        tool_ids=[tool_id],
        title=str(descriptor.get("name") or tool_id),
        description=description,
        status={
            "state": "completed",
            "label": "结果已就绪",
            "detail": status_detail,
        },
        artifacts=artifacts,
        parameters=ctx["parameters"],
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
        tool_version=ctx["tool_version"],
        remote_result_dir=ctx["remote_result_dir"],
        local_result_dir=ctx["local_result_dir"],
    )


def _build_artifact_collection_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    descriptor = self._require_tool_descriptor(tool_id)
    return self._build_artifact_backed_view_for_execution(
        execution_row,
        archetype="artifact_collection",
        description=str(descriptor.get("description") or f"{tool_id} 结果"),
        status_detail="该工具以文件集结果为主，以下展示已同步产物。",
    )


def _build_generic_table_view_for_execution(
    self,
    execution_row: Any,
    *,
    archetype: str,
    summary_keys: list[str] | list[tuple[str, str, str]] | None = None,
    row_count_label: str = "结果条目",
    table_subtitle: str = "",
) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    execution_id = str(execution_row["execution_id"] or "")
    descriptor = self._require_tool_descriptor(tool_id)
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
    if not artifacts:
        raise RuntimeError(f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}")
    ctx = self._build_execution_result_context(execution_row, artifacts)

    artifact = self._artifact_from_result_views(
        descriptor,
        artifacts,
        sample_id=ctx["sample_id"],
        preferred_types=("table", "html", "krona"),
    )
    if artifact is None:
        artifact = self._first_available_artifact_with_suffix(artifacts, (".tsv", ".csv", ".txt", ".json"))
    if artifact is None:
        return self._build_artifact_collection_view_for_execution(execution_id, execution_row)

    local_path = str(artifact.get("local_path") or "").strip()
    if not local_path:
        raise RuntimeError(f"结果文件缺少本地路径: tool={tool_id}, execution_id={execution_id}, name={artifact.get('name')}")

    columns, rows, metrics = self._parse_table_file(Path(local_path))
    summary = self._summarize_metric_rows(rows, preferred_keys=summary_keys or [], metrics=metrics) if summary_keys else []
    if not summary:
        summary = self._summarize_row_count(rows, label=row_count_label)
    return build_single_tool_view(
        feature_id=tool_id,
        tool_id=tool_id,
        archetype=archetype,
        tool_ids=[tool_id],
        title=str(descriptor.get("name") or tool_id),
        description=str(descriptor.get("description") or f"{tool_id} 结果"),
        status={"state": "completed", "label": "结果已就绪", "detail": "已加载结构化结果表。"},
        summary=summary,
        columns=columns,
        rows=rows,
        artifacts=artifacts,
        parameters=ctx["parameters"],
        table_title=str((descriptor.get("result_views") or [{}])[0].get("title") or "分析结果"),
        table_subtitle=table_subtitle or f"已从 {artifact.get('name')} 构建结果表。",
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
        tool_version=ctx["tool_version"],
        remote_result_dir=ctx["remote_result_dir"],
        local_result_dir=ctx["local_result_dir"],
    )


def _build_qc_report_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    if tool_id == "fastp":
        view = self._build_fastp_view_for_execution(execution_id)
        if view is None:
            raise RuntimeError(f"fastp 结果不可用: execution_id={execution_id}")
        return view
    return self._build_generic_table_view_for_execution(
        execution_row,
        archetype="qc_report",
        summary_keys=["total_reads", "host_reads", "non_host_reads", "host_fraction"],
        row_count_label="QC 指标",
        table_subtitle="已从结果文件构建 QC / 去宿主结果表。",
    )


def _build_html_report_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    descriptor = self._require_tool_descriptor(tool_id)
    ctx = self._build_execution_result_context(execution_row)
    html_artifact = self._find_result_artifact(
        ctx["artifacts"],
        descriptor,
        ctx["sample_id"],
        preferred_view_types=("html", "krona"),
        allowed_suffixes=(".html",),
    )
    if html_artifact is None:
        raise RuntimeError(f"HTML 结果缺失: tool={tool_id}, execution_id={execution_id}")
    return self._build_artifact_backed_view_for_execution(
        execution_row,
        archetype="html_report",
        description=str(descriptor.get("description") or f"{tool_id} HTML 报告"),
        status_detail="已同步主 HTML 报告，可在页面预览或在系统中打开。",
    )


def _build_annotation_table_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    if tool_id == "prokka":
        view = self._build_prokka_view_for_execution(execution_id, execution_row)
        if view is None:
            raise RuntimeError(f"Prokka 结果不可用: execution_id={execution_id}")
        return view
    return self._build_generic_table_view_for_execution(
        execution_row,
        archetype="annotation_table",
        summary_keys=["name", "gene", "product", "contig", "query_id"],
        row_count_label="注释条目",
        table_subtitle="已从结果文件构建注释 / 命中结果表。",
    )


def _build_quality_assessment_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    return self._build_generic_table_view_for_execution(
        execution_row,
        archetype="quality_assessment",
        summary_keys=self._QUALITY_SUMMARY_KEYS.get(tool_id, []),
        row_count_label="质量指标",
        table_subtitle="已从质量评估文件构建结果表。",
    )


def _build_workflow_product_view_for_execution(
    self,
    execution_id: str,
    execution_row: Any,
    *,
    feature_id: str | None = None,
) -> dict:
    resolved_feature_id = feature_id or self._resolve_detection_workflow_id_for_execution(execution_id) or str(execution_row["tool_id"] or "")
    if resolved_feature_id == "primer_design":
        return self._build_primer_workflow_view_for_execution(execution_id)
    if resolved_feature_id == "multiplex_primer_panel":
        return self._build_multiplex_workflow_view_for_execution(execution_id)
    if resolved_feature_id in DETECTION_WORKFLOW_ORDER:
        return self._build_detection_workflow_result_view(execution_id, execution_row, feature_id=resolved_feature_id)
    raise RuntimeError(
        f"未支持的 workflow_product: tool={execution_row['tool_id']}, feature_id={resolved_feature_id}, execution_id={execution_id}"
    )


def _build_single_section_workflow_view(
    self,
    execution_id: str,
    *,
    feature_id: str,
    source_view: dict[str, Any],
    section_id: str,
) -> dict:
    row = self._get_execution_result_row(execution_id)
    if row is None:
        raise RuntimeError(f"未找到执行记录: {execution_id}")
    descriptor = self._require_tool_descriptor(feature_id)
    context = self._build_execution_result_context(row)
    normalize_kwargs = self._normalize_result_view_kwargs(context)
    section_view = normalize_result_view(
        source_view,
        feature_id=feature_id,
        tool_id=feature_id,
        archetype="annotation_table",
        **normalize_kwargs,
    )
    return normalize_result_view(
        source_view,
        feature_id=feature_id,
        tool_id=feature_id,
        archetype="workflow_product",
        title=str(descriptor.get("name") or feature_id),
        description=str(descriptor.get("description") or f"{feature_id} 工作流结果"),
        sections=[
            section_from_view(
                section_view,
                section_id=section_id,
                title="产品结果",
                archetype="annotation_table",
            )
        ],
        **normalize_kwargs,
    )


def _build_primer_workflow_view_for_execution(self, execution_id: str) -> dict:
    primer_view = self.get_primer_view_for_execution(execution_id)
    if primer_view is None:
        raise RuntimeError(f"引物设计结果不可用: execution_id={execution_id}")
    return self._build_single_section_workflow_view(
        execution_id,
        feature_id="primer_design",
        source_view=primer_view,
        section_id="primer_result",
    )


def _build_multiplex_workflow_view_for_execution(self, execution_id: str) -> dict:
    multiplex_view = self.get_multiplex_view_for_execution(execution_id)
    if multiplex_view is None:
        raise RuntimeError(f"多重引物池结果不可用: execution_id={execution_id}")
    return self._build_single_section_workflow_view(
        execution_id,
        feature_id="multiplex_primer_panel",
        source_view=multiplex_view,
        section_id="multiplex_result",
    )


def _build_prokka_view_for_execution(self, execution_id: str, execution_row: Any | None = None) -> dict | None:
    row = execution_row or self._get_execution_result_row(execution_id)
    if row is None:
        return None
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(str(row["execution_id"] or "")))
    if not artifacts:
        raise RuntimeError(f"Prokka 执行结果缺少工件清单: {execution_id}")

    sample_id = str(row["sample_id"] or "")
    stats_name = f"{sample_id}.prokka.txt"
    stats_text = self._read_local_artifact_text(artifacts, stats_name)
    if not stats_text:
        raise RuntimeError(f"Prokka 结果缺少主统计文件: {stats_name}")
    stats = parse_prokka_stats_text(stats_text)
    if not stats:
        raise RuntimeError(f"Prokka 统计文件无法解析: {stats_name}")

    descriptor = self._require_tool_descriptor("prokka")
    ctx = self._build_execution_result_context(row, artifacts)
    table_columns = [
        {"key": "organism", "label": "物种"},
        {"key": "contigs", "label": "Contigs"},
        {"key": "bases", "label": "Bases"},
        {"key": "cds", "label": "CDS"},
        {"key": "rrna", "label": "rRNA"},
        {"key": "trna", "label": "tRNA"},
    ]
    table_rows = [
        {
            "organism": stats.get("organism", sample_id or "-"),
            "contigs": stats.get("contigs", "-"),
            "bases": stats.get("bases", "-"),
            "cds": stats.get("cds", "-"),
            "rrna": stats.get("rrna", "-"),
            "trna": stats.get("trna", "-"),
        }
    ]
    return build_single_tool_view(
        feature_id="prokka",
        tool_id="prokka",
        archetype="annotation_table",
        tool_ids=["prokka"],
        title=str(descriptor.get("name") or "Prokka"),
        description=str(descriptor.get("description") or "快速原核基因组注释结果"),
        status={
            "state": "completed",
            "label": "结果已就绪",
            "detail": "注释统计和主要产物已同步到本地。",
        },
        summary=[
            {"label": "CDS", "value": stats.get("cds", "-"), "tone": "primary"},
            {"label": "rRNA", "value": stats.get("rrna", "-"), "tone": "info"},
            {"label": "tRNA", "value": stats.get("trna", "-"), "tone": "info"},
            {"label": "Contigs", "value": stats.get("contigs", "-"), "tone": "success"},
        ],
        columns=table_columns,
        rows=table_rows,
        artifacts=artifacts,
        parameters=ctx["parameters"],
        table_title="注释统计",
        table_subtitle="Prokka 输出的主要注释统计摘要。",
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
        tool_version=ctx["tool_version"],
        remote_result_dir=ctx["remote_result_dir"],
        local_result_dir=ctx["local_result_dir"],
    )


def _build_fastp_view_for_execution(self, execution_id: str) -> dict | None:
    normalized_id = str(execution_id or "").strip()
    if not normalized_id:
        return None

    pm = self._get_project_manager()
    if pm is None or pm.current_project is None:
        return None
    self.normalize_project_remote_base(pm)

    try:
        row = pm.db.execute(
            "SELECT tool_id, sample_id FROM executions WHERE execution_id = ? LIMIT 1",
            (normalized_id,),
        ).fetchone()
    except Exception:
        return None
    if not row or row["tool_id"] != "fastp":
        return None
    execution_row = self._get_execution_result_row(normalized_id)
    if execution_row is None:
        return None
    base_view = self._build_fastp_view_from_artifacts(
        execution_row,
        feature_id="fastp",
        include_context_parameters=False,
        table_title="质控过滤统计",
        table_subtitle="fastp 接头去除 + 低质量过滤详情。",
    )
    if base_view is None:
        return None
    original_reads = next((item["value"] for item in base_view["summary"] if item["label"] == "原始 Reads"), "—")
    passed_reads = next((item["value"] for item in base_view["summary"] if item["label"] == "通过 QC"), "—")
    base_view["parameters"] = [
        {"label": "输入", "value": f"双端 FASTQ ({original_reads} reads)"},
        {"label": "输出", "value": f"清洁 reads ({passed_reads})"},
        {"label": "工具", "value": "fastp"},
    ] + list(base_view.get("provenance", {}).get("parameters") or [])
    return base_view


def _build_taxonomy_profile_view_for_execution(self, execution_id: str, execution_row: Any) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    if tool_id in ("kraken2", "centrifuge"):
        view = self._build_targeted_seq_view_for_execution(execution_id)
        if view is None:
            raise RuntimeError(f"分类结果不可用: tool={tool_id}, execution_id={execution_id}")
        return view
    return self._build_generic_table_view_for_execution(
        execution_row,
        archetype="taxonomy_profile",
        summary_keys=["name", "abundance", "relative_abundance", "fraction_total_reads"],
        row_count_label="分类条目",
        table_subtitle="已从分类结果文件构建结果表。",
    )


def _resolve_targeted_seq_local_paths(
    self,
    sample_id: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Path | None]:
    suffixes = {
        "kreport": ".kreport",
        "coverage_depth": ".coverage_depth.tsv",
        "amplicon_performance": ".amplicon_performance.tsv",
        "fastp_json": ".fastp.json",
        "bracken": ".bracken.tsv",
        "bracken_kreport": ".bracken.kreport",
        "krona": ".krona.html",
    }
    return {
        key: self._local_artifact_path(artifacts, f"{sample_id}{suffix}")
        for key, suffix in suffixes.items()
    }


def _build_targeted_seq_abundance_payload(
    self,
    chart_data: dict[str, Any],
    bracken_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if bracken_rows:
        return (
            [
                {
                    "name": row["name"],
                    "reads": int(row["reads"].replace(",", "")),
                    "value": float(row["percentage"].rstrip("%")),
                }
                for row in bracken_rows
            ],
            "Bracken 丰度 (Top 20)",
        )
    return list(chart_data.get("data", [])[:20]), "物种丰度 (Top 20)"


def _build_targeted_seq_table_payload(
    self,
    chart_data: dict[str, Any],
    bracken_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str, str]:
    if bracken_rows:
        return (
            bracken_rows,
            [
                {"key": "rank", "label": "序号"},
                {"key": "name", "label": "物种名称"},
                {"key": "reads", "label": "Bracken Reads"},
                {"key": "percentage", "label": "相对丰度 (%)"},
            ],
            "Bracken 丰度结果",
            "优先展示 Bracken 重估后的物种丰度结果。",
        )
    rows = [
        {
            "rank": str(i),
            "name": item["name"],
            "reads": f'{item.get("reads", 0):,}',
            "percentage": f'{item["value"]:.2f}%',
        }
        for i, item in enumerate(chart_data.get("data", []), 1)
    ]
    return (
        rows,
        [
            {"key": "rank", "label": "序号"},
            {"key": "name", "label": "病原体名称"},
            {"key": "reads", "label": "Reads 数"},
            {"key": "percentage", "label": "占比 (%)"},
        ],
        "病原体物种组成",
        "基于 kreport 解析的物种组成，按丰度降序排列。",
    )


def _build_targeted_seq_summary(self, summary_data: dict[str, Any]) -> list[dict[str, Any]]:
    total = summary_data["total_reads"]
    classified = summary_data["classified_reads"]
    pct = f"{classified / total * 100:.1f}%" if total > 0 else "0%"
    return [
        {"label": "总 Reads", "value": f"{total:,}", "tone": "primary"},
        {"label": "已分类", "value": f"{classified:,} ({pct})", "tone": "info"},
        {"label": "物种数", "value": str(summary_data["species_count"]), "tone": "success"},
        {"label": "Top 物种", "value": summary_data["top_species"], "tone": "accent"},
    ]


def _append_chart_if_present(self, charts: list[dict[str, Any]], chart: dict[str, Any], *, title: str | None = None) -> None:
    if not chart.get("data"):
        return
    if title is not None:
        charts.append({"type": chart.get("type"), "title": title, "data": chart.get("data", [])})
        return
    charts.append(chart)


def _build_targeted_seq_view_for_execution(self, execution_id: str) -> dict | None:
    normalized_id = str(execution_id or "").strip()
    if not normalized_id:
        return None
    execution_row = self._get_execution_result_row(normalized_id)
    if execution_row is None:
        return None
    if str(execution_row["tool_id"] or "") not in TARGETED_RESULT_TOOL_IDS:
        return None
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(normalized_id))
    if not artifacts:
        return None
    ctx = self._build_execution_result_context(execution_row, artifacts)
    tool_id = ctx["tool_id"]
    sample_id = ctx["sample_id"]
    remote_dir = ctx["remote_result_dir"]
    local_paths = self._resolve_targeted_seq_local_paths(sample_id, artifacts)
    local_kreport = local_paths["kreport"]
    if local_kreport is None:
        return None

    chart_data = ChartDataParser.parse_kreport(str(local_kreport))
    sunburst_chart = ChartDataParser.parse_kreport_tree(str(local_kreport))
    summary_data = ChartDataParser.parse_kreport_summary(str(local_kreport))
    bracken_rows = self._parse_bracken_abundance_rows(local_paths["bracken"])
    read_flow_chart = self._build_read_flow_chart(
        local_paths["fastp_json"],
        summary_data,
    )
    coverage_chart = {"type": "coverage_depth", "title": "Coverage Depth", "data": []}
    amplicon_chart = {"type": "amplicon_performance", "title": "Amplicon Performance", "data": []}
    if local_paths["coverage_depth"] is not None:
        coverage_chart = ChartDataParser.parse_coverage_depth(str(local_paths["coverage_depth"]))
    if local_paths["amplicon_performance"] is not None:
        amplicon_chart = ChartDataParser.parse_amplicon_performance(str(local_paths["amplicon_performance"]))
    abundance_bar_data, abundance_bar_title = self._build_targeted_seq_abundance_payload(chart_data, bracken_rows)

    charts = [
        {
            "type": "pie",
            "title": "病原体组成",
            "data": chart_data.get("data", []),
        },
        {
            "type": "abundance_bar",
            "title": abundance_bar_title,
            "data": abundance_bar_data,
        },
    ]
    if read_flow_chart is not None:
        charts.insert(0, read_flow_chart)
    self._append_chart_if_present(charts, sunburst_chart)
    self._append_chart_if_present(charts, coverage_chart, title="Coverage Depth")
    self._append_chart_if_present(charts, amplicon_chart, title="Amplicon Performance")
    rows, columns, table_title, table_subtitle = self._build_targeted_seq_table_payload(chart_data, bracken_rows)
    summary = self._build_targeted_seq_summary(summary_data)

    classifier_label = "Centrifuge" if tool_id in ("centrifuge", "unknown_sample_detection") else "Kraken2"
    return build_single_tool_view(
        feature_id=str(tool_id),
        tool_id=str(tool_id),
        archetype="taxonomy_profile",
        tool_ids=[tool_id],
        title=str(self._require_tool_descriptor(tool_id).get("name") or tool_id),
        description=f"{classifier_label} 分类结果",
        status={"state": "completed", "label": "分析完成", "detail": "已加载分类图表和结果表。"},
        summary=summary,
        charts=charts,
        columns=columns,
        rows=rows,
        artifacts=self._available_artifacts(artifacts),
        parameters=ctx["parameters"],
        table_title=table_title,
        table_subtitle=table_subtitle,
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
        tool_version=ctx["tool_version"],
        remote_result_dir=remote_dir,
        local_result_dir=ctx["local_result_dir"],
    )


def _build_fastp_view_from_artifacts(
    self,
    execution_row: Any,
    *,
    feature_id: str = "fastp",
    include_context_parameters: bool = True,
    table_title: str | None = None,
    table_subtitle: str | None = None,
) -> dict | None:
    execution_id = str(execution_row["execution_id"] or "")
    sample_id = str(execution_row["sample_id"] or "")
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
    if not artifacts:
        return None

    json_name = f"{sample_id}.fastp.json"
    html_name = f"{sample_id}.fastp.html"
    local_json = self._local_artifact_path(artifacts, json_name)
    if local_json is None:
        return None

    ctx = self._build_execution_result_context(execution_row, artifacts)
    remote_dir = ctx["remote_result_dir"]
    html_artifact = self._artifact_by_name(artifacts, html_name)
    fastp_data = parse_fastp_json(local_json)
    summary = fastp_data.get("summary", {})
    before = summary.get("before_filtering", {})
    after = summary.get("after_filtering", {})
    filtering = fastp_data.get("filtering_result", {})

    total_before = int(before.get("total_reads", 0) or 0)
    total_after = int(after.get("total_reads", 0) or 0)
    q30_before = float(before.get("q30_rate", 0) or 0)
    q30_after = float(after.get("q30_rate", 0) or 0)
    gc_after = float(after.get("gc_content", 0) or 0)
    passed = int(filtering.get("passed_filter_reads", 0) or 0)
    low_quality = int(filtering.get("low_quality_reads", 0) or 0)
    too_short = int(filtering.get("too_short_reads", 0) or 0)
    too_many_n = int(filtering.get("too_many_N_reads", 0) or 0)

    pct_pass = f"{passed / total_before * 100:.1f}%" if total_before > 0 else "—"
    fastp_chart = ChartDataParser.parse_fastp_json(str(local_json))
    return build_single_tool_view(
        feature_id=feature_id,
        tool_id="fastp",
        archetype="qc_report",
        tool_ids=["fastp"],
        title="fastp 质控报告",
        description=f"样品 {sample_id} 的 QC 质控统计。",
        status={
            "state": "completed",
            "label": "QC 完成",
            "detail": f"通过率 {pct_pass}，Q30 {q30_after:.1%}",
        },
        summary=[
            {"label": "原始 Reads", "value": f"{total_before:,}", "tone": "primary"},
            {"label": "通过 QC", "value": f"{total_after:,} ({pct_pass})", "tone": "success"},
            {"label": "Q30 (过滤后)", "value": f"{q30_after:.2%}", "tone": "info"},
            {"label": "GC 含量", "value": f"{gc_after:.2%}", "tone": "info"},
        ],
        charts=[fastp_chart],
        columns=[
            {"key": "metric", "label": "指标"},
            {"key": "before", "label": "过滤前"},
            {"key": "after", "label": "过滤后"},
        ],
        rows=[
            {"metric": "总 Reads", "before": f"{total_before:,}", "after": f"{total_after:,}"},
            {"metric": "Q30", "before": f"{q30_before:.2%}", "after": f"{q30_after:.2%}"},
            {"metric": "GC 含量", "before": f"{float(before.get('gc_content', 0) or 0):.2%}", "after": f"{gc_after:.2%}"},
            {"metric": "低质量 Reads", "before": "—", "after": f"{low_quality:,}"},
            {"metric": "过短 Reads", "before": "—", "after": f"{too_short:,}"},
            {"metric": "高 N Reads", "before": "—", "after": f"{too_many_n:,}"},
            {"metric": "通过率", "before": "—", "after": pct_pass},
        ],
        artifacts=[
            {
                "name": json_name,
                "remote_path": str((self._artifact_by_name(artifacts, json_name) or {}).get("remote_path") or f"{remote_dir}/{json_name}"),
                "local_path": str(local_json),
                "available": True,
            },
            {
                "name": html_name,
                "remote_path": str((html_artifact or {}).get("remote_path") or f"{remote_dir}/{html_name}"),
                "local_path": str((html_artifact or {}).get("local_path") or ""),
                "available": bool((html_artifact or {}).get("available")),
            },
        ],
        provenance={
            "execution_id": ctx["execution_id"],
            "parameters": list(ctx["parameters"]),
            "tool_version": ctx["tool_version"],
            "remote_result_dir": remote_dir,
            "local_result_dir": ctx["local_result_dir"],
        },
        parameters=list(ctx["parameters"]) if include_context_parameters else [],
        table_title=table_title or "分析结果",
        table_subtitle=table_subtitle or "",
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
    )


def _infer_total_reads_from_summary(self, summary: list[dict[str, Any]]) -> int:
    for item in summary:
        if "Reads" not in str(item.get("label") or ""):
            continue
        try:
            return int(str(item.get("value") or "0").replace(",", "").split("(")[0].strip())
        except ValueError:
            continue
    return 0


def _finalize_unknown_detection_table(self, workflow_view: dict[str, Any], spec: dict[str, Any]) -> None:
    workflow_view["table"]["columns"] = copy.deepcopy(spec.get("view", {}).get("columns", []))
    workflow_view["columns"] = list(workflow_view["table"]["columns"])
    total_reads = self._infer_total_reads_from_summary(list(workflow_view.get("summary") or []))
    for row_data in workflow_view.get("rows", []):
        if "rpm" not in row_data:
            if total_reads > 0:
                try:
                    raw_reads = int(str(row_data.get("reads", "0")).replace(",", ""))
                    row_data["rpm"] = f"{raw_reads / total_reads * 1_000_000:,.1f}"
                except (TypeError, ValueError):
                    row_data["rpm"] = "—"
            else:
                row_data["rpm"] = "—"
        row_data.setdefault("category", "—")
        row_data.setdefault("source", "Centrifuge")
    workflow_view["table"]["rows"] = list(workflow_view["rows"])


def _build_detection_workflow_result_view(self, execution_id: str, execution_row: Any, *, feature_id: str) -> dict:
    tool_id = str(execution_row["tool_id"] or "")
    artifacts = self._normalize_artifacts(self.list_local_execution_artifacts(execution_id))
    if not artifacts:
        raise RuntimeError(f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}")
    ctx = self._build_execution_result_context(execution_row, artifacts)
    spec = DETECTION_WORKFLOW_SPECS.get(feature_id, {})

    fastp_view = self._build_fastp_view_from_artifacts(execution_row, feature_id="fastp")
    taxonomy_view = self._build_targeted_seq_view_for_execution(execution_id)
    if taxonomy_view is None:
        raise RuntimeError(f"工作流缺少分类结果: tool={tool_id}, execution_id={execution_id}")
    normalized_taxonomy = normalize_result_view(
        taxonomy_view,
        feature_id=feature_id,
        tool_id=tool_id,
        archetype="taxonomy_profile",
        **self._normalize_result_view_kwargs(ctx),
    )

    descriptor = self._require_tool_descriptor(feature_id)
    sections = []
    if fastp_view is not None:
        sections.append(section_from_view(fastp_view, section_id="fastp", title="质控结果", archetype="qc_report"))
    sections.append(section_from_view(normalized_taxonomy, section_id="taxonomy", title="分类结果", archetype="taxonomy_profile"))

    workflow_summary = []
    if fastp_view is not None:
        workflow_summary.extend(list(fastp_view.get("summary") or [])[:2])
    workflow_summary.extend(list(normalized_taxonomy.get("summary") or [])[:3])
    workflow_view = build_single_tool_view(
        feature_id=feature_id,
        tool_id=feature_id,
        archetype="workflow_product",
        tool_ids=[feature_id],
        title=str(spec.get("view", {}).get("title") or descriptor.get("name") or feature_id),
        description=str(spec.get("view", {}).get("description") or descriptor.get("description") or f"{feature_id} 工作流结果"),
        status={"state": "completed", "label": "结果已就绪", "detail": "已复用子工具结果构建工作流结果视图。"},
        summary=workflow_summary,
        charts=list(normalized_taxonomy.get("charts") or []),
        table=dict(normalized_taxonomy.get("table") or {}),
        artifacts=artifacts,
        provenance={
            "execution_id": ctx["execution_id"],
            "parameters": list(spec.get("view", {}).get("parameters") or []) + list(ctx["parameters"]),
            "tool_version": ctx["tool_version"],
            "remote_result_dir": ctx["remote_result_dir"],
            "local_result_dir": ctx["local_result_dir"],
        },
        sample_name=ctx["sample_name"],
        execution_id=ctx["execution_id"],
        updated_at=ctx["updated_at"],
        sections=sections,
    )
    workflow_view["table"]["title"] = str(spec.get("view", {}).get("table_title") or workflow_view["table"].get("title") or "分析结果")
    workflow_view["table"]["subtitle"] = str(spec.get("view", {}).get("table_subtitle") or workflow_view["table"].get("subtitle") or "")
    workflow_view["table_title"] = workflow_view["table"]["title"]
    workflow_view["table_subtitle"] = workflow_view["table"]["subtitle"]
    workflow_view["parameters"] = list(workflow_view["provenance"]["parameters"])

    if feature_id == "unknown_sample_detection":
        self._finalize_unknown_detection_table(workflow_view, spec)

    return workflow_view
