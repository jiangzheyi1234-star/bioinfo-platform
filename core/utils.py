"""通用工具函数。

此模块无外部依赖，可被任何层使用。
"""

from __future__ import annotations

import re
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


def human_time_ago(ts: float) -> str:
    """将时间戳转换为'X 分钟前'形式。"""
    if ts is None:
        return "—"
    diff = time.time() - ts
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff / 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff / 3600)} 小时前"
    return f"{int(diff / 86400)} 天前"


def sanitize_terminal_line(text: str) -> str:
    """清理终端输出：去 ANSI 转义码，处理 \\r 覆写。

    conda 的 spinner / 进度条使用 ``\\r`` 在同一行反复覆写，
    多包下载区域使用 ``ESC[A`` 光标上移重绘。
    直接 insertPlainText 会导致乱码。这里只保留最后一段有意义的内容。
    """
    text = ANSI_RE.sub("", text)
    if "\r" in text:
        parts = text.split("\r")
        last = ""
        for p in reversed(parts):
            if p.strip():
                last = p
                break
        if text.endswith("\n") and not last.endswith("\n"):
            last += "\n"
        text = last
    if not text.strip():
        return ""
    return text