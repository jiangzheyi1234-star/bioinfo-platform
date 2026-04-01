from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.execution.single_tool_result_parsers import summarize_table_row

logger = logging.getLogger(__name__)

QUALITY_SUMMARY_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "quast": [("Contigs", "# contigs", "primary"), ("总长度", "Total length", "info"), ("N50", "N50", "success")],
    "checkm2": [("Completeness", "Completeness", "success"), ("Contamination", "Contamination", "warning"), ("GC", "GC_Content", "info")],
    "gunc": [("Mapped Genes", "n_genes_mapped", "primary"), ("CSS", "clade_separation_score", "info"), ("Contamination", "contamination_portion", "warning")],
}


def row_lookup(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in row.items()}


def parse_float(value: Any) -> float | None:
    try:
        text = str(value).strip().rstrip("%")
        if not text:
            return None
        number = float(text)
        if 0 <= number <= 1 and "fraction" in str(value):
            return number * 100
        return number
    except Exception:
        return None


def build_read_flow_chart(fastp_json_path: Path | None, kreport_summary: dict[str, Any]) -> dict[str, Any] | None:
    stages: list[dict[str, Any]] = []
    if fastp_json_path is not None and fastp_json_path.exists():
        try:
            payload = json.loads(fastp_json_path.read_text(encoding="utf-8"))
            summary = payload.get("summary", {})
            before = summary.get("before_filtering", {})
            after = summary.get("after_filtering", {})
            raw_reads = int(before.get("total_reads", 0) or 0)
            qc_reads = int(after.get("total_reads", 0) or 0)
            if raw_reads > 0:
                stages.append({"name": "原始 Reads", "value": raw_reads})
            if qc_reads > 0:
                stages.append({"name": "QC 后", "value": qc_reads})
        except Exception:
            logger.exception("Failed to parse fastp summary for funnel chart: %s", fastp_json_path)

    classified = int(kreport_summary.get("classified_reads", 0) or 0)
    unclassified = int(kreport_summary.get("unclassified_reads", 0) or 0)
    total = int(kreport_summary.get("total_reads", 0) or 0)
    if total > 0:
        stages.append({"name": "送分类 Reads", "value": total})
    if classified > 0:
        stages.append({"name": "已分类", "value": classified})
    if unclassified > 0:
        stages.append({"name": "未分类", "value": unclassified})

    if len(stages) < 2:
        return None
    return {"type": "funnel", "title": "分析流程摘要", "data": stages}


def summarize_metric_rows(
    rows: list[dict[str, Any]],
    preferred_keys: list[str] | list[tuple[str, str, str]],
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if metrics:
        metric_candidates = [(str(key), str(key), "info") for key in metrics.keys()]
        summary = summarize_table_row(metrics, metric_candidates[:4])
        if summary:
            return summary
    if not rows:
        return []
    first_row = row_lookup(rows[0])
    summary = []
    if preferred_keys and isinstance(preferred_keys[0], tuple):
        return summarize_table_row(first_row, list(preferred_keys))[:4]
    for key in preferred_keys:
        key_text = str(key).lower()
        if key_text not in first_row:
            continue
        label = str(key).upper() if key_text == "n50" else str(key).replace("_", " ").title()
        summary.append({"label": label, "value": str(first_row[key_text]), "tone": "info"})
    return summary[:4]


def build_generic_summary(
    archetype: str,
    rows: list[dict[str, Any]],
    artifacts: list[dict],
    *,
    tool_id: str = "",
) -> list[dict[str, Any]]:
    available_count = len([item for item in artifacts if item.get("available")])
    if archetype == "taxonomy_profile":
        first_row = rows[0] if rows else {}
        lookup = row_lookup(first_row)
        top_name = (
            lookup.get("name")
            or lookup.get("clade_name")
            or lookup.get("taxonomy")
            or lookup.get("classification")
            or "—"
        )
        top_value = (
            lookup.get("percentage")
            or lookup.get("fraction_total_reads")
            or lookup.get("relative_abundance")
            or lookup.get("abundance")
            or "—"
        )
        return [
            {"label": "分类记录", "value": str(len(rows)), "tone": "primary"},
            {"label": "Top 分类", "value": str(top_name), "tone": "accent"},
            {"label": "Top 丰度", "value": str(top_value), "tone": "info"},
            {"label": "结果文件", "value": str(available_count), "tone": "success"},
        ]

    if archetype == "quality_assessment":
        summary = summarize_metric_rows(rows, QUALITY_SUMMARY_KEYS.get(tool_id, []))
        if summary:
            summary.append({"label": "结果文件", "value": str(available_count), "tone": "info"})
            return summary[:4]
        return [
            {"label": "质量记录", "value": str(len(rows)), "tone": "primary"},
            {"label": "结果文件", "value": str(available_count), "tone": "info"},
        ]

    if archetype == "qc_report":
        first_row = rows[0] if rows else {}
        lookup = row_lookup(first_row)
        preferred_keys = ("total_reads", "host_reads", "non_host_reads", "host_fraction")
        summary = []
        labels = {
            "total_reads": "总 Reads",
            "host_reads": "宿主 Reads",
            "non_host_reads": "非宿主 Reads",
            "host_fraction": "宿主占比",
        }
        for key in preferred_keys:
            if key in lookup:
                summary.append({"label": labels[key], "value": str(lookup[key]), "tone": "info"})
        if summary:
            return summary[:4]
        return [
            {"label": "结果文件", "value": str(available_count), "tone": "primary"},
            {"label": "统计记录", "value": str(len(rows)), "tone": "info"},
        ]

    if archetype == "annotation_table":
        return [
            {"label": "结果条目", "value": str(len(rows)), "tone": "primary"},
            {"label": "结果文件", "value": str(available_count), "tone": "info"},
        ]

    return [
        {"label": "结果文件", "value": str(available_count), "tone": "primary"},
        {"label": "结果记录", "value": str(len(rows)), "tone": "info"},
    ]


def build_taxonomy_charts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    name_candidates = ("name", "clade_name", "taxonomy", "classification")
    value_candidates = ("percentage", "fraction_total_reads", "relative_abundance", "abundance", "reads", "new_est_reads")
    first_lookup = row_lookup(rows[0])
    name_key = next((key for key in name_candidates if key in first_lookup), "")
    value_key = next((key for key in value_candidates if key in first_lookup), "")
    if not name_key or not value_key:
        return []
    chart_rows = []
    for row in rows[:20]:
        lookup = row_lookup(row)
        numeric = parse_float(lookup.get(value_key))
        if numeric is None:
            continue
        if "fraction" in value_key and numeric <= 1:
            numeric *= 100
        chart_rows.append({"name": str(lookup.get(name_key) or "—"), "value": round(numeric, 4)})
    if not chart_rows:
        return []
    return [{"type": "abundance_bar", "title": "分类丰度", "data": chart_rows}]
