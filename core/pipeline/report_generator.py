"""PDF 病原体检测报告生成器 — matplotlib PdfPages 实现。

Core 层（无 Qt 依赖）。
依赖：matplotlib（已在项目环境中）。

中文字体回退链：Microsoft YaHei → SimHei → sans-serif。
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 调色板（独立于 UI 层）
_PALETTE = [
    "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de",
    "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc", "#48b8d0",
]


def _setup_matplotlib():
    """配置 matplotlib 后端和中文字体。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    # 中文字体回退
    for font in ("Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC"):
        try:
            from matplotlib.font_manager import FontProperties
            fp = FontProperties(family=font)
            if fp.get_name() != font:
                continue
            plt.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue
    else:
        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

    return plt, PdfPages


class ReportGenerator:
    """病原体检测 PDF 报告生成器。"""

    @staticmethod
    def generate_detection_report(
        species_list: list[dict[str, Any]],
        summary: dict[str, Any],
        output_path: str,
        project_name: str = "",
        sample_name: str = "",
        analysis_method: str = "Kraken2 + BLASTn",
    ) -> Path | None:
        """生成完整的检测 PDF 报告。

        Args:
            species_list: DetectionMerger.merge() 输出的合并物种列表
            summary: ChartDataParser.parse_kreport_summary() 输出
            output_path: PDF 输出路径
            project_name: 项目名称
            sample_name: 样品名称
            analysis_method: 分析方法描述

        Returns:
            生成的 PDF 文件 Path，失败返回 None
        """
        try:
            plt, PdfPages = _setup_matplotlib()
        except Exception as exc:
            logger.error("matplotlib 初始化失败: %s", exc)
            return None

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            with PdfPages(str(output)) as pdf:
                ReportGenerator._page_cover(
                    plt, pdf, project_name, sample_name, analysis_method
                )
                ReportGenerator._page_overview(
                    plt, pdf, species_list, summary
                )
                ReportGenerator._page_species_table(
                    plt, pdf, species_list
                )
                # BLAST 补充详情页（仅当有 BLAST 独有物种时）
                blast_only = [s for s in species_list if s.get("source") == "BLAST"]
                if blast_only:
                    ReportGenerator._page_blast_detail(plt, pdf, blast_only)
                ReportGenerator._page_methods(
                    plt, pdf, analysis_method, summary
                )
            logger.info("PDF 报告已生成: %s", output)
            return output
        except Exception as exc:
            logger.error("生成 PDF 报告失败: %s", exc)
            return None

    # ── 第 1 页：封面 ──────────────────────────────────────────

    @staticmethod
    def _page_cover(plt, pdf, project_name, sample_name, analysis_method):
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # 顶部色带
        ax.fill_between([0, 1], [0.92, 0.92], [1, 1], color="#5470c6", alpha=0.9)
        ax.text(0.5, 0.96, "H2OMeta", ha="center", va="center",
                fontsize=14, color="white", weight="bold")

        # 标题
        ax.text(0.5, 0.65, "病原体检测报告", ha="center", va="center",
                fontsize=32, weight="bold", color="#1e293b")

        # 信息块
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        info_lines = [
            f"项目名称：{project_name or '未命名项目'}",
            f"样品名称：{sample_name or '未命名样品'}",
            f"分析方法：{analysis_method}",
            f"生成时间：{now}",
        ]
        y = 0.48
        for line in info_lines:
            ax.text(0.5, y, line, ha="center", va="center",
                    fontsize=13, color="#475569")
            y -= 0.045

        # 底部
        ax.text(0.5, 0.08, "—— 由 H2OMeta 宏基因组分析平台自动生成 ——",
                ha="center", va="center", fontsize=10, color="#94a3b8")

        pdf.savefig(fig)
        plt.close(fig)

    # ── 第 2 页：总览 + 饼图 ──────────────────────────────────

    @staticmethod
    def _page_overview(plt, pdf, species_list, summary):
        fig, axes = plt.subplots(2, 1, figsize=(8.27, 11.69),
                                 gridspec_kw={"height_ratios": [1, 2.5]})

        # 上方：摘要卡片文字
        ax_top = axes[0]
        ax_top.axis("off")
        total = summary.get("total_reads", 0)
        classified = summary.get("classified_reads", 0)
        sp_count = summary.get("species_count", 0)
        top_sp = summary.get("top_species", "N/A")
        pct = f"{classified / total * 100:.1f}%" if total > 0 else "0%"

        cards = [
            ("总 Reads", f"{total:,}"),
            ("已分类 Reads", f"{classified:,} ({pct})"),
            ("检出物种数", str(sp_count)),
            ("Top 物种", top_sp),
        ]
        for i, (label, value) in enumerate(cards):
            x = 0.12 + i * 0.22
            ax_top.text(x, 0.65, label, ha="center", fontsize=10, color="#64748b")
            ax_top.text(x, 0.35, value, ha="center", fontsize=12,
                        weight="bold", color="#1e293b")

        # 下方：饼图（Top 20）
        ax_pie = axes[1]
        if not species_list:
            ax_pie.text(0.5, 0.5, "无物种数据", ha="center", va="center",
                        fontsize=14, color="#94a3b8")
            ax_pie.axis("off")
        else:
            top20 = species_list[:20]
            names = [s["name"] for s in top20]
            values = [max(s.get("reads", 0), 1) for s in top20]
            colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(top20))]

            wedges, texts = ax_pie.pie(
                values, labels=None, colors=colors,
                startangle=90, counterclock=False,
                wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
            )
            ax_pie.set_title("物种组成（Top 20）", fontsize=14, weight="bold", pad=15)

            # 图例放右侧
            legend_labels = [
                f"{n} ({v:,})" for n, v in zip(names, values)
            ]
            ax_pie.legend(
                wedges, legend_labels,
                loc="center left", bbox_to_anchor=(1.05, 0.5),
                fontsize=7, frameon=False,
            )

        fig.tight_layout(pad=2.0)
        pdf.savefig(fig)
        plt.close(fig)

    # ── 第 3 页：物种表格 ─────────────────────────────────────

    @staticmethod
    def _page_species_table(plt, pdf, species_list):
        rows_per_page = 35
        total_rows = len(species_list)
        page = 0

        while page * rows_per_page < max(total_rows, 1):
            start = page * rows_per_page
            end = min(start + rows_per_page, total_rows)
            chunk = species_list[start:end]

            fig = plt.figure(figsize=(8.27, 11.69))
            ax = fig.add_axes([0.05, 0.05, 0.9, 0.88])
            ax.axis("off")

            title = "合并物种表格"
            if total_rows > rows_per_page:
                title += f" ({page + 1}/{(total_rows - 1) // rows_per_page + 1})"
            ax.set_title(title, fontsize=14, weight="bold", pad=20)

            if not chunk:
                ax.text(0.5, 0.5, "无物种数据", ha="center", va="center",
                        fontsize=14, color="#94a3b8")
                pdf.savefig(fig)
                plt.close(fig)
                break

            # 表头
            col_labels = ["序号", "物种名称", "Reads 数", "占比(%)", "来源"]
            col_widths = [0.06, 0.40, 0.15, 0.12, 0.12]

            table_data = []
            for i, sp in enumerate(chunk, start + 1):
                reads = sp.get("reads", 0)
                pct = sp.get("percentage", 0.0)
                source = sp.get("source", "")
                table_data.append([
                    str(i),
                    sp.get("name", ""),
                    f"{reads:,}",
                    f"{pct:.2f}" if pct else "-",
                    source,
                ])

            table = ax.table(
                cellText=table_data,
                colLabels=col_labels,
                colWidths=col_widths,
                loc="upper center",
                cellLoc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            table.scale(1, 1.3)

            # 样式
            for (r, c), cell in table.get_celld().items():
                cell.set_edgecolor("#e2e8f0")
                if r == 0:
                    cell.set_facecolor("#5470c6")
                    cell.set_text_props(color="white", weight="bold")
                elif r % 2 == 0:
                    cell.set_facecolor("#f8fafc")
                # 物种名左对齐
                if c == 1:
                    cell.set_text_props(ha="left")

            pdf.savefig(fig)
            plt.close(fig)
            page += 1

    # ── BLAST 补充详情页 ──────────────────────────────────────

    @staticmethod
    def _page_blast_detail(plt, pdf, blast_only):
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0.05, 0.05, 0.9, 0.88])
        ax.axis("off")
        ax.set_title("BLAST 补充检出物种", fontsize=14, weight="bold", pad=20)

        col_labels = ["序号", "物种名称", "Contigs", "平均Identity%", "最佳E-value"]
        col_widths = [0.06, 0.38, 0.12, 0.18, 0.18]

        table_data = []
        for i, sp in enumerate(blast_only[:35], 1):
            identity = sp.get("avg_identity")
            evalue = sp.get("best_evalue")
            table_data.append([
                str(i),
                sp.get("name", ""),
                str(sp.get("contigs", 0)),
                f"{identity:.1f}" if identity is not None else "-",
                f"{evalue:.1e}" if evalue is not None else "-",
            ])

        table = ax.table(
            cellText=table_data,
            colLabels=col_labels,
            colWidths=col_widths,
            loc="upper center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.3)

        for (r, c), cell in table.get_celld().items():
            cell.set_edgecolor("#e2e8f0")
            if r == 0:
                cell.set_facecolor("#ee6666")
                cell.set_text_props(color="white", weight="bold")
            elif r % 2 == 0:
                cell.set_facecolor("#fff5f5")
            if c == 1:
                cell.set_text_props(ha="left")

        pdf.savefig(fig)
        plt.close(fig)

    # ── 尾页：方法说明 ────────────────────────────────────────

    @staticmethod
    def _page_methods(plt, pdf, analysis_method, summary):
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axis("off")

        ax.text(0.5, 0.95, "分析方法说明", ha="center", fontsize=16,
                weight="bold", color="#1e293b")

        lines = [
            f"分析方法：{analysis_method}",
            "",
            "软件与数据库：",
            "  - Centrifuge：基于 BWT 的超快速物种分类，适合自定义病原体数据库",
            "  - Kraken2：基于 k-mer 的快速物种分类，适合标准参考数据库",
            "  - BLASTn：核苷酸序列比对（NCBI core_nt 数据库），高灵敏度验证",
            "  - fastp：测序数据质控与过滤（接头去除、质量过滤）",
            "  - hostile：人类宿主序列去除（基于 Bowtie2/Minimap2）",
            "",
            "靶向测序分析流程：",
            "  1. 纳米孔 FASTQ 经 fastp 质控、hostile 去宿主后获得清洁 reads",
            "  2. 清洁 reads 通过分类器（Centrifuge/Kraken2）快速鉴定病原体组成",
            "  3. 未分类 reads 可进一步 de novo 组装 + BLASTn 比对补充鉴定",
            "  4. 合并分类和比对结果，生成最终病原体检测报告",
            "",
            f"总 Reads：{summary.get('total_reads', 0):,}",
            f"已分类 Reads：{summary.get('classified_reads', 0):,}",
            f"未分类 Reads：{summary.get('unclassified_reads', 0):,}",
            f"物种数：{summary.get('species_count', 0)}",
            "",
            "结果解读注意事项：",
            "  - 低丰度物种（占比<1%）可能为环境或试剂污染，需结合阴性对照",
            "  - 物种名称遵循 NCBI Taxonomy 标准命名体系",
            "  - 靶向测序使用特异性扩增子，reads 比例不直接等同于感染载量",
            "",
            "免责声明：",
            "  本报告由 H2OMeta 宏基因组分析平台自动生成，仅供科研参考。",
            "  临床诊断需结合患者症状、流行病学史及其他实验室检测结果。",
        ]

        y = 0.85
        for line in lines:
            ax.text(0.05, y, line, fontsize=10, color="#334155",
                    verticalalignment="top")
            y -= 0.035

        pdf.savefig(fig)
        plt.close(fig)
