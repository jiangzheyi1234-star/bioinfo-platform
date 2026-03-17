"""图表数据解析器 — 将工具输出文件解析为 ECharts 可用的数据结构。

Core 层（允许 QtCore，禁止 QtWidgets）。

支持格式:
  - fastp JSON report → QC 统计柱状图数据
  - Kraken2/Centrifuge kreport → 分类学组成饼图/树图数据

kreport 格式说明（Kraken2 / Centrifuge 共用）:
  列：percentage | clade_reads | direct_reads | rank_code | taxid | scientific_name
  rank_code: U=未分类, R=根(Kraken2), -=无级(Centrifuge root, taxid=1),
             D=域, P=门, C=纲, O=目, F=科, G=属, S=种, S1/S2=亚种/株
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChartDataParser:
    """图表数据解析器（全部为静态方法，无状态）"""

    # ── fastp JSON ─────────────────────────────────────────────

    @staticmethod
    def parse_fastp_json(json_path: str) -> dict[str, Any]:
        """解析 fastp JSON 报告，返回 ECharts 柱状图数据。

        Args:
            json_path: fastp 生成的 .json 文件路径（本地或内容字符串）

        Returns:
            {
              "type": "bar",
              "title": "fastp 质控统计",
              "categories": [...],
              "series": [{"name": ..., "data": [...]}]
            }
        """
        try:
            text = Path(json_path).read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception as e:
            logger.error("解析 fastp JSON 失败: %s — %s", json_path, e)
            return ChartDataParser._empty_chart("fastp 质控统计")

        summary = data.get("summary", {})
        before = summary.get("before_filtering", {})
        after = summary.get("after_filtering", {})

        def fmt_m(n: int) -> float:
            return round(n / 1_000_000, 2)

        categories = ["总 reads", "总碱基(Mb)", "Q20 率(%)", "Q30 率(%)", "GC 含量(%)"]
        before_vals = [
            fmt_m(before.get("total_reads", 0)),
            fmt_m(before.get("total_bases", 0)),
            round(before.get("q20_rate", 0) * 100, 2),
            round(before.get("q30_rate", 0) * 100, 2),
            round(before.get("gc_content", 0) * 100, 2),
        ]
        after_vals = [
            fmt_m(after.get("total_reads", 0)),
            fmt_m(after.get("total_bases", 0)),
            round(after.get("q20_rate", 0) * 100, 2),
            round(after.get("q30_rate", 0) * 100, 2),
            round(after.get("gc_content", 0) * 100, 2),
        ]

        return {
            "type": "bar",
            "title": "fastp 质控统计",
            "categories": categories,
            "series": [
                {"name": "过滤前", "data": before_vals, "color": "#5470c6"},
                {"name": "过滤后", "data": after_vals, "color": "#91cc75"},
            ],
        }

    # ── Kraken2/Centrifuge kreport ─────────────────────────────

    # 物种及亚种级别的 rank code（S=species, S1=subspecies, S2=strain …）
    _SPECIES_RANKS = {"S", "S1", "S2", "S3"}

    @staticmethod
    def parse_kreport(kreport_path: str, top_n: int = 20) -> dict[str, Any]:
        """解析 Kraken2/Centrifuge kreport，返回 ECharts 饼图数据。

        kreport 格式（tab 分隔）:
          percentage | clade_reads | direct_reads | rank_code | taxid | scientific_name

        物种级别取 S（species）、S1（subspecies）、S2（strain）；
        亚种/株级 reads 已包含在父级 S 的 clade_reads 中，因此仅在
        父级 S 缺失时才计入亚种条目，避免重复计数。

        Args:
            kreport_path: kreport 文件路径
            top_n: 取前 N 个物种（其余归入「其他」）

        Returns:
            {"type": "pie", "title": "物种组成", "data": [...]}
        """
        species: list[dict[str, Any]] = []
        seen_species_names: set[str] = set()

        try:
            lines = Path(kreport_path).read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.error("读取 kreport 失败: %s — %s", kreport_path, e)
            return ChartDataParser._empty_chart("物种组成")

        for line in lines:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            pct_str, clade_str, direct_str, rank, _, name = parts[:6]
            if rank not in ChartDataParser._SPECIES_RANKS:
                continue
            try:
                pct = float(pct_str.strip())
                clade = int(clade_str.strip())
            except ValueError:
                continue
            if pct < 0.01:
                continue

            clean_name = name.strip().lstrip()

            # 对于亚种/株 (S1/S2/S3)，检查其父级种是否已存在
            # 父级种的 clade_reads 已包含亚种 reads，跳过避免重复
            if rank != "S":
                parent_genus_species = " ".join(clean_name.split()[:2])
                if parent_genus_species in seen_species_names:
                    continue

            if rank == "S":
                seen_species_names.add(clean_name)

            species.append({
                "name": clean_name,
                "value": round(pct, 4),
                "reads": clade,
            })

        # 取 top_n，其余归入「其他」
        species.sort(key=lambda x: x["value"], reverse=True)
        top = species[:top_n]
        others_pct = sum(s["value"] for s in species[top_n:])
        others_reads = sum(s["reads"] for s in species[top_n:])
        if others_pct > 0:
            top.append({"name": "其他", "value": round(others_pct, 4), "reads": others_reads})

        return {
            "type": "pie",
            "title": "物种组成",
            "data": [{"name": s["name"], "value": s["value"], "reads": s["reads"]} for s in top],
        }

    @staticmethod
    def parse_kreport_summary(kreport_path: str) -> dict[str, Any]:
        """解析 kreport 摘要信息。

        Returns:
            {
              "total_reads": int,
              "classified_reads": int,
              "unclassified_reads": int,
              "species_count": int,
              "top_species": str,
              "domain_breakdown": [{"name": str, "reads": int, "percentage": float}, ...]
            }
        """
        total_reads = 0
        classified_reads = 0
        unclassified_reads = 0
        species_count = 0
        top_species = ""
        domains: list[dict[str, Any]] = []

        try:
            lines = Path(kreport_path).read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.error("读取 kreport 摘要失败: %s — %s", kreport_path, e)
            return {"total_reads": 0, "classified_reads": 0,
                    "unclassified_reads": 0, "species_count": 0,
                    "top_species": "N/A", "domain_breakdown": []}

        best_pct = -1.0
        root_reads = 0
        for line in lines:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            pct_str, clade_str, _, rank, taxid, name = parts[:6]
            try:
                pct = float(pct_str.strip())
                clade = int(clade_str.strip())
            except ValueError:
                continue
            if rank == "U":
                unclassified_reads = clade
            elif rank == "R" or (taxid.strip() == "1" and "root" in name.lower()):
                root_reads = clade
            # 域级别统计（Bacteria, Viruses, Eukaryota, Archaea）
            if rank == "D" and pct >= 0.01:
                domains.append({
                    "name": name.strip().lstrip(),
                    "reads": clade,
                    "percentage": round(pct, 2),
                })
            if rank in ChartDataParser._SPECIES_RANKS and pct > best_pct:
                best_pct = pct
                top_species = name.strip()
            if rank in ChartDataParser._SPECIES_RANKS and pct >= 0.01:
                species_count += 1

        classified_reads = root_reads
        total_reads = root_reads + unclassified_reads
        domains.sort(key=lambda x: x["reads"], reverse=True)

        return {
            "total_reads": total_reads,
            "classified_reads": classified_reads,
            "unclassified_reads": unclassified_reads,
            "species_count": species_count,
            "top_species": top_species or "N/A",
            "domain_breakdown": domains,
        }

    @staticmethod
    def parse_kreport_tree(kreport_path: str) -> dict[str, Any]:
        """解析 Kraken2 kreport，返回 ECharts 树图（sunburst）数据。

        Returns:
            {
              "type": "sunburst",
              "title": "物种分类层级",
              "data": [...]   # ECharts sunburst 格式
            }
        """
        RANK_ORDER = {"D": 0, "P": 1, "C": 2, "O": 3, "F": 4, "G": 5, "S": 6}
        nodes: list[dict] = []

        try:
            lines = Path(kreport_path).read_text(encoding="utf-8").splitlines()
        except Exception as e:
            logger.error("读取 kreport 失败: %s — %s", kreport_path, e)
            return ChartDataParser._empty_chart("物种分类层级")

        for line in lines:
            parts = line.strip().split("\t")
            if len(parts) < 6:
                continue
            pct_str, _, _, rank, taxid, name = parts[:6]
            if rank not in RANK_ORDER:
                continue
            try:
                pct = float(pct_str.strip())
            except ValueError:
                continue
            if pct < 0.1:
                continue
            nodes.append({
                "name": name.strip().lstrip(),
                "value": round(pct, 3),
                "rank": rank,
                "taxid": taxid,
                "depth": RANK_ORDER[rank],
            })

        # 简单层级组装（仅到属级）：按 depth 归组
        if not nodes:
            return ChartDataParser._empty_chart("物种分类层级")

        return {
            "type": "sunburst",
            "title": "物种分类层级",
            "data": _build_sunburst_tree(nodes),
        }

    @staticmethod
    def _empty_chart(title: str) -> dict[str, Any]:
        return {"type": "empty", "title": title, "data": [], "series": []}


# ── 辅助函数 ─────────────────────────────────────────────────────


def _build_sunburst_tree(nodes: list[dict]) -> list[dict]:
    """将扁平节点列表组装为 ECharts sunburst 树结构（简化版）"""
    # 按深度分组
    by_depth: dict[int, list[dict]] = {}
    for n in nodes:
        by_depth.setdefault(n["depth"], []).append(n)

    if not by_depth:
        return []

    # 只取前三层（Domain → Phylum → Class）
    depths = sorted(by_depth.keys())[:3]

    # 根节点（Domain 层）
    roots: list[dict] = []
    for root_node in by_depth.get(depths[0], []):
        item: dict = {"name": root_node["name"], "value": root_node["value"], "children": []}
        # 子层（Phylum）
        if len(depths) > 1:
            for child_node in by_depth.get(depths[1], []):
                child: dict = {"name": child_node["name"], "value": child_node["value"], "children": []}
                # 孙层（Class）
                if len(depths) > 2:
                    for gc in by_depth.get(depths[2], []):
                        child["children"].append({
                            "name": gc["name"],
                            "value": gc["value"],
                        })
                item["children"].append(child)
        roots.append(item)

    return roots
