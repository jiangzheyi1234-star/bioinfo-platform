from __future__ import annotations

from collections import defaultdict
from typing import ClassVar

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.widgets.styles import (
    COLOR_BG_CARD,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_DEFAULT,
    COLOR_TEXT_TITLE,
    COLOR_TEXT_WHITE,
)


class Toast(QFrame):
    """轻量右下角通知：默认自动消失，可手动关闭。"""

    _active: ClassVar[dict[int, list["Toast"]]] = defaultdict(list)
    _SPACING: ClassVar[int] = 10
    _MARGIN: ClassVar[int] = 20

    def __init__(self, host: QWidget, message: str, level: str = "info", duration_ms: int = 3000):
        super().__init__(None)
        self._host = host.window() if host is not None else None
        self._duration_ms = max(0, int(duration_ms))
        self.setObjectName("AppToast")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        text_color = COLOR_TEXT_WHITE if level in {"success", "error"} else COLOR_TEXT_DEFAULT
        bg_color = {
            "success": COLOR_SUCCESS,
            "error": COLOR_DANGER,
        }.get(level, COLOR_BG_CARD)
        border_color = bg_color if level in {"success", "error"} else COLOR_BORDER

        self.setStyleSheet(
            f"""
            QFrame#AppToast {{
                background: {bg_color};
                border: 1px solid {border_color};
                border-radius: 10px;
            }}
            QLabel#ToastText {{
                color: {text_color};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#ToastClose {{
                border: none;
                background: transparent;
                color: {text_color};
                font-size: 14px;
                min-width: 16px;
                min-height: 16px;
            }}
            QPushButton#ToastClose:hover {{
                color: {COLOR_TEXT_TITLE if level == "info" else COLOR_TEXT_WHITE};
            }}
            """
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(8)

        prefix = {
            "success": "成功",
            "error": "失败",
        }.get(level, "提示")
        text = QLabel(f"{prefix}: {message}")
        text.setObjectName("ToastText")
        text.setWordWrap(True)
        lay.addWidget(text, 1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("ToastClose")
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.setMinimumWidth(280)
        self.adjustSize()

    @classmethod
    def show_toast(cls, host: QWidget, message: str, level: str = "info", duration_ms: int = 3000) -> None:
        if host is None:
            return
        toast = cls(host, message=message, level=level, duration_ms=duration_ms)
        key = id(toast._host)
        cls._active[key].append(toast)
        toast._relayout_host_toasts()
        toast.show()
        if toast._duration_ms > 0:
            QTimer.singleShot(toast._duration_ms, toast.close)

    def _relayout_host_toasts(self) -> None:
        if self._host is None:
            return
        key = id(self._host)
        stack = [t for t in self._active.get(key, []) if t is not None and not t.isHidden()]
        self._active[key] = stack
        if not stack:
            return
        top_left = self._host.mapToGlobal(QPoint(0, 0))
        host_w = self._host.width()
        host_h = self._host.height()
        y = host_h - self._MARGIN
        for t in reversed(stack):
            t.adjustSize()
            x = max(self._MARGIN, host_w - t.width() - self._MARGIN)
            y -= t.height()
            t.move(top_left + QPoint(x, y))
            y -= self._SPACING

    def closeEvent(self, event) -> None:
        if self._host is not None:
            key = id(self._host)
            self._active[key] = [t for t in self._active.get(key, []) if t is not self and not t.isHidden()]
            # 关闭后重新布局剩余 toast
            if self._active[key]:
                self._active[key][0]._relayout_host_toasts()
        super().closeEvent(event)
