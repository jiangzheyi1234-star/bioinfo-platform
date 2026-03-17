"""BLAST outfmt 6 结果解析器 — 解析 BLASTn TSV 输出为物种汇总。

Core 层（无 Qt 依赖）。

outfmt 6 默认列：
  qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore

当使用 -outfmt '6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore stitle'
时会多出 stitle 列，从中提取物种信息。
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 从 BLAST hit title 中提取物种名（常见格式：genus species 后跟描述）
_SPECIES_RE = re.compile(
    r"^(?:\S+\s+)?([A-Z][a-z]+ [a-z]+)"  # 属名 + 种名
)


class BlastResultParser:
    """解析 BLASTn outfmt 6 TSV → 物种汇总列表。"""

    @staticmethod
    def parse(
        blast_tsv_path: str,
        *,
        identity_threshold: float = 80.0,
        evalue_threshold: float = 1e-5,
        min_alignment_length: int = 100,
        top_n: int = 50,
    ) -> list[dict[str, Any]]:
        """解析 BLAST TSV 输出，返回按 contigs 数降序的物种列表。

        Args:
            blast_tsv_path: BLAST outfmt 6/7 TSV 文件路径
            identity_threshold: 最低 identity% 过滤（默认 80%，
                物种级鉴定建议 ≥90%，属级 ≥80%）
            evalue_threshold: 最大 e-value 过滤
            min_alignment_length: 最短比对长度（bp），过滤短片段假阳性
            top_n: 返回前 N 个物种

        Returns:
            [{"name": str, "contigs": int, "reads": int,
              "avg_identity": float, "avg_length": float,
              "best_evalue": float, "source": "BLAST"}, ...]
        """
        path = Path(blast_tsv_path)
        if not path.exists():
            logger.warning("BLAST 结果文件不存在: %s", blast_tsv_path)
            return []

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.error("读取 BLAST TSV 失败: %s — %s", blast_tsv_path, exc)
            return []

        # 按 query 取最佳 hit（最高 bitscore）
        best_hits: dict[str, dict] = {}  # qseqid → best hit dict

        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 12:
                continue

            qseqid = parts[0]
            sseqid = parts[1]
            try:
                pident = float(parts[2])
                length = int(parts[3])
                evalue = float(parts[10])
                bitscore = float(parts[11])
            except (ValueError, IndexError):
                continue

            if pident < identity_threshold or evalue > evalue_threshold:
                continue
            if length < min_alignment_length:
                continue

            # 提取物种名
            species = BlastResultParser._extract_species(parts, sseqid)
            if not species:
                continue

            prev = best_hits.get(qseqid)
            if prev is None or bitscore > prev["bitscore"]:
                best_hits[qseqid] = {
                    "species": species,
                    "pident": pident,
                    "length": length,
                    "evalue": evalue,
                    "bitscore": bitscore,
                }

        # 按物种汇总
        species_agg: dict[str, dict] = {}
        for hit in best_hits.values():
            sp = hit["species"]
            if sp not in species_agg:
                species_agg[sp] = {
                    "name": sp,
                    "contigs": 0,
                    "identity_sum": 0.0,
                    "length_sum": 0,
                    "best_evalue": hit["evalue"],
                }
            agg = species_agg[sp]
            agg["contigs"] += 1
            agg["identity_sum"] += hit["pident"]
            agg["length_sum"] += hit["length"]
            if hit["evalue"] < agg["best_evalue"]:
                agg["best_evalue"] = hit["evalue"]

        result = []
        for agg in species_agg.values():
            n = agg["contigs"]
            result.append({
                "name": agg["name"],
                "contigs": n,
                "reads": n,  # 估算：1 contig ≈ 1 read（粗估）
                "avg_identity": round(agg["identity_sum"] / n, 2),
                "avg_length": round(agg["length_sum"] / n, 1),
                "best_evalue": agg["best_evalue"],
                "source": "BLAST",
            })

        result.sort(key=lambda x: x["contigs"], reverse=True)
        return result[:top_n]

    @staticmethod
    def _extract_species(parts: list[str], sseqid: str) -> str:
        """从 BLAST hit 中提取物种名。优先用 stitle（第 13 列），fallback 到 sseqid。"""
        # 尝试 stitle（列索引 12+）
        if len(parts) > 12:
            stitle = " ".join(parts[12:]).strip()
            m = _SPECIES_RE.search(stitle)
            if m:
                return m.group(1)
            # stitle 可能不含标准格式，取前两个词作为属+种
            words = stitle.split()
            if len(words) >= 2 and words[0][0].isupper():
                return f"{words[0]} {words[1]}"

        # fallback：从 sseqid 提取（如 gi|xxx|ref|NR_xxx| Genus species）
        if "|" in sseqid:
            tail = sseqid.split("|")[-1].strip()
            if tail:
                m = _SPECIES_RE.search(tail)
                if m:
                    return m.group(1)

        return ""
