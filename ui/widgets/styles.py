"""ui.widgets.styles

集中管理可复用的样式字符串，避免跨组件访问对方私有字段。

建议：在组件里只拼装结构，不再写具体颜色/圆角/字体等细节。

用法示例：
  from ui.widgets.styles import INPUT_LINEEDIT, CARD_FRAME, BUTTON_PRIMARY, BUTTON_SUCCESS, BUTTON_LINK
  line_edit.setStyleSheet(INPUT_LINEEDIT)
  frame.setStyleSheet(CARD_FRAME("NCBICard"))
  save_btn.setStyleSheet(BUTTON_SUCCESS)
"""

# -------------------------
# Design tokens（颜色/尺寸）
# -------------------------
COLOR_BG_APP = "#f4f9ff"
COLOR_CARD_BG = "#ffffff"
COLOR_BORDER = "#e1eefb"

COLOR_PRIMARY = "#1890ff"
COLOR_SUCCESS = "#52c41a"
COLOR_DANGER = "#ff4d4f"

COLOR_TEXT_TITLE = "#1a3a5a"
COLOR_TEXT_MUTED = "#a0aec0"
COLOR_TEXT_SUBTITLE = "#4a6a8a"
COLOR_TEXT_HINT = "#90adca"

RADIUS_CARD = 12
RADIUS_CONTROL = 6


# -------------------------
# Card/frame
# -------------------------
def CARD_FRAME(object_name: str) -> str:
    """QFrame 卡片基础样式。"""
    return f"""
        QFrame#{object_name} {{
            background-color: {COLOR_CARD_BG};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_CARD}px;
        }}
    """


# -------------------------
# Typography helpers
# -------------------------
PAGE_HEADER_TITLE = f"font-size: 20px; font-weight: bold; color: {COLOR_TEXT_TITLE}; background: transparent;"
CARD_TITLE = f"font-weight: 600; color: {COLOR_TEXT_SUBTITLE}; font-size: 14px; background: transparent;"
LABEL_MUTED = f"color: {COLOR_TEXT_MUTED}; font-size: 11px; background: transparent;"

# 表单字段名（如“NCBI API Key”）建议使用更清晰的副标题色
FORM_LABEL = f"color: {COLOR_TEXT_SUBTITLE}; font-size: 12px; background: transparent;"

# 弱提示/装饰（箭头、辅助提示等）
LABEL_HINT = f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;"


# -------------------------
# Inputs
# -------------------------
INPUT_LINEEDIT = f"""
    QLineEdit {{
        padding: 10px;
        border: 1px solid #dcebfa;
        border-radius: {RADIUS_CONTROL}px;
        background-color: #fafcfe;
        color: #333;
    }}
    QLineEdit:focus {{
        border: 1px solid {COLOR_PRIMARY};
        background-color: #ffffff;
    }}
    QLineEdit:disabled {{
        background-color: #f5f5f5;
        color: #bfbfbf;
        border: 1px solid #e8e8e8;
    }}
"""


# -------------------------
# Buttons
# -------------------------
BUTTON_PRIMARY = f"""
    QPushButton {{
        background: {COLOR_PRIMARY};
        color: white;
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px;
        font-weight: bold;
        border: none;
    }}
    QPushButton:disabled {{
        background: #bae7ff;
        color: #ffffff;
    }}
"""

BUTTON_SUCCESS = f"""
    QPushButton {{
        background: {COLOR_SUCCESS};
        color: white;
        border-radius: {RADIUS_CONTROL}px;
        padding: 10px 20px;
        font-weight: bold;
        border: none;
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


# -------------------------
# Status labels
# -------------------------
STATUS_NEUTRAL = f"color: {COLOR_TEXT_MUTED}; margin-left: 10px; background: transparent;"
STATUS_SUCCESS = f"color: {COLOR_SUCCESS}; background: transparent;"
STATUS_ERROR = f"color: {COLOR_DANGER}; background: transparent;"

