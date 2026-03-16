"""H2OMeta UI 层 - 所有 UI 组件的入口

导入所有页面和 widget，方便跨模块使用。
"""

# 页面导入 (从 ui.pages 导出的页面)
from ui.pages import (
    HomePage,
    DetectionPageWeb,
    SettingsPage,
)

# Widget 导入 (延迟导入由 main.py 负责，这里仅做类型提示)

__all__ = [
    # Pages
    "HomePage",
    "DetectionPageWeb",
    "SettingsPage",
]
