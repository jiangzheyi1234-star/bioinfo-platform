"""日志页面（Clash 风格独立实现）。"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
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
    "INFO": "#3B82F6",
    "SUCCESS": "#10B981",
    "WARNING": "#F59E0B",
    "ERROR": "#EF4444",
}
_ALL_LEVELS = ["ALL", "INFO", "SUCCESS", "WARNING", "ERROR"]
_ENTRY_ROLE = Qt.ItemDataRole.UserRole


class _LogEntry:
    __slots__ = ("ts", "level", "message", "execution_id", "project_id")

    def __init__(self, ts: str, level: str, message: str, eid: str = "", project_id: str = ""):
        self.ts = ts
        self.level = level
        self.message = message
        self.execution_id = eid
        self.project_id = project_id


class _LogDelegate(QStyledItemDelegate):
    """两行日志条目：时间+级别，消息正文。"""

    _PAD_H = 12
    _PAD_V = 8
    _LINE_GAP = 3

    def paint(self, painter, option: QStyleOptionViewItem, index):
        entry: Optional[_LogEntry] = index.data(_ENTRY_ROLE)
        if not entry:
            return

        painter.save()
        rect = option.rect

        painter.fillRect(rect, QColor("#F5F7FA"))

        x = rect.x() + self._PAD_H
        w = rect.width() - self._PAD_H * 2

        ts_font = QFont(styles.FONT_FAMILY.split(",")[0].strip("' "), 11)
        ts_fm = QFontMetrics(ts_font)
        y1 = rect.y() + self._PAD_V + ts_fm.ascent()

        painter.setFont(ts_font)
        painter.setPen(QColor("#8B98AB"))
        painter.drawText(x, y1, entry.ts)
        ts_w = ts_fm.horizontalAdvance(entry.ts)

        lvl_font = QFont(ts_font)
        lvl_font.setWeight(QFont.Weight.Bold)
        painter.setFont(lvl_font)
        painter.setPen(QColor(_LEVEL_COLORS.get(entry.level, _LEVEL_COLORS["INFO"])))
        painter.drawText(x + ts_w + 10, y1, entry.level)

        msg_font = QFont(styles.FONT_FAMILY.split(",")[0].strip("' "), 11)
        msg_fm = QFontMetrics(msg_font)
        y2 = y1 + ts_fm.descent() + self._LINE_GAP + msg_fm.ascent()

        painter.setFont(msg_font)
        painter.setPen(QColor("#172B4D"))
        elided = msg_fm.elidedText(entry.message, Qt.TextElideMode.ElideRight, w)
        painter.drawText(x, y2, elided)

        painter.setPen(QPen(QColor("#DCE3EC"), 1))
        painter.drawLine(rect.x() + 6, rect.bottom(), rect.right() - 6, rect.bottom())

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, 54)


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


class LogPage(BasePage):
    """实时日志页面。"""
    log_status_changed = pyqtSignal(str)
    request_tail_poll = pyqtSignal()

    def __init__(self, main_window=None) -> None:
        super().__init__("日志")
        self._main_window = main_window
        self._entries: list[_LogEntry] = []
        self._ssh_run_fn: Optional[Callable] = None
        self._current_exec_id = ""
        self._current_task_dir = ""
        self._current_project_id = ""

        # 默认关闭项目筛选，仅保留兼容能力。
        self._project_filter = False

        self._tail_paused = False
        self._auto_scroll = True
        self._paused_buffer: list[tuple[str, str, str]] = []

        self._tail_worker: Optional[_LogTailWorker] = None
        self._tail_thread: Optional[QThread] = None
        self._tail_timer: Optional[QTimer] = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.label.hide()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        page_bg = "#EEF2F7"
        self.setStyleSheet(f"background:{page_bg};")

        header = QHBoxLayout()
        header.setContentsMargins(22, 14, 22, 10)

        title = QLabel("日志")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A;")
        header.addWidget(title)
        header.addStretch()

        self._clear_btn = QPushButton("清除")
        self._clear_btn.setFixedSize(96, 36)
        self._clear_btn.setStyleSheet(
            """
            QPushButton {
                border: none;
                border-radius: 10px;
                background: #2F6FE4;
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover { background: #2A62CA; }
            QPushButton:pressed { background: #244FA8; }
            """
        )
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        header.addWidget(self._clear_btn)
        self.layout.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(22, 0, 22, 10)
        toolbar.setSpacing(10)
        toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        control_h = 38
        self._level_combo = QComboBox()
        self._level_combo.addItems(_ALL_LEVELS)
        self._level_combo.setFixedSize(106, control_h)
        self._level_combo.setStyleSheet(
            """
            QComboBox {
                border: 1px solid #C9D2E0;
                border-radius: 8px;
                padding: 0 12px;
                background: #FFFFFF;
                color: #1F2D3D;
                font-size: 12px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            """
        )
        self._level_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._level_combo)
        toolbar.addStretch()

        self.layout.addLayout(toolbar)

        self._list = QListWidget()
        self._list.setItemDelegate(_LogDelegate(self._list))
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            f"QListWidget{{border:none; background:{page_bg}; outline:none;}}"
            "QListWidget::item{border:none; padding:0;}"
            f"{styles.SCROLL_BAR_ELEGANT}"
        )
        self.layout.addWidget(self._list, stretch=1)

        self._empty_label = QLabel("暂无日志")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color:#8B98AB; font-size:14px; background:transparent;")
        self._empty_label.setVisible(True)
        self.layout.addWidget(self._empty_label, stretch=1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(22, 4, 22, 8)
        self._count_label = QLabel("共 0 条日志")
        self._count_label.setStyleSheet("font-size:11px; color:#8B98AB; background:transparent;")
        bottom.addWidget(self._count_label)
        bottom.addStretch()
        self._exec_label = QLabel("")
        self._exec_label.setStyleSheet("font-size:11px; color:#8B98AB; background:transparent;")
        bottom.addWidget(self._exec_label)
        self.layout.addLayout(bottom)

        self._tail_paused = False
        self._auto_scroll = True
        self.log_status_changed.emit("日志: 就绪")

    def set_ssh_run_fn(self, fn: Callable) -> None:
        self._ssh_run_fn = fn

    def set_project_context(self, project_id: str) -> None:
        self._current_project_id = project_id
        if self._project_filter:
            self._rebuild_list()

    def load_history(self, db: sqlite3.Connection, project_id: str) -> None:
        try:
            rows = db.execute(
                "SELECT execution_id, tool_id, status, created_at, completed_at, error "
                "FROM executions ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        except Exception:
            logger.debug("加载执行历史失败", exc_info=True)
            return
        payload = [
            {
                "execution_id": row[0],
                "tool_id": row[1],
                "status": row[2],
                "created_at": row[3],
                "completed_at": row[4] if len(row) > 4 else None,
                "error": row[5] if len(row) > 5 else "",
            }
            for row in rows
        ]
        self.load_history_rows(payload, project_id)

    def load_history_rows(self, rows: list[dict], project_id: str) -> None:
        try:
            parsed_rows = list(rows or [])
        except Exception:
            logger.debug("日志历史数据格式异常", exc_info=True)
            return

        if not parsed_rows:
            return

        status_map = {
            "completed": ("SUCCESS", "完成"),
            "failed": ("ERROR", "失败"),
            "running": ("WARNING", "运行中"),
            "pending": ("INFO", "等待中"),
            "retrying": ("WARNING", "重试中"),
        }
        for row in reversed(parsed_rows):
            eid = row.get("execution_id", "")
            tool = row.get("tool_id", "")
            status = row.get("status", "")
            created = row.get("created_at")
            error = row.get("error", "")
            ts = datetime.fromtimestamp(created).strftime("%m-%d %H:%M:%S") if created else "??-?? ??:??:??"
            level, label = status_map.get(status, ("INFO", status))
            msg = f"[历史] {tool} — {label}"
            if status == "failed" and error:
                msg += f": {error[:80]}"
            self._entries.append(_LogEntry(ts, level, msg, eid, project_id))

        self._rebuild_list()

    def append_log(self, level: str, message: str, execution_id: str = "", project_id: str = "") -> None:
        ts = time.strftime("%m-%d %H:%M:%S")
        pid = project_id or self._current_project_id
        entry = _LogEntry(ts, level.upper(), message, execution_id, pid)
        self._entries.append(entry)
        if len(self._entries) > MAX_LOG_ENTRIES:
            self._entries = self._entries[len(self._entries) - MAX_LOG_ENTRIES :]
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
            try:
                self.request_tail_poll.disconnect(self._tail_worker.poll)
            except (TypeError, RuntimeError):
                pass
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
        self._paused_buffer.clear()
        self._list.clear()
        self._update_counts()

    def _on_clear_clicked(self) -> None:
        if self._project_filter and self._current_project_id:
            self._entries = [entry for entry in self._entries if entry.project_id != self._current_project_id]
            self._rebuild_list()
            self.log_status_changed.emit("日志: 已清除当前项目")
            return
        self.clear_logs()
        self.log_status_changed.emit("日志: 已清除")

    def _start_tailing(self) -> None:
        if not self._ssh_run_fn or not self._current_task_dir:
            return
        self._tail_thread = QThread()
        self._tail_worker = _LogTailWorker(self._ssh_run_fn, self._current_task_dir)
        self._tail_worker.moveToThread(self._tail_thread)
        self._tail_worker.new_lines.connect(self._on_new_remote_lines)
        self.request_tail_poll.connect(
            self._tail_worker.poll,
            Qt.ConnectionType.QueuedConnection,
        )
        self._tail_thread.start()
        self._tail_timer = QTimer()
        self._tail_timer.setInterval(TAIL_INTERVAL_MS)
        self._tail_timer.timeout.connect(self._do_poll)
        self._tail_timer.start()
        QTimer.singleShot(0, self._do_poll)

    def _do_poll(self) -> None:
        if self._tail_worker:
            self.request_tail_poll.emit()

    def _on_new_remote_lines(self, lines: list[str]) -> None:
        eid = self._current_exec_id
        for raw in lines:
            level, msg = _parse_level(raw)
            if self._tail_paused:
                self._paused_buffer.append((level, msg, eid))
                continue
            self.append_log(level, msg, eid)

    def _matches_filter(self, entry: _LogEntry) -> bool:
        if self._project_filter and self._current_project_id:
            if entry.project_id and entry.project_id != self._current_project_id:
                return False
        lf = self._level_combo.currentText()
        if lf != "ALL" and entry.level != lf:
            return False
        tf = ""
        if hasattr(self, "_filter_input") and self._filter_input is not None:
            tf = self._filter_input.text().strip()
        if tf:
            query = tf.lower()
            haystack = f"{entry.ts} {entry.level} {entry.message}".lower()
            if query not in haystack:
                return False
        return True

    def _maybe_add_item(self, entry: _LogEntry) -> None:
        if not self._matches_filter(entry):
            return
        self._add_item(entry)
        if self._auto_scroll:
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
        if self._auto_scroll:
            self._list.scrollToBottom()

    def _toggle_tail_pause(self, paused: bool) -> None:
        self._tail_paused = paused
        if hasattr(self, "_pause_btn") and self._pause_btn is not None:
            self._pause_btn.setText("▶" if paused else "II")
            self._pause_btn.setToolTip("继续实时更新" if paused else "暂停实时更新")
        self.log_status_changed.emit("日志: 暂停中" if paused else "日志: 实时更新")
        if not paused and self._paused_buffer:
            for level, msg, eid in self._paused_buffer:
                self.append_log(level, msg, eid)
            self._paused_buffer.clear()

    def _toggle_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled
        if hasattr(self, "_scroll_btn") and self._scroll_btn is not None:
            self._scroll_btn.setToolTip("自动定位到底部" if enabled else "关闭自动定位")
        mode = "自动置底" if enabled else "自由滚动"
        self.log_status_changed.emit(f"日志: {mode}")
        if enabled and self._list.count() > 0:
            self._list.scrollToBottom()

    def _update_counts(self) -> None:
        n = len(self._entries)
        self._count_label.setText(f"共 {n} 条日志")
        has_items = self._list.count() > 0
        self._list.setVisible(has_items)
        self._empty_label.setVisible(not has_items)
