"""图表控件 — 使用 matplotlib 渲染 fastp QC 和 Kraken2 物种图表。

接受 ChartDataParser 输出的通用数据字典:
  - type="bar"     → 分组柱状图（fastp 质控统计）
  - type="pie"     → 饼图（Kraken2 物种组成）
  - type="sunburst" → 嵌套饼图（物种分类层级）
  - type="empty"  → 空白占位图
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

# 懒导入 matplotlib（避免启动时阻塞）
_mpl_available = False
try:
    import matplotlib
    matplotlib.use("QtAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import numpy as np
    _mpl_available = True
except ImportError:
    logger.warning("matplotlib 未安装，图表控件将以占位模式运行")


# ── 颜色方案（与 styles.py 保持一致风格） ─────────────────────
_PALETTE = [
    "#5470c6", "#91cc75", "#fac858", "#ee6666",
    "#73c0de", "#3ba272", "#fc8452", "#9a60b4",
    "#ea7ccc", "#48b8af",
]
_BG_COLOR = "#FFFFFF"
_TEXT_COLOR = "#1D1D1F"
_GRID_COLOR = "#E5E5EA"


class ChartWidget(QWidget):
    """通用图表控件，根据 data_dict["type"] 自动选择图表类型。

    用法::

        widget = ChartWidget()
        widget.update_chart(ChartDataParser.parse_fastp_json(path))
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas: FigureCanvas | None = None
        self._figure: Figure | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        if not _mpl_available:
            lbl = QLabel("图表功能需要安装 matplotlib\n运行: pip install matplotlib")
            lbl.setStyleSheet("color: #8E8E93; font-size: 13px; padding: 24px;")
            self._layout.addWidget(lbl)
        else:
            self._init_canvas()

    def _init_canvas(self) -> None:
        self._figure = Figure(figsize=(6, 3.6), facecolor=_BG_COLOR, tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(self._canvas)

    def update_chart(self, data: dict[str, Any]) -> None:
        """更新图表数据并重绘。"""
        if not _mpl_available or self._figure is None:
            return

        self._figure.clear()
        chart_type = data.get("type", "empty")

        try:
            if chart_type == "bar":
                self._draw_bar(data)
            elif chart_type == "pie":
                self._draw_pie(data)
            elif chart_type == "sunburst":
                self._draw_sunburst(data)
            else:
                self._draw_empty(data.get("title", "暂无数据"))
        except Exception:
            logger.exception("图表绘制失败")
            self._draw_empty("绘制失败")

        self._canvas.draw()

    # ── 柱状图（fastp QC） ─────────────────────────────────────

    def _draw_bar(self, data: dict[str, Any]) -> None:
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(_BG_COLOR)

        categories = data.get("categories", [])
        series = data.get("series", [])

        x = np.arange(len(categories))
        width = 0.35 / max(len(series), 1) * 2 if series else 0.35
        n = len(series)
        offsets = [(-n / 2 + i + 0.5) * width for i in range(n)]

        for i, s in enumerate(series):
            color = s.get("color") or _PALETTE[i % len(_PALETTE)]
            bars = ax.bar(x + offsets[i], s.get("data", []), width, label=s.get("name", ""),
                          color=color, alpha=0.85, zorder=2)
            # 数值标签
            for bar in bars:
                h = bar.get_height()
                if h > 0:
                    ax.annotate(
                        f"{h:g}",
                        xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom",
                        fontsize=7.5, color=_TEXT_COLOR,
                    )

        ax.set_xticks(x)
        ax.set_xticklabels(categories, fontsize=9.5, color=_TEXT_COLOR)
        ax.set_title(data.get("title", ""), fontsize=12, color=_TEXT_COLOR, pad=10)
        ax.tick_params(axis="y", colors=_TEXT_COLOR, labelsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(_GRID_COLOR)
        ax.yaxis.grid(True, color=_GRID_COLOR, linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        if series:
            ax.legend(fontsize=9, framealpha=0)

    # ── 饼图（Kraken2 物种） ───────────────────────────────────

    def _draw_pie(self, data: dict[str, Any]) -> None:
        items = data.get("data", [])
        if not items:
            self._draw_empty(data.get("title", "暂无数据"))
            return

        ax = self._figure.add_subplot(111)
        ax.set_facecolor(_BG_COLOR)

        labels = [d["name"] for d in items]
        values = [d["value"] for d in items]

        colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(items))]

        wedges, texts, autotexts = ax.pie(
            values,
            labels=None,
            colors=colors,
            autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
            startangle=140,
            wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
            pctdistance=0.82,
        )
        for at in autotexts:
            at.set_fontsize(8)
            at.set_color("white")

        # 侧边图例（最多显示 15 个）
        legend_labels = labels[:15]
        legend_handles = wedges[:15]
        ax.legend(
            legend_handles, legend_labels,
            loc="center left", bbox_to_anchor=(1.0, 0.5),
            fontsize=8.5, framealpha=0,
        )
        ax.set_title(data.get("title", ""), fontsize=12, color=_TEXT_COLOR, pad=10)

    # ── 嵌套饼图（Sunburst 物种层级） ─────────────────────────

    def _draw_sunburst(self, data: dict[str, Any]) -> None:
        tree = data.get("data", [])
        if not tree:
            self._draw_empty(data.get("title", "暂无数据"))
            return

        ax = self._figure.add_subplot(111)
        ax.set_facecolor(_BG_COLOR)
        ax.set_aspect("equal")

        # 展平为内圈（Domain）+ 外圈（Phylum）层
        inner_labels, inner_vals = [], []
        outer_labels, outer_vals = [], []

        for i, domain in enumerate(tree):
            d_val = domain.get("value", 0)
            inner_labels.append(domain["name"])
            inner_vals.append(d_val)

            children = domain.get("children", [])
            for child in children:
                outer_labels.append(child["name"])
                outer_vals.append(child.get("value", 0))

        if not inner_vals:
            self._draw_empty(data.get("title", "暂无数据"))
            return

        inner_colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(inner_labels))]
        outer_colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(outer_labels))]

        # 内圈
        ax.pie(inner_vals, labels=inner_labels, colors=inner_colors,
               radius=0.55, startangle=140,
               wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
               textprops={"fontsize": 7.5, "color": _TEXT_COLOR})

        # 外圈（如果有）
        if outer_vals:
            ax.pie(outer_vals, labels=None, colors=outer_colors,
                   radius=1.0, startangle=140,
                   wedgeprops={"linewidth": 0.5, "edgecolor": "white", "width": 0.45})

        ax.set_title(data.get("title", ""), fontsize=12, color=_TEXT_COLOR, pad=10)

    # ── 空白占位图 ─────────────────────────────────────────────

    def _draw_empty(self, title: str) -> None:
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(_BG_COLOR)
        ax.text(
            0.5, 0.5, f"{title}\n（暂无数据）",
            ha="center", va="center", fontsize=11, color="#8E8E93",
            transform=ax.transAxes,
        )
        ax.set_axis_off()


class ResultsPanel(QFrame):
    """结果展示面板 — 包含 fastp QC 和 Kraken2 物种图表。

    在 AnalysisPage 流水线完成后调用 load_results() 刷新。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ResultsPanel")
        self.setStyleSheet("""
            QFrame#ResultsPanel {
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 8px;
                background: #FFFFFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        title_lbl = QLabel("分析结果")
        title_lbl.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1D1D1F; background: transparent;"
        )
        layout.addWidget(title_lbl)

        self._placeholder = QLabel("流水线运行完成后，结果图表将显示在此处。")
        self._placeholder.setStyleSheet(
            "font-size: 13px; color: #8E8E93; padding: 20px; background: transparent;"
        )
        layout.addWidget(self._placeholder)

        # fastp 质控图表
        self._fastp_chart = ChartWidget()
        self._fastp_chart.setMinimumHeight(260)
        self._fastp_chart.hide()
        layout.addWidget(self._fastp_chart)

        # Kraken2 物种组成图表
        self._kraken_chart = ChartWidget()
        self._kraken_chart.setMinimumHeight(260)
        self._kraken_chart.hide()
        layout.addWidget(self._kraken_chart)

    def load_results(self, fastp_json_path: str | None = None,
                     kreport_path: str | None = None) -> None:
        """加载并渲染结果图表。

        Args:
            fastp_json_path: 本地或远程已下载的 fastp JSON 文件路径
            kreport_path:    本地或远程已下载的 kreport 文件路径
        """
        from core.chart_data_parser import ChartDataParser
        has_data = False

        if fastp_json_path:
            try:
                chart_data = ChartDataParser.parse_fastp_json(fastp_json_path)
                self._fastp_chart.update_chart(chart_data)
                self._fastp_chart.show()
                has_data = True
            except Exception:
                logger.exception("加载 fastp 图表失败")

        if kreport_path:
            try:
                chart_data = ChartDataParser.parse_kreport(kreport_path)
                self._kraken_chart.update_chart(chart_data)
                self._kraken_chart.show()
                has_data = True
            except Exception:
                logger.exception("加载 Kraken2 图表失败")

        if has_data:
            self._placeholder.hide()
        else:
            self._placeholder.setText("未找到结果文件，请确认流水线已完成。")
            self._placeholder.show()

    def reset(self) -> None:
        """重置为初始状态（开始新流水线前调用）"""
        self._fastp_chart.hide()
        self._kraken_chart.hide()
        self._placeholder.setText("流水线运行完成后，结果图表将显示在此处。")
        self._placeholder.show()
