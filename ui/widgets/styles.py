# ui/widgets/styles.py
# 设计令牌（Design Tokens）系统 — Clash Verge 风格
#
# 设计哲学：
#   - Clash Verge 亮色主题：纯白底 + 蓝色强调
#   - 零阴影，通过背景层次创造深度
#   - 极细分割线 (rgba 6% 透明度级别)
#   - 选中态 = 低透明度主色调底色，而非实心色块
#   - 全局 8~12px 圆角

# ═══════════════════════════════════════════════════════════
#  颜色常量 (Tokens)
# ═══════════════════════════════════════════════════════════

# 主色调 — 科技蓝 (Blue 系列，比 Sky 更沉稳)
COLOR_PRIMARY = "#3B82F6"            # Blue 500
COLOR_PRIMARY_HOVER = "#2563EB"      # Blue 600
COLOR_PRIMARY_PRESSED = "#1D4ED8"    # Blue 700

# 成功状态色
COLOR_SUCCESS = "#10B981"            # Emerald 500
COLOR_SUCCESS_HOVER = "#059669"      # Emerald 600
COLOR_SUCCESS_PRESSED = "#047857"    # Emerald 700

# 辅助颜色
COLOR_DANGER = "#EF4444"             # Red 500
COLOR_WARNING = "#F59E0B"            # Amber 500

# 背景色系 — 亮色层级
COLOR_BG_APP = "#F1F5F9"             # Slate 100 (略带蓝灰)
COLOR_BG_CARD = "#FFFFFF"            # 纯白卡片
COLOR_BG_PAGE = "#F1F5F9"            # 同 APP 背景
COLOR_BG_BLANK = "transparent"
COLOR_BG_SIDEBAR = "#FFFFFF"         # 白色侧边栏
COLOR_BG_TERMINAL = "#1E1E2E"        # 终端深色
COLOR_BG_TERMINAL_TEXT = "#D4D4D4"   # 终端文字

# 边框色系
COLOR_BORDER = "#E2E8F0"             # Slate 200
COLOR_BORDER_INPUT = "#CBD5E1"       # Slate 300
COLOR_BORDER_FOCUS = "#3B82F6"       # Blue 500

# 选中态色系
COLOR_SELECTION_BG = "#EFF6FF"       # Blue 50
COLOR_SELECTION_HOVER = "#F1F5F9"    # Slate 100

# 文字色系 (Slate 体系)
COLOR_TEXT_TITLE = "#0F172A"         # Slate 900
COLOR_TEXT_DEFAULT = "#334155"       # Slate 700
COLOR_TEXT_SUB = "#475569"           # Slate 600
COLOR_TEXT_HINT = "#94A3B8"          # Slate 400
COLOR_TEXT_MUTED = "#CBD5E1"         # Slate 300
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_DISABLED = "#94A3B8"
COLOR_TEXT_INTERPRET = "#1D4ED8"     # Blue 700

# 侧边栏
COLOR_BG_SIDEBAR_ITEM = "#F1F5F9"        # hover: Slate 100
COLOR_BG_SIDEBAR_SELECTED = "#EFF6FF"    # Blue 50

# 按钮 & 交互
COLOR_BG_BUTTON_HOVER = "#F8FAFC"        # Slate 50
COLOR_BG_BUTTON_CHECKED = "#3B82F6"      # Blue 500

# 表格 & 进度条
COLOR_BG_PROGRESS_BAR = "#F1F5F9"        # Slate 100
COLOR_BG_TABLE = "#FFFFFF"
COLOR_BG_TABLE_CELL = "#FFFFFF"
COLOR_BG_TABLE_GRIDLINE = "#E2E8F0"      # Slate 200
COLOR_BG_PROGRESS_CHUNK = "#3B82F6"

# 卡片高亮 & 解读区
COLOR_BG_CARD_HIGHLIGHT = "#F8FAFC"
COLOR_BG_CARD_INTERPRET = "#EFF6FF"
COLOR_BG_INPUT_DISABLED = "#F1F5F9"

# 信息/警告区块
COLOR_BG_INFO = "#EFF6FF"                # Blue 50
COLOR_BG_INFO_BORDER = "#BFDBFE"         # Blue 200
COLOR_BG_WARN = "#FFFBEB"               # Amber 50
COLOR_BG_WARN_TEXT = "#B45309"           # Amber 700

# ═══════════════════════════════════════════════════════════
#  尺寸常量
# ═══════════════════════════════════════════════════════════

RADIUS_CARD = "12px"
RADIUS_CTRL = "8px"
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
    """Clash Verge 风格的轻柔阴影"""
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
        border: 1px solid rgba(59, 130, 246, 0.4);
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
        border: 1px solid rgba(59, 130, 246, 0.4);
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
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:1 #2563EB);
        color: {COLOR_TEXT_WHITE};
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #60A5FA, stop:1 #3B82F6);
    }}
    QPushButton:pressed {{
        background: #1D4ED8;
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
        background: #EFF6FF;
        color: #1D4ED8;
        border: 1px solid #BFDBFE;
        border-radius: {RADIUS_CTRL};
        padding: 8px 16px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: #DBEAFE;
        border-color: #93C5FD;
    }}
    QPushButton:pressed {{
        background: #BFDBFE;
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
    """Clash Verge 风格卡片 — 纯白底，12px 圆角"""
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
#  选中态: 蓝色背景 + 白色文字 (圆角胶囊)
#  hover: 浅灰薄雾
#  文字: 700 粗体
# ═══════════════════════════════════════════════════════════

SIDEBAR_NAV_ITEM = f"""
    QListWidget {{
        background: {COLOR_BG_SIDEBAR};
        border: none;
        padding-top: 8px;
        outline: none;
        font-family: {FONT_FAMILY};
    }}
    QListWidget::item {{
        height: 44px;
        padding-left: 16px;
        margin: 2px 10px;
        border-radius: 8px;
        color: {COLOR_TEXT_SUB};
        font-size: 13px;
        font-weight: 600;
    }}
    QListWidget::item:hover {{
        background: {COLOR_BG_SIDEBAR_ITEM};
        color: {COLOR_TEXT_DEFAULT};
    }}
    QListWidget::item:selected {{
        background: {COLOR_BG_SIDEBAR_SELECTED};
        color: {COLOR_TEXT_DEFAULT};
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

# ═══════════════════════════════════════════════════════════
#  项目选择器样式
# ═══════════════════════════════════════════════════════════

PROJECT_SELECTOR_BUTTON = f"""
    QPushButton {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        padding: 10px 12px;
        text-align: left;
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
        font-weight: 500;
        margin: 4px 8px 8px 8px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_BG_SIDEBAR_ITEM};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_SELECTION_BG};
    }}
"""

PROJECT_SELECTOR_BUTTON_EMPTY = f"""
    QPushButton {{
        background-color: transparent;
        border: none;
        border-radius: 8px;
        padding: 10px 12px;
        text-align: left;
        color: {COLOR_PRIMARY};
        font-size: 13px;
        font-weight: 500;
        margin: 4px 8px 8px 8px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_BG_SIDEBAR_ITEM};
    }}
"""

PROJECT_SELECTOR_MENU = f"""
    QFrame {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid #CBD5E1;
        border-radius: 10px;
    }}
"""

PROJECT_MENU_SEARCH = f"""
    QLineEdit {{
        border: none;
        border-bottom: 1px solid #E2E8F0;
        padding: 10px 10px;
        font-size: 13px;
        color: {COLOR_TEXT_DEFAULT};
        background: transparent;
    }}
    QLineEdit::placeholder {{
        color: {COLOR_TEXT_HINT};
    }}
"""

PROJECT_MENU_LIST = f"""
    QListWidget {{
        border: none;
        background: transparent;
        outline: none;
    }}
    QListWidget::item {{
        padding: 8px 12px;
        border-radius: 6px;
        margin: 1px 4px;
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
    }}
    QListWidget::item:hover {{
        background-color: {COLOR_SELECTION_HOVER};
    }}
    QListWidget::item:selected {{
        background-color: {COLOR_SELECTION_BG};
        color: {COLOR_PRIMARY};
    }}
    QScrollBar:vertical {{
        width: 5px;
        background: transparent;
        margin: 6px 4px 6px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 2px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(0, 0, 0, 0.25);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
"""

PROJECT_MENU_BUTTON = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-top: 1px solid #E2E8F0;
        border-radius: 0;
        padding: 10px 10px;
        text-align: left;
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_SELECTION_HOVER};
    }}
"""

PROJECT_MENU_BUTTON_DANGER = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-top: 1px solid #E2E8F0;
        border-radius: 0;
        padding: 10px 10px;
        text-align: left;
        color: {COLOR_DANGER};
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: rgba(239, 68, 68, 0.08);
    }}
"""
