"""检测结果合并器 — 合并 Kraken2/Centrifuge kreport 与 BLAST 结果。

Core 层（无 Qt 依赖）。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DetectionMerger:
    """合并 kreport 解析结果与 BLAST 物种汇总。"""

    @staticmethod
    def merge(
        kreport_species: list[dict[str, Any]],
        blast_species: list[dict[str, Any]] | None = None,
        *,
        classifier_name: str = "Classifier",
    ) -> list[dict[str, Any]]:
        """合并两个来源的物种列表，按 reads 降序。

        Args:
            kreport_species: ChartDataParser.parse_kreport() 输出的 data 列表
                [{"name": str, "value": float, "reads": int}, ...]
            blast_species: BlastResultParser.parse() 输出
                [{"name": str, "contigs": int, "reads": int, ...}, ...]
            classifier_name: 分类器名称（"Centrifuge" 或 "Kraken2"），
                用于 source 标记

        Returns:
            [{"name": str, "reads": int, "percentage": float,
              "source": "<classifier>"|"BLAST"|"Both",
              "contigs": int|None, "avg_identity": float|None,
              "best_evalue": float|None}, ...]
        """
        merged: dict[str, dict] = {}

        # 1) 添加 kreport 数据
        for item in kreport_species:
            name = item.get("name", "").strip()
            if not name:
                continue
            merged[name] = {
                "name": name,
                "reads": item.get("reads", 0),
                "percentage": item.get("value", 0.0),
                "source": classifier_name,
                "contigs": None,
                "avg_identity": None,
                "best_evalue": None,
            }

        # 2) 合并 BLAST 数据
        if blast_species:
            for item in blast_species:
                name = item.get("name", "").strip()
                if not name:
                    continue
                blast_reads = item.get("reads", 0)

                if name in merged:
                    # 同名物种 — 来源标记为 Both，reads 取较大值
                    entry = merged[name]
                    entry["source"] = "Both"
                    entry["contigs"] = item.get("contigs")
                    entry["avg_identity"] = item.get("avg_identity")
                    entry["best_evalue"] = item.get("best_evalue")
                else:
                    # BLAST 独有物种
                    merged[name] = {
                        "name": name,
                        "reads": blast_reads,
                        "percentage": 0.0,
                        "source": "BLAST",
                        "contigs": item.get("contigs"),
                        "avg_identity": item.get("avg_identity"),
                        "best_evalue": item.get("best_evalue"),
                    }

        result = list(merged.values())
        result.sort(key=lambda x: x["reads"], reverse=True)
        return result
