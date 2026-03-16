"""日志页面 — 仿 Clash Verge Rev 风格的实时任务执行日志。

两行布局：第一行 时间戳 + 彩色级别标签，第二行 消息正文。
1px 分割线分隔条目，自定义 QStyledItemDelegate 绘制。
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from core.utils import sanitize_log
from ui.page_base import BasePage
from ui.widgets import styles

logger = logging.getLogger(__name__)

MAX_LOG_ENTRIES = 5000
TAIL_INTERVAL_MS = 3000

_LEVEL_COLORS = {
    "INFO": "#3B82F6",      # Tailwind Blue 500
    "SUCCESS": "#10B981",   # Tailwind Emerald 500
    "WARNING": "#F59E0B",   # Tailwind Amber 500
    "ERROR": "#EF4444",     # Tailwind Red 500
}
_ALL_LEVELS = ["ALL", "INFO", "SUCCESS", "WARNING", "ERROR"]
_ENTRY_ROLE = Qt.ItemDataRole.UserRole


class _LogEntry:
    __slots__ = ("ts", "level", "message", "execution_id", "project_id")

    def __init__(self, ts: str, level: str, message: str, eid: str = "",
                 project_id: str = ""):
        self.ts = ts
        self.level = level
        self.message = message
        self.execution_id = eid
        self.project_id = project_id


# ── Delegate ─────────────────────────────────────────────

class _LogDelegate(QStyledItemDelegate):
    """Clash Verge 风格两行日志条目绘制。"""

    _PAD_H = 16
    _PAD_V = 8
    _LINE_GAP = 4

    def paint(self, painter, option: QStyleOptionViewItem, index):
        entry: Optional[_LogEntry] = index.data(_ENTRY_ROLE)
        if not entry:
            return
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        rect = option.rect

        # 背景
        painter.fillRect(rect, QColor(styles.COLOR_BG_PAGE))

        x = rect.x() + self._PAD_H
        w = rect.width() - self._PAD_H * 2

        # ── 第一行：时间戳 + 级别 ──
        ts_font = QFont(styles.FONT_FAMILY.split(",")[0].strip("' "), 11)
        ts_fm = QFontMetrics(ts_font)
        y1 = rect.y() + self._PAD_V + ts_fm.ascent()

        painter.setFont(ts_font)
        painter.setPen(QColor(styles.COLOR_TEXT_HINT))
        painter.drawText(x, y1, entry.ts)
        ts_w = ts_fm.horizontalAdvance(entry.ts)

        lvl_font = QFont(ts_font)
        lvl_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(lvl_font)
        color = _LEVEL_COLORS.get(entry.level, _LEVEL_COLORS["INFO"])
        painter.setPen(QColor(color))
        painter.drawText(x + ts_w + 12, y1, entry.level)

        # ── 第二行：消息正文 ──
        msg_font = QFont(styles.FONT_FAMILY.split(",")[0].strip("' "), 12)
        msg_fm = QFontMetrics(msg_font)
        y2 = y1 + ts_fm.descent() + self._LINE_GAP + msg_fm.ascent()

        painter.setFont(msg_font)
        painter.setPen(QColor(styles.COLOR_TEXT_DEFAULT))
        elided = msg_fm.elidedText(entry.message, Qt.TextElideMode.ElideRight, w)
        painter.drawText(x, y2, elided)

        # ── 底部分割线 ──
        painter.setPen(QPen(QColor(styles.COLOR_BORDER), 1))
        bot = rect.bottom()
        painter.drawLine(rect.x() + self._PAD_H, bot, rect.right() - self._PAD_H, bot)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 52)


# ── 远端日志轮询 ─────────────────────────────────────────

def _parse_level(line: str) -> tuple[str, str]:
    for lvl in ("INFO", "SUCCESS", "WARNING", "ERROR"):
        tag = f"[{lvl}]"
        if tag in line:
            return lvl, line[line.index(tag) + len(tag):].strip()
    return "INFO", line.strip()


class _LogTailWorker(QObject):
    new_lines = pyqtSignal(list)

    def __init__(self, ssh_run_fn: Callable, task_dir: str) -> None:
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._task_dir = task_dir
        self._last_line = 1
        self._stopped = False

    def poll(self) -> None:
        if self._stopped:
            return
        try:
            expanded = f'"$(eval echo {self._task_dir})"'
            cmd = f"tail -n +{self._last_line} {expanded}/task.log 2>/dev/null"
            rc, stdout, _ = self._ssh_run_fn(cmd, 10)
            if rc == 0 and stdout.strip():
                cleaned = sanitize_log(stdout)
                lines = [l for l in cleaned.split("\n") if l.strip()]
                if lines:
                    self._last_line += len(lines)
                    self.new_lines.emit(lines)
        except Exception as e:
            logger.debug("日志轮询失败: %s", e)

    def stop(self) -> None:
        self._stopped = True


# ── 日志页面 ─────────────────────────────────────────────

class LogPage(BasePage):
    """实时日志页面 — Clash Verge Rev 风格。"""

    def __init__(self, main_window=None) -> None:
        super().__init__("日志")
        self._main_window = main_window
        self._entries: list[_LogEntry] = []
        self._ssh_run_fn: Optional[Callable] = None
        self._current_exec_id = ""
        self._current_task_dir = ""
        self._current_project_id = ""
        self._project_filter = True  # 默认开启项目筛选
        self._tail_worker: Optional[_LogTailWorker] = None
        self._tail_thread: Optional[QThread] = None
        self._tail_timer: Optional[QTimer] = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.label.hide()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── 顶栏工具条 ──
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 12, 16, 8)
        toolbar.setSpacing(8)

        self._level_combo = QComboBox()
        self._level_combo.addItems(_ALL_LEVELS)
        self._level_combo.setFixedWidth(110)
        self._level_combo.setFixedHeight(33)
        self._level_combo.setStyleSheet(styles.INPUT_COMBOBOX)
        self._level_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._level_combo)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("搜索日志...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.setFixedHeight(33)
        self._filter_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._filter_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_input, stretch=1)

        self._project_btn = QPushButton("仅当前项目")
        self._project_btn.setCheckable(True)
        self._project_btn.setChecked(True)
        self._project_btn.setFixedHeight(33)
        self._project_btn.setStyleSheet(styles.BUTTON_NAV_TOGGLE)
        self._project_btn.toggled.connect(self._on_project_filter_toggled)
        toolbar.addWidget(self._project_btn)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.setFixedHeight(33)
        self._clear_btn.setStyleSheet(styles.BUTTON_DANGER)
        self._clear_btn.clicked.connect(self.clear_logs)
        toolbar.addWidget(self._clear_btn)

        self.layout.addLayout(toolbar)

        # ── 日志列表 ──
        self._list = QListWidget()
        self._list.setItemDelegate(_LogDelegate(self._list))
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            f"QListWidget{{border:none; background:{styles.COLOR_BG_PAGE}; outline:none;}}"
            f"QListWidget::item{{border:none; padding:0;}}"
            f"{styles.SCROLL_BAR_ELEGANT}"
        )
        self.layout.addWidget(self._list, stretch=1)

        # ── 空状态占位 ──
        self._empty_label = QLabel("暂无日志")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color:{styles.COLOR_TEXT_MUTED}; font-size:14px; background:transparent;"
        )
        self._empty_label.setVisible(True)
        self.layout.addWidget(self._empty_label, stretch=1)

        # ── 底栏 ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 6, 16, 10)
        self._count_label = QLabel("共 0 条日志")
        self._count_label.setStyleSheet(styles.LABEL_HINT)
        bottom.addWidget(self._count_label)
        bottom.addStretch()
        self._exec_label = QLabel("")
        self._exec_label.setStyleSheet(styles.LABEL_HINT)
        bottom.addWidget(self._exec_label)
        self.layout.addLayout(bottom)

    # ── 公开 API ─────────────────────────────────────────

    def set_ssh_run_fn(self, fn: Callable) -> None:
        self._ssh_run_fn = fn

    def set_project_context(self, project_id: str) -> None:
        """切换当前项目上下文，自动刷新筛选。"""
        self._current_project_id = project_id
        if self._project_filter:
            self._rebuild_list()

    def append_log(self, level: str, message: str, execution_id: str = "",
                   project_id: str = "") -> None:
        ts = time.strftime("%m-%d %H:%M:%S")
        pid = project_id or self._current_project_id
        entry = _LogEntry(ts, level.upper(), message, execution_id, pid)
        self._entries.append(entry)
        if len(self._entries) > MAX_LOG_ENTRIES:
            self._entries = self._entries[len(self._entries) - MAX_LOG_ENTRIES:]
            self._rebuild_list()
            return
        self._maybe_add_item(entry)
        self._update_counts()

    def set_execution_context(self, execution_id: str, task_dir: str) -> None:
        self.stop_tailing()
        self._current_exec_id = execution_id
        self._current_task_dir = task_dir
        self._exec_label.setText(f"正在监控: {execution_id[:16]}")
        self.append_log("INFO", f"开始监控任务 {execution_id[:16]}", execution_id)
        self._start_tailing()

    def stop_tailing(self) -> None:
        if self._tail_timer:
            self._tail_timer.stop()
            self._tail_timer = None
        if self._tail_worker:
            self._tail_worker.stop()
            self._tail_worker = None
        if self._tail_thread and self._tail_thread.isRunning():
            self._tail_thread.quit()
            self._tail_thread.wait(2000)
            self._tail_thread = None
        if self._current_exec_id:
            self._exec_label.setText("")
            self._current_exec_id = ""
            self._current_task_dir = ""

    def clear_logs(self) -> None:
        self._entries.clear()
        self._list.clear()
        self._update_counts()

    # ── 远端日志轮询 ─────────────────────────────────────

    def _start_tailing(self) -> None:
        if not self._ssh_run_fn or not self._current_task_dir:
            return
        self._tail_thread = QThread()
        self._tail_worker = _LogTailWorker(self._ssh_run_fn, self._current_task_dir)
        self._tail_worker.moveToThread(self._tail_thread)
        self._tail_worker.new_lines.connect(self._on_new_remote_lines)
        self._tail_thread.start()
        self._tail_timer = QTimer()
        self._tail_timer.setInterval(TAIL_INTERVAL_MS)
        self._tail_timer.timeout.connect(self._do_poll)
        self._tail_timer.start()
        QTimer.singleShot(0, self._do_poll)

    def _do_poll(self) -> None:
        if self._tail_worker:
            self._tail_worker.poll()

    def _on_new_remote_lines(self, lines: list[str]) -> None:
        eid = self._current_exec_id
        for raw in lines:
            level, msg = _parse_level(raw)
            self.append_log(level, msg, eid)

    # ── 筛选 / 渲染 ─────────────────────────────────────

    def _matches_filter(self, entry: _LogEntry) -> bool:
        # 项目筛选
        if self._project_filter and self._current_project_id:
            if entry.project_id and entry.project_id != self._current_project_id:
                return False
        lf = self._level_combo.currentText()
        if lf != "ALL" and entry.level != lf:
            return False
        tf = self._filter_input.text().strip()
        if tf and tf.lower() not in entry.message.lower():
            return False
        return True

    def _on_project_filter_toggled(self, checked: bool) -> None:
        self._project_filter = checked
        self._rebuild_list()

    def _maybe_add_item(self, entry: _LogEntry) -> None:
        if not self._matches_filter(entry):
            return
        self._add_item(entry)
        sb = self._list.verticalScrollBar()
        if sb and sb.value() >= sb.maximum() - 60:
            self._list.scrollToBottom()

    def _add_item(self, entry: _LogEntry) -> None:
        item = QListWidgetItem()
        item.setData(_ENTRY_ROLE, entry)
        self._list.addItem(item)

    def _apply_filter(self) -> None:
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        self._list.clear()
        for e in self._entries:
            if self._matches_filter(e):
                self._add_item(e)
        self._update_counts()
        self._list.scrollToBottom()

    def _update_counts(self) -> None:
        n = len(self._entries)
        self._count_label.setText(f"共 {n} 条日志")
        has_items = self._list.count() > 0
        self._list.setVisible(has_items)
        self._empty_label.setVisible(not has_items)
