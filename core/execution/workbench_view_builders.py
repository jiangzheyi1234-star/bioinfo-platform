"""Workbench view builders extracted from ToolBridgeService.

Keep this module Qt-free and focused on deterministic data shaping so it can
be unit-tested independently from remote I/O and orchestration concerns.
"""

from __future__ import annotations

import copy

from core.execution.result_parsers import build_multiplex_columns, parse_multiplex_result_text, parse_primer_result_text


def build_primer_view(
    *,
    base_view: dict,
    primer_result_final_2_text: str,
    all_candidates_count: int,
    filtered_count: int,
    dimer_count: int,
    description: str,
    status: dict,
    parameters: list[dict],
    artifacts: list[dict],
    remote_result_dir: str,
) -> dict | None:
    rows = parse_primer_result_text(primer_result_final_2_text)
    if not rows:
        return None

    view = copy.deepcopy(base_view)
    view["description"] = description
    view["status"] = status
    view["parameters"] = parameters
    view["summary"] = [
        {"label": "目标病原体", "value": str(len(rows)), "tone": "primary"},
        {"label": "候选引物对", "value": str(all_candidates_count), "tone": "info"},
        {"label": "通过二聚体过滤", "value": str(filtered_count), "tone": "success"},
        {"label": "二聚体分析记录", "value": str(dimer_count), "tone": "accent"},
    ]
    view["rows"] = rows
    view["artifacts"] = artifacts
    view["remote_result_dir"] = remote_result_dir
    return view


def build_multiplex_view(
    *,
    multiplex_panel_text: str,
    synthesis_count: int | None,
    optimization_count: int | None,
    description: str,
    status: dict,
    parameters: list[dict],
    artifacts: list[dict],
    remote_result_dir: str,
) -> dict | None:
    rows = parse_multiplex_result_text(multiplex_panel_text)
    if not rows:
        return None

    valid_rows = [r for r in rows if r.get("pool_id") != "no_candidate" and r.get("forward_primer", "").strip()]
    no_candidate_rows = [r for r in rows if r.get("pool_id") == "no_candidate" or not r.get("forward_primer", "").strip()]
    suboptimal_rows = [r for r in valid_rows if r.get("pool_status") == "suboptimal"]

    optimization_rounds = max((optimization_count or 1) - 1, 0)
    parameter_items = list(parameters)
    parameter_items.append(
        {
            "label": "优化轮次",
            "value": str(optimization_rounds),
            "description": "指算法为消解引物冲突并满足约束而进行的迭代次数；轮次越多表示优化过程越复杂，不代表结果更差。",
        }
    )

    total_pathogens = len(rows)
    coverage_str = f"{len(valid_rows)}/{total_pathogens}"
    coverage_tone = "success" if len(valid_rows) == total_pathogens else "warning"

    all_tms: list[float] = []
    all_amplicon_lengths: list[int] = []
    for r in valid_rows:
        for k in ("tm_f", "tm_r"):
            try:
                all_tms.append(float(r.get(k) or 0))
            except ValueError:
                pass
        try:
            al = int(r.get("amplicon_length") or 0)
            if al > 0:
                all_amplicon_lengths.append(al)
        except ValueError:
            pass

    summary = [
        {"label": "入池病原体", "value": coverage_str, "tone": coverage_tone},
        {"label": "订单条目", "value": str(max((synthesis_count or 1) - 1, 0)), "tone": "primary"},
    ]
    if suboptimal_rows:
        summary.append({"label": "需验证", "value": str(len(suboptimal_rows)), "tone": "warning"})
    else:
        summary.append({"label": "质量", "value": "全部 optimal", "tone": "success"})

    if all_tms:
        tm_min = min(all_tms)
        tm_max = max(all_tms)
        tm_mean = sum(all_tms) / len(all_tms)
        summary.append({"label": "Tm 范围", "value": f"{tm_min:.1f}-{tm_max:.1f}℃", "tone": "accent"})
        parameter_items.append(
            {
                "label": "推荐退火温度",
                "value": f"{tm_mean - 5:.1f}℃",
                "description": f"基于池内引物平均 Tm ({tm_mean:.1f}℃) 减 5℃ 计算。实际需根据聚合酶和缓冲体系微调。",
            }
        )
    else:
        summary.append({"label": "优化轮次", "value": str(optimization_rounds), "tone": "accent"})

    if all_amplicon_lengths:
        parameter_items.append(
            {
                "label": "扩增子范围",
                "value": f"{min(all_amplicon_lengths)}-{max(all_amplicon_lengths)} bp",
                "description": "池内扩增子长度的最小-最大范围。差异越大越利于凝胶电泳区分。",
            }
        )
    if suboptimal_rows:
        subopt_names = ", ".join(r.get("pathogen", "") for r in suboptimal_rows[:5])
        suffix = f" 等 {len(suboptimal_rows)} 个" if len(suboptimal_rows) > 5 else ""
        parameter_items.append(
            {
                "label": "需实验验证",
                "value": subopt_names + suffix,
                "description": "这些病原体的引物在池优化中存在轻微冲突（二聚体/Tm偏差/长度重叠），建议通过调整退火温度或引物浓度在实验端验证。",
            }
        )

    chart_data = None
    if valid_rows:
        chart_items = []
        for r in rows:
            pathogen = r.get("pathogen", "")
            try:
                amp_len = int(r.get("amplicon_length") or 0)
            except ValueError:
                amp_len = 0
            row_status = r.get("pool_status", "optimal")
            if r.get("pool_id") == "no_candidate" or not r.get("forward_primer", "").strip():
                row_status = "no_candidate"
                amp_len = 0
            chart_items.append(
                {
                    "name": pathogen,
                    "value": amp_len,
                    "status": row_status,
                    "region_id": r.get("region_id", ""),
                }
            )
        chart_data = {
            "type": "bar",
            "title": "扩增子长度分布",
            "data": chart_items,
        }

    return {
        "tool_ids": ["multiplex_primer_panel"],
        "title": "多重引物池设计",
        "description": description,
        "status": status,
        "parameters": parameter_items,
        "summary": summary,
        "columns": build_multiplex_columns(rows),
        "rows": rows,
        "chart": chart_data,
        "artifacts": artifacts,
        "remote_result_dir": remote_result_dir,
    }
