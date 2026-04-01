from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def generate_targeted_seq_report(
    summary: dict,
    species_list: list[dict],
    output_dir: Path,
    *,
    classifier_name: str = "Classifier",
) -> Path | None:
    """生成靶向测序病原体检测报告 .txt 文件（UTF-8 BOM）。"""
    total = summary.get("total_reads", 0)
    classified = summary.get("classified_reads", 0)
    unclassified = summary.get("unclassified_reads", 0)
    pct = f"{classified / total * 100:.1f}" if total > 0 else "0.0"
    unpct = f"{unclassified / total * 100:.1f}" if total > 0 else "0.0"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "=" * 52,
        "        靶向测序病原体检测报告",
        "=" * 52,
        f"生成时间：{now}",
        f"分类工具：{classifier_name}",
        f"总 Reads：{total:,}",
        f"已分类：{classified:,} ({pct}%)",
        f"未分类：{unclassified:,} ({unpct}%)",
        f"检出物种数：{summary.get('species_count', 0)}",
    ]

    domains = summary.get("domain_breakdown", [])
    if domains:
        lines.append("")
        lines.append("域级别分布：")
        for d in domains:
            lines.append(f"  {d['name']:<20}{d['reads']:>10,}  ({d['percentage']:.2f}%)")

    lines.extend([
        "",
        f"{'序号':<6}{'病原体名称':<30}{'Reads数':<12}{'占比(%)':<10}",
        "-" * 58,
    ])
    for i, item in enumerate(species_list, 1):
        name = item.get("name", "")
        reads = item.get("reads", 0)
        value = item.get("value", 0)
        lines.append(f"{i:<6}{name:<30}{reads:<12,}{value:<10.2f}")

    lines.extend([
        "=" * 52,
        "",
        "注意事项：",
        "  1. 本报告由 H2OMeta 平台自动生成，仅供科研参考。",
        "  2. 低丰度物种（<1%）可能为环境或试剂污染，需结合阴性对照判断。",
        "  3. 临床诊断需结合患者症状、流行病学史及其他实验室检测结果。",
        "  4. 物种名称遵循 NCBI Taxonomy 命名体系。",
    ])

    report_path = output_dir / "targeted_seq_report.txt"
    try:
        report_path.write_text(
            "\n".join(lines) + "\n", encoding="utf-8-sig",
        )
        return report_path
    except Exception:
        logger.exception("生成靶向测序报告失败: %s", report_path)
        return None


def try_load_blast_results(
    sample_id: str,
    current_exec_id: str,
    *,
    get_project_manager: Callable[[], Any],
    execution_results_dir: Callable[[str], Path | None],
) -> list[dict] | None:
    """查找同样品最新的 blastn 执行结果，解析并返回。"""
    from core.pipeline.blast_result_parser import BlastResultParser

    pm = get_project_manager()
    if pm is None or pm.current_project is None:
        return None

    try:
        row = pm.db.execute(
            "SELECT execution_id FROM executions "
            "WHERE sample_id = ? AND tool_id = 'blastn' AND status = 'completed' "
            "ORDER BY rowid DESC LIMIT 1",
            (sample_id,),
        ).fetchone()
    except Exception:
        return None

    if not row:
        return None

    blast_exec_id = row["execution_id"]
    results_dir = execution_results_dir(blast_exec_id)
    if results_dir is None:
        return None

    blast_tsv = results_dir / f"{sample_id}_blast.tsv"
    if not blast_tsv.exists():
        return None

    return BlastResultParser.parse(str(blast_tsv))


def generate_detection_pdf(
    summary: dict,
    kreport_species: list[dict],
    output_dir: Path,
    remote_dir: str,
    sample_id: str,
    execution_id: str,
    *,
    classifier_name: str = "Classifier",
    get_project_manager: Callable[[], Any],
    execution_results_dir: Callable[[str], Path | None],
) -> Path | None:
    """生成病原体检测 PDF 报告，尝试合并 BLAST 结果。"""
    from core.pipeline.detection_merger import DetectionMerger
    from core.pipeline.report_generator import ReportGenerator

    blast_species = try_load_blast_results(
        sample_id,
        execution_id,
        get_project_manager=get_project_manager,
        execution_results_dir=execution_results_dir,
    )

    merged = DetectionMerger.merge(
        kreport_species, blast_species, classifier_name=classifier_name,
    )
    if not merged:
        return None

    pm = get_project_manager()
    project_name = ""
    sample_name = sample_id
    if pm and pm.current_project:
        project_name = pm.current_project.name or ""
        try:
            row = pm.db.execute(
                "SELECT name FROM samples WHERE sample_id = ? LIMIT 1",
                (sample_id,),
            ).fetchone()
            if row:
                sample_name = row["name"] or sample_id
        except Exception:
            pass

    analysis_method = f"{classifier_name} + BLASTn" if blast_species else classifier_name
    pdf_path = output_dir / "detection_report.pdf"
    return ReportGenerator.generate_detection_report(
        species_list=merged,
        summary=summary,
        output_path=str(pdf_path),
        project_name=project_name,
        sample_name=sample_name,
        analysis_method=analysis_method,
    )
