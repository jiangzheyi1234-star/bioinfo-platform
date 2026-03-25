from __future__ import annotations

import logging
import posixpath
import shlex
from typing import Optional

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import get_config, save_config
from core.data.database_service import DatabaseCheckResult, DatabaseInfo, DatabaseService, DatabaseStatus
from ui.page_base import BasePage
from ui.widgets.database_management_components import (
    DatabaseInstallDialog,
    DatabaseInstallMonitor,
    DatabaseItemCard,
    DatabaseStatusWorker,
)
from ui.widgets.styles import BUTTON_PRIMARY, BUTTON_SECONDARY, INPUT_LINEEDIT, PAGE_HEADER_TITLE

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "reads": "物种分类",
    "mag": "组装质控",
    "annotation": "功能注释",
    "amr": "AMR",
    "other": "其他",
}

_ICON_COLOR = "#64748B"
_ICON_COLOR_HOVER = "#0EA5E9"
_SETTINGS_ICON_COLOR = "#64748B"

_GHOST_BTN_STYLE = """
    QPushButton {
        background: transparent;
        color: #64748B;
        border: none;
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 13px;
    }
    QPushButton:hover {
        background: #DBEAFE;
        color: #0EA5E9;
    }
    QPushButton:pressed {
        background: #BFDBFE;
    }
"""

_ICON_BTN_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        border-radius: 14px;
    }
    QPushButton:hover {
        background: #E2E8F0;
    }
    QPushButton:pressed {
        background: #CBD5E1;
    }
"""

_SCROLL_BAR_GRAY = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(100, 116, 139, 0.22);
        border-radius: 5px;
        min-height: 40px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(100, 116, 139, 0.35);
    }
    QScrollBar::handle:vertical:pressed {
        background: rgba(100, 116, 139, 0.48);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
        background: transparent;
        border: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""


class RemoteDirectoryPickerDialog(QDialog):
    def __init__(self, start_path: str, list_dirs_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择数据库根目录")
        self.resize(560, 460)
        self._list_dirs_fn = list_dirs_fn
        self.selected_path = ""
        self._current_path = ""
        self._build_ui()
        self._load_path(start_path or "~")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        nav = QHBoxLayout()
        self.up_btn = QPushButton("上级")
        self.up_btn.setStyleSheet(BUTTON_SECONDARY)
        self.up_btn.clicked.connect(self._go_parent)
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("font-size: 12px; color: #334155;")
        nav.addWidget(self.up_btn)
        nav.addWidget(self.path_label, stretch=1)
        root.addLayout(nav)

        self.dir_list = QListWidget()
        self.dir_list.itemDoubleClicked.connect(self._open_child)
        self.dir_list.currentItemChanged.connect(self._on_item_selected)
        root.addWidget(self.dir_list, stretch=1)

        self.selected_label = QLabel("当前选择: ")
        self.selected_label.setStyleSheet("font-size: 12px; color: #475569;")
        root.addWidget(self.selected_label)

        foot = QHBoxLayout()
        foot.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        self.cancel_btn.clicked.connect(self.reject)
        self.select_btn = QPushButton("选择此目录")
        self.select_btn.setStyleSheet(BUTTON_PRIMARY)
        self.select_btn.clicked.connect(self._accept_selected)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.select_btn)
        root.addLayout(foot)

    def _load_path(self, raw_path: str) -> None:
        ok, resolved, dirs, message = self._list_dirs_fn(raw_path)
        if not ok:
            QMessageBox.warning(self, "目录浏览", message)
            return
        self._current_path = resolved
        self.selected_path = resolved
        self.path_label.setText(f"当前位置: {resolved}")
        self.selected_label.setText(f"当前选择: {resolved}")
        self.dir_list.clear()
        for name in dirs:
            item = QListWidgetItem(f"[DIR] {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.dir_list.addItem(item)

    def _go_parent(self) -> None:
        if not self._current_path:
            return
        parent = posixpath.dirname(self._current_path.rstrip("/")) or "/"
        self._load_path(parent)

    def _open_child(self, item: QListWidgetItem) -> None:
        name = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not name:
            return
        child = posixpath.join(self._current_path, name)
        self._load_path(child)

    def _on_item_selected(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        if current is None:
            self.selected_path = self._current_path
            self.selected_label.setText(f"当前选择: {self.selected_path}")
            return
        name = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        self.selected_path = posixpath.join(self._current_path, name) if name else self._current_path
        self.selected_label.setText(f"当前选择: {self.selected_path}")

    def _accept_selected(self) -> None:
        self.selected_path = self.selected_path or self._current_path
        if not self.selected_path:
            QMessageBox.warning(self, "目录浏览", "请选择有效目录。")
            return
        self.accept()


class DatabaseSettingsDialog(QDialog):
    def __init__(self, initial_path: str, info_fn, browse_fn, save_fn, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据库设置")
        self.setFixedWidth(520)
        self._info_fn = info_fn
        self._browse_fn = browse_fn
        self._save_fn = save_fn
        self._build_ui()
        self.path_edit.setText(initial_path)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.timeout.connect(self._refresh_info)
        self.path_edit.textChanged.connect(self._schedule_refresh_info)
        self._refresh_info()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        title = QLabel("数据库根目录")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #071828;")
        root.addWidget(title)

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setStyleSheet(INPUT_LINEEDIT)
        self.path_edit.setPlaceholderText("~/databases")
        browse_btn = QPushButton("📁 浏览")
        browse_btn.setStyleSheet(BUTTON_SECONDARY)
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(self.path_edit, stretch=1)
        row.addWidget(browse_btn)
        root.addLayout(row)

        hint = QLabel("所有数据库默认安装位置")
        hint.setStyleSheet("font-size: 12px; color: #4A7A90;")
        root.addWidget(hint)

        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(6)
        self.info_icon = QLabel()
        self.info_icon.setPixmap(qta.icon("ph.map-pin", color="#0EA5E9").pixmap(QSize(14, 14)))
        self.info_icon.setFixedSize(14, 14)
        self.info_line = QLabel("--")
        self.info_line.setStyleSheet("font-size: 12px; color: #0369A1;")
        info_row.addWidget(self.info_icon)
        info_row.addWidget(self.info_line, stretch=1)
        root.addLayout(info_row)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet(BUTTON_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(BUTTON_PRIMARY)
        save_btn.clicked.connect(self._on_save)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        root.addLayout(actions)

    def _schedule_refresh_info(self) -> None:
        self._info_timer.start(250)

    def _refresh_info(self) -> None:
        info = self._info_fn(self.path_edit.text().strip())
        self.info_line.setText(str(info.get("resolved", "--") or "--"))

    def _on_browse(self) -> None:
        selected = self._browse_fn(self.path_edit.text().strip())
        if selected:
            self.path_edit.setText(selected)

    def _on_save(self) -> None:
        if self._save_fn(self.path_edit.text().strip()):
            self.accept()


class DatabasePage(BasePage):
    def __init__(self):
        super().__init__("数据库管理")
        self.label.hide()
        self._ssh_client = None
        self._db_root_value = ""
        self._database_service = DatabaseService()
        self._cards: dict[str, DatabaseItemCard] = {}
        self._dialogs: dict[str, DatabaseInstallDialog] = {}
        self._status_thread: Optional[object] = None
        self._status_worker: Optional[DatabaseStatusWorker] = None
        self._install_threads: dict[str, object] = {}
        self._install_workers: dict[str, DatabaseInstallMonitor] = {}
        self._init_ui()
        self._load_db_root()

    def _init_ui(self) -> None:
        self.layout.setContentsMargins(30, 24, 30, 24)
        self.layout.setSpacing(10)

        # ── 标题行 ──────────────────────────────────────────
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel("数据库管理")
        title.setStyleSheet(PAGE_HEADER_TITLE)

        # 设置按钮（圆形图标）
        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(qta.icon("ph.gear-six", color=_SETTINGS_ICON_COLOR))
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.setToolTip("数据库设置")
        self.settings_btn.setStyleSheet(_ICON_BTN_STYLE)
        self.settings_btn.clicked.connect(self._open_db_settings_dialog)

        # 刷新按钮（幽灵按钮 + 图标）
        self.refresh_btn = QPushButton("  刷新")
        self.refresh_btn.setIcon(qta.icon("ph.arrows-clockwise", color=_ICON_COLOR))
        self.refresh_btn.setIconSize(QSize(15, 15))
        self.refresh_btn.setStyleSheet(_GHOST_BTN_STYLE)
        self.refresh_btn.clicked.connect(self._refresh_all_status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #E2E8F0; max-height: 20px;")

        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.refresh_btn)
        title_row.addWidget(sep)
        title_row.addWidget(self.settings_btn)
        self.layout.addLayout(title_row)

        # ── Tab ────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar {
                background: transparent;
            }
            QTabBar::tab {
                background: transparent;
                color: #64748B;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 8px 18px 10px 18px;
                font-size: 13px;
                font-weight: 600;
                min-width: 72px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                color: #0EA5E9;
                font-weight: 700;
                border-bottom: 2px solid #3B82F6;
            }
            QTabBar::tab:hover:!selected {
                color: #0284C7;
            }
            """
        )
        self.layout.addWidget(self.tabs, stretch=1)

        grouped = self._database_service.list_by_category()
        for category in ("reads", "mag", "annotation", "amr", "other"):
            infos = grouped.get(category, [])
            page = self._build_category_page(infos)
            self.tabs.addTab(page, CATEGORY_LABELS.get(category, category))

    def _build_category_page(self, infos: list[DatabaseInfo]) -> QWidget:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.verticalScrollBar().setStyleSheet(_SCROLL_BAR_GRAY)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)
        for info in infos:
            card = DatabaseItemCard(info)
            card.install_requested.connect(self._on_install_clicked)
            card.path_override_requested.connect(self._on_path_override)
            card.cancel_requested.connect(self._on_cancel_install)
            self._cards[info.db_id] = card
            content_layout.addWidget(card)
        content_layout.addStretch()
        scroll.setWidget(content)
        host_layout.addWidget(scroll)
        return host

    def _load_db_root(self) -> None:
        cfg = get_config()
        databases = cfg.get("databases", {})
        self._db_root_value = str(databases.get("db_root", "") or "")

    def _get_db_root(self) -> str:
        return str(self._db_root_value or "").strip()

    def _save_db_root(self, raw_input: str = "") -> bool:
        if self._ssh_client is None:
            QMessageBox.warning(self, "数据库配置", "请先连接 SSH，再保存数据库根目录。")
            return False

        candidate = raw_input
        if not candidate:
            candidate = self._resolve_empty_db_root_candidate()
            if not candidate:
                return False

        allow_create = False
        expanded = self._expand_remote_path(candidate)
        if expanded and expanded.startswith("/"):
            normalized = self._normalize_remote_path(expanded)
            qroot = shlex.quote(normalized)
            rc_exists, _, _ = self._run_ssh(f"test -d {qroot}", 10)
            if rc_exists != 0:
                answer = QMessageBox.question(
                    self,
                    "目录不存在",
                    f"目录不存在：{normalized}\n是否现在创建该目录并继续保存？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return False
                allow_create = True

        ok, resolved_root, message, created = self._validate_db_root_remote(candidate, allow_create=allow_create)
        if not ok:
            QMessageBox.warning(self, "数据库配置", message)
            return False

        db_root = str(raw_input or "").strip()
        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            databases = {}
        databases["db_root"] = resolved_root
        databases.setdefault("overrides", {})
        cfg["databases"] = databases
        if self._empty_db_root_preference:
            runtime = cfg.get("runtime", {})
            if not isinstance(runtime, dict):
                runtime = {}
            runtime["db_root_empty_action"] = self._empty_db_root_preference
            cfg["runtime"] = runtime
        save_config(cfg)
        self._db_root_value = resolved_root
        if created:
            QMessageBox.information(self, "数据库配置", f"已自动创建并保存目录: {resolved_root}")
        else:
            QMessageBox.information(self, "数据库配置", f"数据库根目录已保存: {resolved_root}")
        self._refresh_all_status()
        return True

    def _open_db_settings_dialog(self) -> None:
        dialog = DatabaseSettingsDialog(
            initial_path=self._get_db_root(),
            info_fn=self._collect_db_root_info,
            browse_fn=self._pick_remote_db_root,
            save_fn=self._save_db_root,
            parent=self,
        )
        dialog.exec()

    def _pick_remote_db_root(self, start_path: str = "") -> str:
        if self._ssh_client is None:
            QMessageBox.warning(self, "目录浏览", "请先连接 SSH，再浏览远程目录。")
            return ""
        start_path = start_path or self._get_db_root() or "~"
        dialog = RemoteDirectoryPickerDialog(start_path, self._list_remote_directories, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_path:
            return dialog.selected_path
        return ""

    def _run_ssh(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        run_fn = self._make_ssh_run_fn()
        return run_fn(cmd, timeout)

    def _list_remote_directories(self, raw_path: str) -> tuple[bool, str, list[str], str]:
        resolved = self._expand_remote_path(raw_path)
        if not resolved:
            return False, "", [], f"无法解析远程路径: {raw_path}"
        if not resolved.startswith("/"):
            return False, "", [], f"目录必须是绝对路径: {resolved}"
        resolved = self._normalize_remote_path(resolved)
        qpath = shlex.quote(resolved)
        rc_exists, _, _ = self._run_ssh(f"test -d {qpath}", 10)
        if rc_exists != 0:
            return False, "", [], f"目录不存在: {resolved}"

        cmd = f"find {qpath} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | LC_ALL=C sort"
        rc, stdout, stderr = self._run_ssh(cmd, 12)
        if rc != 0:
            return False, "", [], f"读取目录失败: {stderr.strip() or resolved}"
        dirs = [line.strip() for line in stdout.splitlines() if line.strip()]
        return True, resolved, dirs, ""

    def _collect_db_root_info(self, raw_path: str) -> dict[str, str]:
        if self._ssh_client is None:
            return {"resolved": "--"}
        candidate = str(raw_path or "").strip() or "~"
        resolved = self._expand_remote_path(candidate)
        return {"resolved": resolved or "--"}

    def _expand_remote_path(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path:
            return ""
        qpath = shlex.quote(path)
        cmd = (
            f"p={qpath}; "
            'if [ "$p" = "~" ]; then printf "%s\\n" "$HOME"; '
            'elif [ "${p#~/}" != "$p" ]; then printf "%s\\n" "$HOME/${p#~/}"; '
            'else printf "%s\\n" "$p"; fi'
        )
        rc, stdout, _ = self._run_ssh(cmd, 10)
        expanded = stdout.strip() if rc == 0 else ""
        if expanded.startswith("~"):
            home = self._get_remote_home()
            if home:
                if expanded == "~":
                    expanded = home
                elif expanded.startswith("~/"):
                    expanded = f"{home}/{expanded[2:]}"
        return expanded

    def _get_remote_home(self) -> str:
        rc, out, _ = self._run_ssh("printf '%s\\n' \"$HOME\"", 10)
        home = out.strip() if rc == 0 else ""
        return home if home.startswith("/") else ""

    def _normalize_remote_path(self, resolved: str) -> str:
        normalized = posixpath.normpath(str(resolved or "").strip())
        if not normalized.startswith("/"):
            return normalized
        return normalized if normalized == "/" else normalized.rstrip("/")

    def _validate_db_root_remote(self, raw_path: str, allow_create: bool = False) -> tuple[bool, str, str, bool]:
        path = str(raw_path or "").strip()
        if not path:
            return False, "", "数据库根目录不能为空。", False

        resolved = self._expand_remote_path(path)
        if not resolved:
            return False, "", f"无法解析远程路径: {path}", False
        if not resolved.startswith("/"):
            return False, "", f"数据库根目录必须是绝对路径，当前为: {resolved}", False
        resolved = self._normalize_remote_path(resolved)

        created = False
        qroot = shlex.quote(resolved)
        rc, _, _ = self._run_ssh(f"test -d {qroot}", 10)
        if rc != 0:
            if allow_create:
                rc_create, _, err_create = self._run_ssh(f"mkdir -p {qroot}", 15)
                if rc_create != 0:
                    return False, "", f"目录不存在且无法自动创建: {resolved}\n错误: {err_create.strip() or '权限不足'}", False
                created = True
            else:
                return False, "", f"目录不存在: {resolved}", False

        rc_exec, _, _ = self._run_ssh(f"test -x {qroot}", 10)
        if rc_exec != 0:
            return False, "", f"目录不可进入(-x): {resolved}", created

        rc_write, _, _ = self._run_ssh(f"test -w {qroot}", 10)
        if rc_write != 0:
            return False, "", self._build_permission_denied_message(resolved), created

        probe = f"{qroot}/.h2ometa_write_probe"
        rc_probe, _, err_probe = self._run_ssh(f"touch {probe} && rm -f {probe}", 10)
        if rc_probe != 0:
            return False, "", self._build_permission_denied_message(resolved, detail=err_probe.strip() or "写入探针失败"), created

        return True, resolved, "", created

    @property
    def _empty_db_root_preference(self) -> str:
        cfg = get_config()
        runtime = cfg.get("runtime", {})
        if not isinstance(runtime, dict):
            return ""
        value = str(runtime.get("db_root_empty_action", "") or "").strip().lower()
        return value if value in {"use_home"} else ""

    def _resolve_empty_db_root_candidate(self) -> str:
        if self._empty_db_root_preference == "use_home":
            return "~/databases"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("数据库配置")
        msg.setText("尚未设置数据库根目录，建议使用 ~/databases。")
        msg.setInformativeText("请选择下一步操作。")
        use_home_btn = msg.addButton("使用 ~/databases", QMessageBox.ButtonRole.AcceptRole)
        manual_btn = msg.addButton("手动输入", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        remember_box = QCheckBox("记住这次选择")
        msg.setCheckBox(remember_box)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == use_home_btn:
            if remember_box.isChecked():
                cfg = get_config()
                runtime = cfg.get("runtime", {})
                if not isinstance(runtime, dict):
                    runtime = {}
                runtime["db_root_empty_action"] = "use_home"
                cfg["runtime"] = runtime
                save_config(cfg)
            return "~/databases"
        if clicked == manual_btn:
            return ""
        if clicked == cancel_btn:
            return ""
        return ""

    def _build_permission_denied_message(self, db_root: str, detail: str = "") -> str:
        user = "your_user"
        rc_user, stdout_user, _ = self._run_ssh("whoami", 10)
        if rc_user == 0 and stdout_user.strip():
            user = stdout_user.strip()
        lines = [
            f"当前 SSH 用户对目录无写权限: {db_root}",
            "建议改用: ~/databases（会映射到当前用户 HOME 目录）",
            "如需继续使用该目录，请联系管理员执行：",
            "# 个人目录方案",
            f"mkdir -p {db_root}",
            f"chown {user}:{user} {db_root}",
            f"chmod 775 {db_root}",
            "# 共享目录方案（按实际组名替换 bio）",
            f"chgrp bio {db_root}",
            f"chmod 2775 {db_root}",
        ]
        if detail:
            lines.append(f"详细错误: {detail}")
        return "\n".join(lines)

    def set_active_client(self, client) -> None:
        self._ssh_client = client
        if client is None:
            for card in self._cards.values():
                card.update_status(DatabaseCheckResult(db_id=card.db_info.db_id, status=DatabaseStatus.UNKNOWN))
            return
        self._refresh_all_status()

    def refresh_context(self) -> None:
        if self._ssh_client is not None:
            self._refresh_all_status()

    def _make_ssh_run_fn(self):
        client = self._ssh_client
        if client is None:
            raise RuntimeError("SSH client is not connected")

        def _run(cmd: str, timeout: int = 15):
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            del stdin
            rc = stdout.channel.recv_exit_status()
            return rc, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")

        return _run

    def _cleanup_status_worker(self) -> None:
        if self._status_worker is not None and hasattr(self._status_worker, "cancel"):
            self._status_worker.cancel()
        if self._status_thread is not None:
            self._status_thread.quit()
            self._status_thread.wait(1500)
            self._status_thread.deleteLater()
        self._status_worker = None
        self._status_thread = None

    def _refresh_all_status(self) -> None:
        if self._ssh_client is None:
            return
        from PyQt6.QtCore import QThread
        self._cleanup_status_worker()
        self._status_thread = QThread(self)
        self._status_worker = DatabaseStatusWorker(
            database_service=self._database_service,
            ssh_run_fn=self._make_ssh_run_fn(),
            db_root=self._get_db_root(),
        )
        self._status_worker.moveToThread(self._status_thread)
        self._status_thread.started.connect(self._status_worker.run)
        self._status_worker.status_checked.connect(self._on_status_checked)
        self._status_worker.all_done.connect(self._cleanup_status_worker)
        self._status_worker.error.connect(self._on_status_error)
        self._status_thread.start()

    def _on_status_checked(self, db_id: str, result) -> None:
        card = self._cards.get(db_id)
        if card is not None:
            card.update_status(result)

    def _on_status_error(self, message: str) -> None:
        logger.warning("Database status refresh failed: %s", message)
        self._cleanup_status_worker()

    def _on_install_clicked(self, db_id: str) -> None:
        if self._ssh_client is None:
            QMessageBox.warning(self, "数据库安装", "请先连接 SSH。")
            return
        info = self._database_service.get_info(db_id)
        if info is None:
            return
        try:
            commands = self._database_service.generate_install_commands(db_id, self._get_db_root())
        except Exception as exc:
            QMessageBox.warning(self, "数据库安装", str(exc))
            return
        dialog = DatabaseInstallDialog(info, commands, parent=self)
        self._dialogs[db_id] = dialog
        dialog.install_confirmed.connect(self._start_install)
        dialog.install_cancelled.connect(lambda _: self._dialogs.pop(db_id, None))
        dialog.show()

    def _start_install(self, db_id: str, mirror_index: int) -> None:
        card = self._cards.get(db_id)
        if card is None:
            return
        try:
            result = self._database_service.submit_install(
                self._make_ssh_run_fn(),
                db_id=db_id,
                db_root=self._get_db_root(),
                mirror_index=mirror_index,
            )
        except Exception as exc:
            QMessageBox.warning(self, "数据库安装", f"提交安装任务失败: {exc}")
            return
        card.set_installing(True)
        self._start_install_monitor(db_id, result["task_dir"])

    def _start_install_monitor(self, db_id: str, task_dir: str) -> None:
        from PyQt6.QtCore import QThread
        self._stop_install_monitor(db_id)
        thread = QThread(self)
        worker = DatabaseInstallMonitor(
            database_service=self._database_service,
            ssh_run_fn=self._make_ssh_run_fn(),
            db_id=db_id,
            task_dir=task_dir,
            db_root=self._get_db_root(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_updated.connect(self._on_progress_updated)
        worker.log_updated.connect(self._on_log_updated)
        worker.install_finished.connect(self._on_install_finished)
        self._install_threads[db_id] = thread
        self._install_workers[db_id] = worker
        thread.start()

    def _stop_install_monitor(self, db_id: str) -> None:
        worker = self._install_workers.pop(db_id, None)
        if worker is not None and hasattr(worker, "cancel"):
            worker.cancel()
        thread = self._install_threads.pop(db_id, None)
        if thread is not None:
            thread.quit()
            if not thread.wait(1500):
                logger.warning("Database install thread did not stop in time: %s", db_id)
            thread.deleteLater()

    def _on_progress_updated(self, db_id: str, percent: int, speed: str, eta: str) -> None:
        card = self._cards.get(db_id)
        if card:
            card.update_progress(percent, speed=speed, eta=eta)
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.update_progress(percent, speed, eta)

    def _on_log_updated(self, db_id: str, log_text: str) -> None:
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.update_log(log_text)

    def _on_install_finished(self, db_id: str, success: bool, message: str) -> None:
        self._stop_install_monitor(db_id)
        card = self._cards.get(db_id)
        if card is not None:
            card.set_installing(False)
        dialog = self._dialogs.get(db_id)
        if dialog:
            dialog.show_result(success, message)
        self._refresh_all_status()

    def _on_path_override(self, db_id: str) -> None:
        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            databases = {}
        overrides = databases.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        current = str(overrides.get(db_id, "") or "")
        value, ok = QInputDialog.getText(self, "数据库路径覆盖", f"设置 {db_id} 的绝对路径:", text=current)
        if not ok:
            return
        path = str(value or "").strip()
        if path:
            overrides[db_id] = path
        else:
            overrides.pop(db_id, None)
        databases["overrides"] = overrides
        databases.setdefault("db_root", self._get_db_root())
        cfg["databases"] = databases
        save_config(cfg)
        self._refresh_all_status()

    def _on_cancel_install(self, db_id: str) -> None:
        self._stop_install_monitor(db_id)
        card = self._cards.get(db_id)
        if card:
            card.set_installing(False)
        dialog = self._dialogs.pop(db_id, None)
        if dialog:
            dialog.reject()

    def closeEvent(self, event) -> None:
        self._cleanup_status_worker()
        for db_id in list(self._install_threads.keys()):
            self._stop_install_monitor(db_id)
        super().closeEvent(event)
