# ui/widgets/styles.py

# --- 颜色常量 (Tokens) ---
COLOR_BG_APP = "#f4f9ff"      # 极浅蓝背景
COLOR_CARD_BG = "#ffffff"     # 纯白卡片背景
COLOR_BORDER = "#e1eefb"      # 浅蓝色边框
COLOR_PRIMARY = "#1890ff"     # 主色：科技蓝
COLOR_PRIMARY_HOVER = "#40a9ff" 
COLOR_PRIMARY_PRESSED = "#096dd9"

COLOR_SUCCESS = "#52c41a"
COLOR_DANGER = "#ff4d4f"

COLOR_TEXT_TITLE = "#1a3a5a"  # 深蓝黑文字
COLOR_TEXT_SUB = "#4a6a8a"    # 副标题蓝灰
COLOR_TEXT_HINT = "#90adca"   # 提示性淡蓝
COLOR_TEXT_MUTED = "#a0aec0"

# --- 尺寸常量 ---
RADIUS_CARD = "12px"
RADIUS_CTRL = "6px"

# --- 固定样式定义 ---

# 1. 简约时尚卡片
def CARD_FRAME(object_name: str) -> str:
    return f"""
        QFrame#{object_name} {{
            background-color: {COLOR_CARD_BG};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_CARD};
        }}
    """

# 2. 简约白色输入框 (Fixed)
INPUT_LINEEDIT = f"""
    QLineEdit {{
        padding: 8px 12px;
        border: 1px solid #dcebfa;
        border-radius: {RADIUS_CTRL};
        background-color: #ffffff;
        color: #333;
        font-size: 13px;
    }}
    QLineEdit:hover {{
        border: 1px solid {COLOR_PRIMARY_HOVER};
    }}
    QLineEdit:focus {{
        border: 1px solid {COLOR_PRIMARY};
    }}
    QLineEdit:disabled {{
        background-color: #f5f5f5;
        color: #bfbfbf;
    }}
"""

# 3. 具备交互感的标准按钮 (Fixed)
BUTTON_PRIMARY = f"""
    QPushButton {{
        background-color: {COLOR_PRIMARY};
        color: white;
        border-radius: {RADIUS_CTRL};
        padding: 8px 16px;
        font-weight: 500;
        border: none;
    }}
    QPushButton:hover {{
        background-color: {COLOR_PRIMARY_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_PRIMARY_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: #bae7ff;
        color: #ffffff;
    }}
"""

BUTTON_SUCCESS = f"""
    QPushButton {{
        background: {COLOR_SUCCESS};
        color: white;
        border-radius: {RADIUS_CTRL};
        padding: 10px 20px;
        font-weight: bold;
        border: none;
    }}
    QPushButton:hover {{
        background: #73d13d;
    }}
    QPushButton:pressed {{
        background: #389e0d;
    }}
    QPushButton:disabled {{
        background: #b7eb8f;
        color: #ffffff;
    }}
"""

BUTTON_LINK_PRIMARY = f"""
    QPushButton {{
        color: {COLOR_PRIMARY};
        border: none;
        background: transparent;
        font-size: 11px;
        text-decoration: underline;
    }}
    QPushButton:disabled {{
        color: #bfbfbf;
        text-decoration: none;
    }}
"""

BUTTON_LINK_SUCCESS = f"""
    QPushButton {{
        color: {COLOR_SUCCESS};
        border: none;
        background: transparent;
        font-size: 11px;
        text-decoration: underline;
    }}
    QPushButton:disabled {{
        color: #bfbfbf;
        text-decoration: none;
    }}
"""

BUTTON_LINK_DANGER = f"""
    QPushButton {{
        color: #ff7875;
        border: none;
        background: transparent;
        font-size: 11px;
        text-decoration: underline;
    }}
    QPushButton:disabled {{
        color: #bfbfbf;
        text-decoration: none;
    }}
"""

# 4. 文字样式
CARD_TITLE = f"font-size: 14px; font-weight: 600; color: {COLOR_TEXT_TITLE}; background: transparent;"
FORM_LABEL = f"font-size: 12px; color: {COLOR_TEXT_SUB}; background: transparent;"
LABEL_HINT = f"font-size: 12px; color: {COLOR_TEXT_HINT}; background: transparent;"
LABEL_MUTED = f"color: {COLOR_TEXT_MUTED}; font-size: 11px; background: transparent;"

# 5. 状态标签样式
STATUS_NEUTRAL = f"color: {COLOR_TEXT_MUTED}; margin-left: 10px; background: transparent;"
STATUS_SUCCESS = f"color: {COLOR_SUCCESS}; background: transparent;"
STATUS_ERROR = f"color: {COLOR_DANGER}; background: transparent;"

# 6. 页面标题样式
PAGE_HEADER_TITLE = f"font-size: 20px; font-weight: bold; color: {COLOR_TEXT_TITLE}; background: transparent;"