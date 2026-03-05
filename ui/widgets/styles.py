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

# 主色调 — Apple HIG 蓝
COLOR_PRIMARY = "#007AFF"
COLOR_PRIMARY_HOVER = "#3395FF"
COLOR_PRIMARY_PRESSED = "#0062CC"

# 成功状态色
COLOR_SUCCESS = "#06943D"
COLOR_SUCCESS_HOVER = "#0AAF4A"
COLOR_SUCCESS_PRESSED = "#057A32"

# 辅助颜色
COLOR_DANGER = "#FF3B30"
COLOR_WARNING = "#FF9500"

# 背景色系 — 通过层次区分，不靠边框
COLOR_BG_APP = "#F5F5F5"              # 内容区浅灰底
COLOR_BG_CARD = "#FFFFFF"             # 卡片/侧边栏白底
COLOR_BG_PAGE = "#F5F5F5"             # 页面背景 = 内容区
COLOR_BG_BLANK = "transparent"

# 边框色系 — 极淡，6%-10% 可见度
COLOR_BORDER = "rgba(0, 0, 0, 0.08)"          # 通用分割线
COLOR_BORDER_INPUT = "rgba(0, 0, 0, 0.12)"    # 输入框边框（略深）
COLOR_BORDER_FOCUS = "rgba(0, 122, 255, 0.45)"  # 聚焦边框 — 柔和蓝

# 选中态色系 — 极柔和的蓝色底色，避免刺眼
COLOR_SELECTION_BG = "rgba(0, 122, 255, 0.08)"    # 选中行背景 8%
COLOR_SELECTION_HOVER = "rgba(0, 122, 255, 0.05)"  # 悬停行背景 5%

# 文字色系 — 黑底灰辅，苹果风格
COLOR_TEXT_TITLE = "#000000"           # 纯黑标题
COLOR_TEXT_DEFAULT = "#1D1D1F"         # 正文深黑
COLOR_TEXT_SUB = "rgba(60, 60, 67, 0.6)"  # 次要文字 60% 透明
COLOR_TEXT_HINT = "rgba(60, 60, 67, 0.35)"  # 提示文字 35% 透明
COLOR_TEXT_MUTED = "rgba(60, 60, 67, 0.25)"  # 弱化文字
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_DISABLED = "rgba(60, 60, 67, 0.2)"
COLOR_TEXT_INTERPRET = "#003A8C"        # 解读区域文字

# 侧边栏
COLOR_BG_SIDEBAR_ITEM = "rgba(0, 0, 0, 0.04)"     # hover: 4% 黑色薄雾
COLOR_BG_SIDEBAR_SELECTED = "rgba(0, 122, 255, 0.12)"  # 12% 主色调底色

# 按钮 & 交互
COLOR_BG_BUTTON_HOVER = "rgba(0, 122, 255, 0.06)"  # 极淡蓝
COLOR_BG_BUTTON_CHECKED = "#007AFF"

# 表格 & 进度条
COLOR_BG_PROGRESS_BAR = "rgba(0, 0, 0, 0.04)"
COLOR_BG_TABLE = "#FFFFFF"
COLOR_BG_TABLE_CELL = "#FAFAFA"
COLOR_BG_TABLE_GRIDLINE = "rgba(0, 0, 0, 0.05)"
COLOR_BG_PROGRESS_CHUNK = "#007AFF"

# 卡片高亮 & 解读区
COLOR_BG_CARD_HIGHLIGHT = "#FAFAFA"
COLOR_BG_CARD_INTERPRET = "rgba(0, 122, 255, 0.04)"
COLOR_BG_INPUT_DISABLED = "#F5F5F5"

# ═══════════════════════════════════════════════════════════
#  尺寸常量
# ═══════════════════════════════════════════════════════════

RADIUS_CARD = "8px"
RADIUS_CTRL = "6px"
PADDING_CTRL = "8px 16px"
PADDING_INPUT = "8px 12px"

# ═══════════════════════════════════════════════════════════
#  字体栈 — 跟随系统，CJK 优先微软雅黑
# ═══════════════════════════════════════════════════════════

FONT_FAMILY = (
    "'Microsoft YaHei UI', 'Microsoft YaHei', "
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "Roboto, 'Helvetica Neue', Arial, sans-serif"
)

# ═══════════════════════════════════════════════════════════
#  基础样式模板
# ═══════════════════════════════════════════════════════════

_BTN_BASE = f"""
    QPushButton {{
        border-radius: {RADIUS_CTRL};
        padding: {PADDING_CTRL};
        font-weight: 500;
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
"""

# ═══════════════════════════════════════════════════════════
#  按钮体系
# ═══════════════════════════════════════════════════════════

BUTTON_PRIMARY = _BTN_BASE + f"""
    QPushButton {{
        background-color: rgba(0, 122, 255, 0.1);
        color: {COLOR_PRIMARY};
        border: 1px solid rgba(0, 122, 255, 0.2);
    }}
    QPushButton:hover {{
        background-color: rgba(0, 122, 255, 0.16);
        border: 1px solid rgba(0, 122, 255, 0.3);
    }}
    QPushButton:pressed {{
        background-color: rgba(0, 122, 255, 0.22);
        border: 1px solid rgba(0, 122, 255, 0.35);
    }}
    QPushButton:disabled {{
        background-color: rgba(0, 122, 255, 0.04);
        color: rgba(0, 122, 255, 0.3);
        border: 1px solid rgba(0, 122, 255, 0.06);
    }}
"""

BUTTON_SUCCESS = _BTN_BASE + f"""
    QPushButton {{
        background-color: rgba(6, 148, 61, 0.1);
        color: {COLOR_SUCCESS};
        border: 1px solid rgba(6, 148, 61, 0.2);
    }}
    QPushButton:hover {{
        background-color: rgba(6, 148, 61, 0.16);
        border: 1px solid rgba(6, 148, 61, 0.3);
    }}
    QPushButton:pressed {{
        background-color: rgba(6, 148, 61, 0.22);
        border: 1px solid rgba(6, 148, 61, 0.35);
    }}
    QPushButton:disabled {{
        background-color: rgba(6, 148, 61, 0.04);
        color: rgba(6, 148, 61, 0.3);
        border: 1px solid rgba(6, 148, 61, 0.06);
    }}
"""

BUTTON_SECONDARY = f"""
    QPushButton {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid {COLOR_BORDER_INPUT};
        color: {COLOR_TEXT_DEFAULT};
        border-radius: {RADIUS_CTRL};
        padding: 8px 16px;
        font-weight: 500;
        font-size: 13px;
    }}
    QPushButton:hover {{
        border-color: rgba(0, 122, 255, 0.35);
        color: {COLOR_PRIMARY};
        background-color: {COLOR_BG_BUTTON_HOVER};
    }}
    QPushButton:pressed {{
        border-color: {COLOR_PRIMARY_PRESSED};
        color: {COLOR_PRIMARY_PRESSED};
    }}
    QPushButton:disabled {{
        border-color: {COLOR_TEXT_DISABLED};
        color: {COLOR_TEXT_DISABLED};
        background-color: {COLOR_BG_INPUT_DISABLED};
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
        width: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(0, 0, 0, 0.15);
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(0, 0, 0, 0.3);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
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
"""
