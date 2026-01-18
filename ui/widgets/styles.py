# ui/widgets/styles.py
# 设计令牌（Design Tokens）系统 - 全局样式配置机制

# --- 颜色常量 (Tokens) ---
# 主色调
COLOR_PRIMARY = "#1890ff"           # 晴空浅蓝 - 主色调
COLOR_PRIMARY_HOVER = "#40a9ff"     # 悬停时的主色调
COLOR_PRIMARY_PRESSED = "#096dd9"   # 按下时的主色调

# 成功状态色
COLOR_SUCCESS = "#52c41a"           # 森林绿 - 成功状态
COLOR_SUCCESS_HOVER = "#73d13d"     # 悬停时的成功色
COLOR_SUCCESS_PRESSED = "#389e0d"   # 按下时的成功色

# 辅助颜色
COLOR_DANGER = "#ff4d4f"            # 危险/错误色
COLOR_WARNING = "#faad14"           # 警告色

# 背景色系
COLOR_BG_APP = "#f4f9ff"            # 极浅蓝大背景 - 应用背景
COLOR_BG_CARD = "#ffffff"            # 云白底色 - 卡片背景
COLOR_BG_PAGE = "#f5f7f9"           # 页面背景
COLOR_BG_BLANK = "transparent"      # 透明背景

# 边框色系
COLOR_BORDER = "#e1eefb"            # 低饱和度淡青色边框
COLOR_BORDER_INPUT = "#dcebfa"      # 输入框边框
COLOR_BORDER_FOCUS = "#1890ff"       # 聚焦时边框

# 文字色系
COLOR_TEXT_TITLE = "#1a3a5a"        # 深蓝黑 - 标题文字
COLOR_TEXT_DEFAULT = "#333333"      # 默认文字颜色
COLOR_TEXT_SUB = "#4a6a8a"          # 蓝灰 - 次要文字
COLOR_TEXT_HINT = "#90adca"          # 提示性淡蓝
COLOR_TEXT_MUTED = "#a0aec0"        # 弱化文字
COLOR_TEXT_WHITE = "white"          # 白色文字
COLOR_TEXT_DISABLED = "#bfbfbf"      # 禁用文字
COLOR_TEXT_INTERPRET = "#003a8c"    # 解读区域文字颜色

# 特殊背景色
COLOR_BG_SIDEBAR_ITEM = "#f0f7ff"   # 侧边栏项悬停背景
COLOR_BG_SIDEBAR_SELECTED = "#e6f7ff"  # 侧边栏选中项背景
COLOR_BG_BUTTON_HOVER = "#f0f7ff"   # 按钮悬停背景
COLOR_BG_BUTTON_CHECKED = "#1890ff" # 按钮选中背景
COLOR_BG_PROGRESS_BAR = "#eee"      # 进度条背景
COLOR_BG_TABLE = "white"            # 表格背景
COLOR_BG_TABLE_CELL = "#f8fbff"     # 表格单元格背景
COLOR_BG_CARD_HIGHLIGHT = "#f8fbff" # 卡片高亮背景
COLOR_BG_CARD_INTERPRET = "#f0f7ff" # 解读区域背景
COLOR_BG_INPUT_DISABLED = "#f5f5f5" # 输入框禁用背景
COLOR_BG_PROGRESS_CHUNK = "#1890ff" # 进度条块背景
COLOR_BG_TABLE_GRIDLINE = "#f0f0f0" # 表格网格线颜色

# --- 尺寸常量 ---
RADIUS_CARD = "12px"                # 卡片圆角
RADIUS_CTRL = "6px"                 # 控件圆角
PADDING_CTRL = "8px 16px"           # 控件内边距
PADDING_INPUT = "8px 12px"          # 输入框内边距

# --- 基础样式模板 ---
# 按钮基础样式 - 定义共同特征
_BTN_BASE = f"""
    QPushButton {{
        border-radius: {RADIUS_CTRL};
        padding: {PADDING_CTRL};
        font-weight: 500;
        font-size: 13px;
        border: none;
    }}
"""

# 输入框基础样式
_INPUT_BASE = f"""
    QLineEdit {{
        padding: {PADDING_INPUT};
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        background-color: {COLOR_BG_CARD};
        color: {COLOR_TEXT_DEFAULT};
        font-size: 13px;
    }}
    QLineEdit:hover {{
        border: 1px solid {COLOR_PRIMARY_HOVER};
    }}
    QLineEdit:focus {{
        border: 1px solid {COLOR_BORDER_FOCUS};
    }}
    QLineEdit:disabled {{
        background-color: {COLOR_BG_INPUT_DISABLED};
        color: {COLOR_TEXT_DISABLED};
    }}
"""

# 下拉框基础样式 - 极简风格
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
        border: 1px solid {COLOR_PRIMARY_HOVER};
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
        width: 20px;
        border-left: 1px solid {COLOR_BORDER_INPUT};
        border-top-right-radius: {RADIUS_CTRL};
        border-bottom-right-radius: {RADIUS_CTRL};
    }}
    QComboBox::down-arrow {{
        image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOCIgdmlld0JveD0iMCAwIDEyIDgiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xLjgzODg3IDMuNDc0NzZMNiA3LjYzNTYxTDEwLjE2MTEgMy40NzQ3NkMxMC40Mzk4IDMuMjM3OTkgMTAuMjYzMCAyLjgyMDMxIDkuODc0MjQgMi44MjAzMUgxLjEyNTc2QzEuMzMwIDIuODIwMzEgMC41NTAyOTMgMy4yMzc5OSAwLjgzODg3MSAzLjQ3NDc2WiIgZmlsbD0iIzRhNmE4YSIvPgo8L3N2Zz4K);
    }}
"""

# --- 按钮体系标准化（用途导向）---
# 主行动按钮 - 用于"执行"、"确定"、"保存"、"上传"
BUTTON_PRIMARY = _BTN_BASE + f"""
    QPushButton {{
        background-color: {COLOR_PRIMARY};
        color: {COLOR_TEXT_WHITE};
    }}
    QPushButton:hover {{
        background-color: {COLOR_PRIMARY_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_PRIMARY_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: #bae7ff;
        color: {COLOR_TEXT_WHITE};
    }}
"""

# 成功按钮 - 用于"连接成功"、"任务完成状态"
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
        background-color: #b7eb8f;
        color: {COLOR_TEXT_WHITE};
    }}
"""

# 次要按钮 - 用于"浏览文件"、"取消"、"返回"
BUTTON_SECONDARY = f"""
    QPushButton {{
        background-color: {COLOR_BG_CARD};
        border: 1px solid {COLOR_BORDER};
        color: {COLOR_TEXT_SUB};
        border-radius: {RADIUS_CTRL};
        padding: 8px 16px;
        font-weight: 500;
        font-size: 13px;
    }}
    QPushButton:hover {{
        border-color: {COLOR_PRIMARY_HOVER};
        color: {COLOR_PRIMARY};
        background-color: {COLOR_BG_BUTTON_HOVER};
    }}
    QPushButton:pressed {{
        border-color: {COLOR_PRIMARY_PRESSED};
        color: {COLOR_PRIMARY_PRESSED};
        background-color: {COLOR_BG_BUTTON_HOVER};
    }}
    QPushButton:disabled {{
        border-color: {COLOR_TEXT_DISABLED};
        color: {COLOR_TEXT_DISABLED};
        background-color: {COLOR_BG_INPUT_DISABLED};
    }}
"""

# 链接按钮 - 用于"设置规则"、"查看详情"、"帮助"
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
# 导航切换按钮 - 用于顶部模块导航
BUTTON_NAV_TOGGLE = f"""
    QPushButton {{
        background-color: {COLOR_BG_CARD_HIGHLIGHT};
        border: 1px solid {COLOR_BORDER_INPUT};
        border-radius: {RADIUS_CTRL};
        padding: 6px 20px;
        color: {COLOR_TEXT_SUB};
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
# 危险按钮 - 用于删除、移除等危险操作
BUTTON_DANGER = _BTN_BASE + f"""
    QPushButton {{
        background-color: {COLOR_DANGER};
        color: {COLOR_TEXT_WHITE};
    }}
    QPushButton:hover {{
        background-color: #ff7875;
    }}
    QPushButton:pressed {{
        background-color: #d9363e;
    }}
    QPushButton:disabled {{
        background-color: #ffccc7;
        color: {COLOR_TEXT_WHITE};
    }}
"""

# --- 卡片和布局样式 ---
def CARD_FRAME(object_name: str) -> str:
    """简约时尚卡片 - 大留白，清晰隔离"""
    return f"""
        QFrame#{object_name} {{
            background-color: {COLOR_BG_CARD};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_CARD};
            padding: 15px;
        }}
    """

# 输入框样式
INPUT_LINEEDIT = _INPUT_BASE

# 下拉框样式
INPUT_COMBOBOX = _COMBOBOX_BASE

# --- 文字样式 ---
CARD_TITLE = f"font-size: 14px; font-weight: 600; color: {COLOR_TEXT_TITLE}; background: {COLOR_BG_BLANK};"
FORM_LABEL = f"font-size: 12px; color: {COLOR_TEXT_SUB}; background: {COLOR_BG_BLANK};"
LABEL_HINT = f"font-size: 12px; color: {COLOR_TEXT_HINT}; background: {COLOR_BG_BLANK};"
LABEL_MUTED = f"color: {COLOR_TEXT_MUTED}; font-size: 11px; background: {COLOR_BG_BLANK};"

# --- 状态标签样式 ---
STATUS_NEUTRAL = f"color: {COLOR_TEXT_MUTED}; margin-left: 10px; background: {COLOR_BG_BLANK};"
STATUS_SUCCESS = f"color: {COLOR_SUCCESS}; background: {COLOR_BG_BLANK};"
STATUS_ERROR = f"color: {COLOR_DANGER}; background: {COLOR_BG_BLANK};"
STATUS_WARNING = f"color: {COLOR_WARNING}; background: {COLOR_BG_BLANK};"

# --- 页面标题样式 ---
PAGE_HEADER_TITLE = f"font-size: 20px; font-weight: bold; color: {COLOR_TEXT_TITLE}; background: {COLOR_BG_BLANK};"

# --- 其他常用样式 ---
# 分割线样式
DIVIDER = f"background-color: {COLOR_BORDER}; max-height: 1px; border: none;"

# 进度条样式
PROGRESS_BAR = f"""
    QProgressBar {{
        border-radius: 3px;
        background: {COLOR_BG_PROGRESS_BAR};
        text-align: center;
        height: 6px;
    }}
    QProgressBar::chunk {{
        background: {COLOR_BG_PROGRESS_CHUNK};
        border-radius: 3px;
    }}
"""