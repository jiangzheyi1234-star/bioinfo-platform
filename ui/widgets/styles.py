# ui/widgets/styles.py
# 设计令牌（Design Tokens）系统 — Clash Verge 风格
#
# 设计哲学：
#   - Apple HIG 色彩体系 (#007AFF 主蓝)
#   - 零阴影，通过背景层次创造深度
#   - 极细分割线 (rgba 6% 透明度级别)
#   - 选中态 = 低透明度主色调底色，而非实心色块
#   - 全局 8px 圆角

# ═══════════════════════════════════════════════════════════
#  颜色常量 (Tokens)
# ═══════════════════════════════════════════════════════════

# 主色调 — 柔和的天空蓝 (Soft Sky Blue) - 清新轻盈
COLOR_PRIMARY = "#7DD3FC"          # Tailwind Sky 300 - 更柔和的天空蓝
COLOR_PRIMARY_HOVER = "#38BDF8"    # Tailwind Sky 400
COLOR_PRIMARY_PRESSED = "#0EA5E9"  # Tailwind Sky 500

# 成功状态色 — 柔和绿
COLOR_SUCCESS = "#10B981"          # Tailwind Emerald 500
COLOR_SUCCESS_HOVER = "#059669"    # Tailwind Emerald 600
COLOR_SUCCESS_PRESSED = "#047857"  # Tailwind Emerald 700

# 辅助颜色
COLOR_DANGER = "#EF4444"           # Tailwind Red 500
COLOR_WARNING = "#F59E0B"          # Tailwind Amber 500

# 背景色系
COLOR_BG_APP = "#F8FAFC"              # Tailwind Slate 50
COLOR_BG_CARD = "#FFFFFF"             # 纯白卡片
COLOR_BG_PAGE = "#F8FAFC"             # 同 APP 背景
COLOR_BG_BLANK = "transparent"

# 边框色系
COLOR_BORDER = "#E2E8F0"              # Tailwind Slate 200 (更明亮清晰的边框)
COLOR_BORDER_INPUT = "#CBD5E1"        # Tailwind Slate 300
COLOR_BORDER_FOCUS = "#7DD3FC"        # 聚焦边框 Sky 300

# 选中态色系
COLOR_SELECTION_BG = "#F0F9FF"        # Tailwind Sky 50 - 极淡的天空蓝
COLOR_SELECTION_HOVER = "#F1F5F9"     # Tailwind Slate 100

# 文字色系 (Slate 体系)
COLOR_TEXT_TITLE = "#0F172A"           # Tailwind Slate 900
COLOR_TEXT_DEFAULT = "#334155"         # Tailwind Slate 700
COLOR_TEXT_SUB = "#475569"             # Tailwind Slate 600
COLOR_TEXT_HINT = "#94A3B8"            # Tailwind Slate 400
COLOR_TEXT_MUTED = "#CBD5E1"           # Tailwind Slate 300
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_DISABLED = "#94A3B8"
COLOR_TEXT_INTERPRET = "#075985"       # Tailwind Sky 800

# 侧边栏
COLOR_BG_SIDEBAR_ITEM = "#F1F5F9"          # hover: Slate 100
COLOR_BG_SIDEBAR_SELECTED = "#F0F9FF"      # Sky 50

# 按钮 & 交互
COLOR_BG_BUTTON_HOVER = "#F8FAFC"          # Slate 50
COLOR_BG_BUTTON_CHECKED = "#7DD3FC"        # Sky 300

# 表格 & 进度条
COLOR_BG_PROGRESS_BAR = "#F1F5F9"          # Slate 100
COLOR_BG_TABLE = "#FFFFFF"
COLOR_BG_TABLE_CELL = "#FFFFFF"
COLOR_BG_TABLE_GRIDLINE = "#E2E8F0"        # Slate 200
COLOR_BG_PROGRESS_CHUNK = "#7DD3FC"

# 卡片高亮 & 解读区
COLOR_BG_CARD_HIGHLIGHT = "#F8FAFC"
COLOR_BG_CARD_INTERPRET = "#F0F9FF"
COLOR_BG_INPUT_DISABLED = "#F1F5F9"

# ═══════════════════════════════════════════════════════════
#  尺寸常量
# ═══════════════════════════════════════════════════════════

RADIUS_CARD = "12px"      # 从 8px 增加到 12px
RADIUS_CTRL = "8px"       # 从 6px 增加到 8px
PADDING_CTRL = "10px 20px"
PADDING_INPUT = "10px 14px"

# ═══════════════════════════════════════════════════════════
#  字体栈 — 跟随系统，CJK 优先微软雅黑
# ═══════════════════════════════════════════════════════════

FONT_FAMILY = (
    "'Microsoft YaHei UI', 'Microsoft YaHei', "
    "'Segoe UI Emoji', 'Segoe UI', "
    "-apple-system, BlinkMacSystemFont, "
    "Roboto, 'Helvetica Neue', Arial, sans-serif"
)


def apply_card_shadow(widget) -> None:
    """给卡片应用全局一致的 Light & Clinical 风格悬浮阴影"""
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    from PyQt6.QtGui import QColor
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(15)
    shadow.setColor(QColor(0, 0, 0, 15))
    shadow.setOffset(0, 4)
    widget.setGraphicsEffect(shadow)


# ═══════════════════════════════════════════════════════════
#  基础样式模板
# ═══════════════════════════════════════════════════════════

_BTN_BASE = f"""
    QPushButton {{
        border-radius: {RADIUS_CTRL};
        padding: {PADDING_CTRL};
        font-weight: 600;
        font-size: 13px;
        border: none;
    }}
"""

_INPUT_BASE = f"""
    QLineEdit {{
        padding: {PADDING_INPUT};
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        background-color: {COLOR_BG_CARD};
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
        selection-background-color: {COLOR_SELECTION_BG};
        selection-color: {COLOR_TEXT_DEFAULT};
    }}
    QLineEdit:hover {{
        border: 1px solid rgba(0, 122, 255, 0.25);
    }}
    QLineEdit:focus {{
        border: 1px solid {COLOR_BORDER_FOCUS};
    }}
    QLineEdit:disabled {{
        background-color: {COLOR_BG_INPUT_DISABLED};
        color: {COLOR_TEXT_DISABLED};
    }}
"""

_COMBOBOX_BASE = f"""
    QComboBox {{
        padding: {PADDING_INPUT};
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        background-color: {COLOR_BG_CARD};
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
        min-height: 30px;
    }}
    QComboBox:hover {{
        border: 1px solid rgba(0, 122, 255, 0.25);
    }}
    QComboBox:focus {{
        border: 1px solid {COLOR_BORDER_FOCUS};
    }}
    QComboBox:disabled {{
        background-color: {COLOR_BG_INPUT_DISABLED};
        color: {COLOR_TEXT_DISABLED};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        border: none;
    }}
    QComboBox::down-arrow {{
        image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOCIgdmlld0JveD0iMCAwIDEyIDgiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHBhdGggZD0iTTEuNDEgMC41OEw2IDUuMTdsNC41OS00LjU5TDEyIDJsLTYgNkwwIDJsMS40MS0xLjQyeiIgZmlsbD0iIzNDM0M0Mzk5Ii8+PC9zdmc+);
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        background-color: {COLOR_BG_CARD};
        selection-background-color: {COLOR_SELECTION_BG};
        selection-color: {COLOR_PRIMARY};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 32px;
        padding: 4px 12px;
        color: {COLOR_TEXT_DEFAULT};
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {COLOR_SELECTION_HOVER};
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {COLOR_SELECTION_BG};
        color: {COLOR_PRIMARY};
    }}
    QComboBox QAbstractItemView QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QComboBox QAbstractItemView QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.2);
        border-radius: 4px;
        min-height: 20px;
    }}
    QComboBox QAbstractItemView QScrollBar::handle:vertical:hover {{
        background: rgba(0, 0, 0, 0.35);
    }}
    QComboBox QAbstractItemView QScrollBar::handle:vertical:pressed {{
        background: rgba(0, 0, 0, 0.5);
    }}
    QComboBox QAbstractItemView QScrollBar::add-line:vertical,
    QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
        height: 0px;
        background: transparent;
        border: none;
    }}
    QComboBox QAbstractItemView QScrollBar::add-page:vertical,
    QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
"""

# ═══════════════════════════════════════════════════════════
#  按钮体系
# ═══════════════════════════════════════════════════════════

BUTTON_PRIMARY = _BTN_BASE + f"""
    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7DD3FC, stop:1 #38BDF8);
        color: {COLOR_TEXT_WHITE};
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #BAE6FD, stop:1 #7DD3FC);
    }}
    QPushButton:pressed {{
        background: #0EA5E9;
    }}
    QPushButton:disabled {{
        background: #E2E8F0;
        color: #94A3B8;
    }}
"""

BUTTON_SUCCESS = _BTN_BASE + f"""
    QPushButton {{
        background-color: {COLOR_SUCCESS};
        color: {COLOR_TEXT_WHITE};
    }}
    QPushButton:hover {{
        background-color: {COLOR_SUCCESS_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_SUCCESS_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: #E2E8F0;
        color: #94A3B8;
    }}
"""

BUTTON_SECONDARY = f"""
    QPushButton {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid {COLOR_BORDER_INPUT};
        color: {COLOR_TEXT_DEFAULT};
        border-radius: {RADIUS_CTRL};
        padding: {PADDING_CTRL};
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        border-color: #94A3B8;
        background-color: {COLOR_BG_BUTTON_HOVER};
        color: #0F172A;
    }}
    QPushButton:pressed {{
        border-color: {COLOR_PRIMARY_PRESSED};
        background-color: #F1F5F9;
    }}
    QPushButton:disabled {{
        border-color: #E2E8F0;
        color: #94A3B8;
        background-color: #F8FAFC;
    }}
"""

BUTTON_PASTEL_PRIMARY = f"""
    QPushButton {{
        background: #F0F9FF;
        color: #0369A1;
        border: 1px solid #BAE6FD;
        border-radius: {RADIUS_CTRL};
        padding: 8px 16px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: #E0F2FE;
        border-color: #7DD3FC;
    }}
    QPushButton:pressed {{
        background: #BAE6FD;
    }}
"""

BUTTON_LINK = f"""
    QPushButton {{
        color: {COLOR_PRIMARY};
        border: none;
        background: {COLOR_BG_BLANK};
        font-size: 12px;
        text-decoration: underline;
    }}
    QPushButton:hover {{
        color: {COLOR_PRIMARY_HOVER};
    }}
    QPushButton:pressed {{
        color: {COLOR_PRIMARY_PRESSED};
    }}
    QPushButton:disabled {{
        color: {COLOR_TEXT_DISABLED};
        text-decoration: none;
    }}
"""

BUTTON_NAV_TOGGLE = f"""
    QPushButton {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        padding: 6px 20px;
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {COLOR_BG_BUTTON_HOVER};
        border-color: {COLOR_PRIMARY};
    }}
    QPushButton:checked {{
        background-color: {COLOR_BG_BUTTON_CHECKED};
        color: {COLOR_TEXT_WHITE};
        border-color: {COLOR_PRIMARY};
    }}
"""

BUTTON_DANGER = _BTN_BASE + f"""
    QPushButton {{
        background-color: rgba(255, 59, 48, 0.1);
        color: {COLOR_DANGER};
        border: 1px solid rgba(255, 59, 48, 0.2);
    }}
    QPushButton:hover {{
        background-color: rgba(255, 59, 48, 0.16);
        border: 1px solid rgba(255, 59, 48, 0.3);
    }}
    QPushButton:pressed {{
        background-color: rgba(255, 59, 48, 0.22);
        border: 1px solid rgba(255, 59, 48, 0.35);
    }}
    QPushButton:disabled {{
        background-color: rgba(255, 59, 48, 0.04);
        color: rgba(255, 59, 48, 0.3);
        border: 1px solid rgba(255, 59, 48, 0.06);
    }}
"""

# ═══════════════════════════════════════════════════════════
#  卡片和布局
# ═══════════════════════════════════════════════════════════

def CARD_FRAME(object_name: str) -> str:
    """Clash Verge 风格卡片 — 纯白底色，无边框，通过背景对比创造层次"""
    return f"""
        QFrame#{object_name} {{
            background-color: {COLOR_BG_CARD};
            border: none;
            border-radius: {RADIUS_CARD};
            padding: 15px;
        }}
        QFrame#{object_name}:hover {{
            background-color: {COLOR_BG_CARD};
            border: none;
        }}
    """

INPUT_LINEEDIT = _INPUT_BASE
INPUT_COMBOBOX = _COMBOBOX_BASE

# ═══════════════════════════════════════════════════════════
#  文字样式
# ═══════════════════════════════════════════════════════════

CARD_TITLE = f"font-size: 14px; font-weight: 600; color: {COLOR_TEXT_TITLE}; background: {COLOR_BG_BLANK};"
FORM_LABEL = f"font-size: 12px; color: {COLOR_TEXT_SUB}; background: {COLOR_BG_BLANK};"
LABEL_HINT = f"font-size: 12px; color: {COLOR_TEXT_HINT}; background: {COLOR_BG_BLANK};"
LABEL_MUTED = f"color: {COLOR_TEXT_MUTED}; font-size: 11px; background: {COLOR_BG_BLANK};"

# ═══════════════════════════════════════════════════════════
#  状态标签
# ═══════════════════════════════════════════════════════════

STATUS_NEUTRAL = f"color: {COLOR_TEXT_MUTED}; margin-left: 10px; background: {COLOR_BG_BLANK};"
STATUS_SUCCESS = f"color: {COLOR_SUCCESS}; background: {COLOR_BG_BLANK};"
STATUS_ERROR = f"color: {COLOR_DANGER}; background: {COLOR_BG_BLANK};"
STATUS_WARNING = f"color: {COLOR_WARNING}; background: {COLOR_BG_BLANK};"

# ═══════════════════════════════════════════════════════════
#  页面标题
# ═══════════════════════════════════════════════════════════

PAGE_HEADER_TITLE = f"font-size: 20px; font-weight: 700; color: {COLOR_TEXT_TITLE}; background: {COLOR_BG_BLANK};"

# ═══════════════════════════════════════════════════════════
#  分割线 & 进度条
# ═══════════════════════════════════════════════════════════

DIVIDER = f"background-color: {COLOR_BORDER}; max-height: 1px; border: none;"

PROGRESS_BAR = f"""
    QProgressBar {{
        border-radius: 3px;
        background: {COLOR_BG_PROGRESS_BAR};
        text-align: center;
        height: 6px;
        border: none;
    }}
    QProgressBar::chunk {{
        background: {COLOR_BG_PROGRESS_CHUNK};
        border-radius: 3px;
    }}
"""

# ═══════════════════════════════════════════════════════════
#  滚动条 — 极简隐形风格
# ═══════════════════════════════════════════════════════════

SCROLL_BAR_ELEGANT = f"""
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 5px;
        min-height: 40px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(0, 0, 0, 0.25);
    }}
    QScrollBar::handle:vertical:pressed {{
        background: rgba(0, 0, 0, 0.35);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        background: transparent;
        border: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 10px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 5px;
        min-width: 40px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: rgba(0, 0, 0, 0.25);
    }}
    QScrollBar::handle:horizontal:pressed {{
        background: rgba(0, 0, 0, 0.35);
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
        background: transparent;
        border: none;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""

# ═══════════════════════════════════════════════════════════
#  侧边栏导航 — Clash Verge 核心风格
#
#  选中态: 12% 主色调底色 + 主色文字 (非实心色块)
#  hover: 4% 黑色薄雾
#  文字: 700 粗体，不随选中态变化
# ═══════════════════════════════════════════════════════════

SIDEBAR_NAV_ITEM = f"""
    QListWidget {{
        background: {COLOR_BG_CARD};
        border: none;
        padding-top: 8px;
        outline: none;
        font-family: {FONT_FAMILY};
    }}
    QListWidget::item {{
        height: 40px;
        padding-left: 18px;
        margin: 2px 10px;
        border-radius: 8px;
        color: {COLOR_TEXT_SUB};
        font-size: 13px;
        font-weight: 700;
    }}
    QListWidget::item:hover {{
        background: {COLOR_BG_SIDEBAR_ITEM};
        color: {COLOR_TEXT_DEFAULT};
    }}
    QListWidget::item:selected {{
        background: {COLOR_BG_SIDEBAR_SELECTED};
        color: {COLOR_PRIMARY};
        font-weight: 700;
    }}
"""

# ═══════════════════════════════════════════════════════════
#  表格统一样式
# ═══════════════════════════════════════════════════════════

TABLE_WIDGET = f"""
    QTableWidget {{
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_CTRL};
        background-color: {COLOR_BG_TABLE};
        gridline-color: {COLOR_BG_TABLE_GRIDLINE};
        selection-background-color: {COLOR_SELECTION_BG};
        selection-color: {COLOR_TEXT_DEFAULT};
    }}
    QTableWidget::item {{
        padding: 8px;
        color: {COLOR_TEXT_DEFAULT};
    }}
    QTableWidget::item:hover {{
        background-color: {COLOR_SELECTION_HOVER};
    }}
    QTableWidget::item:selected {{
        background-color: {COLOR_SELECTION_BG};
        color: {COLOR_TEXT_DEFAULT};
    }}
    QHeaderView::section {{
        background-color: {COLOR_BG_CARD_HIGHLIGHT};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {COLOR_BORDER};
        font-weight: 600;
        color: {COLOR_TEXT_TITLE};
    }}
    QTableWidget QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QTableWidget QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 5px;
        min-height: 40px;
    }}
    QTableWidget QScrollBar::handle:vertical:hover {{
        background: rgba(0, 0, 0, 0.25);
    }}
    QTableWidget QScrollBar::handle:vertical:pressed {{
        background: rgba(0, 0, 0, 0.35);
    }}
    QTableWidget QScrollBar::add-line:vertical, QTableWidget QScrollBar::sub-line:vertical {{
        height: 0;
        background: transparent;
        border: none;
    }}
    QTableWidget QScrollBar::add-page:vertical, QTableWidget QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QTableWidget QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 10px;
        margin: 0;
    }}
    QTableWidget QScrollBar::handle:horizontal {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 5px;
        min-width: 40px;
    }}
    QTableWidget QScrollBar::handle:horizontal:hover {{
        background: rgba(0, 0, 0, 0.25);
    }}
    QTableWidget QScrollBar::handle:horizontal:pressed {{
        background: rgba(0, 0, 0, 0.35);
    }}
    QTableWidget QScrollBar::add-line:horizontal, QTableWidget QScrollBar::sub-line:horizontal {{
        width: 0;
        background: transparent;
        border: none;
    }}
    QTableWidget QScrollBar::add-page:horizontal, QTableWidget QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
"""
