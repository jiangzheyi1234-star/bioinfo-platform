"""远程文件浏览器 — 通过 SFTP 浏览远端服务器文件系统。"""

import logging
import stat
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ui.widgets import styles

logger = logging.getLogger(__name__)


class RemoteFileDialog(QDialog):
    """通过 SFTP 浏览远端服务器目录/文件的对话框。

    用法::

        dialog = RemoteFileDialog(ssh_service, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.selected_path()
    """

    def __init__(self, ssh_service, initial_path: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("浏览远程文件")
        self.setFixedWidth(420)
        self.setMinimumHeight(340)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {styles.COLOR_BG_CARD};
                border: 1px solid {styles.COLOR_BORDER_INPUT};
                border-radius: {styles.RADIUS_CARD};
            }}
            """
        )

        self._ssh = ssh_service
        self._current_path = initial_path or self._default_home()
        self._selected: Optional[str] = None

        self._build_ui()
        self._navigate(self._current_path)

    def _default_home(self) -> str:
        """尝试获取远端用户主目录，失败回退到 /。"""
        try:
            sftp = self._ssh.sftp()
            try:
                home = sftp.normalize(".")
                return home
            finally:
                sftp.close()
        except Exception:
            return "/"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 路径栏
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        self._btn_up = QPushButton("上级")
        self._btn_up.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_up.setFixedWidth(80)
        self._btn_up.clicked.connect(self._go_up)
        nav_row.addWidget(self._btn_up)

        self._path_input = QLineEdit()
        self._path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self._path_input.returnPressed.connect(self._on_path_entered)
        nav_row.addWidget(self._path_input)

        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setStyleSheet(styles.BUTTON_SECONDARY)
        self._btn_refresh.setFixedWidth(80)
        self._btn_refresh.clicked.connect(lambda: self._navigate(self._current_path))
        nav_row.addWidget(self._btn_refresh)

        layout.addLayout(nav_row)

        # 文件列表
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["名称", "大小", "类型"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet(
            f"""
            QTreeWidget {{
                font-size: 13px;
                border: 1px solid {styles.COLOR_BORDER};
                border-radius: 8px;
                background-color: {styles.COLOR_BG_CARD};
            }}
            {styles.SCROLL_BAR_ELEGANT}
            """
        )
        header = self._tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree, stretch=1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(styles.BUTTON_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet(styles.BUTTON_PRIMARY)
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)

    def selected_path(self) -> str:
        """返回用户选择的远端文件/目录路径。"""
        return self._selected or ""

    def _navigate(self, path: str) -> None:
        """列出指定目录的内容。"""
        self._tree.clear()
        try:
            sftp = self._ssh.sftp()
            try:
                entries = sftp.listdir_attr(path)
            finally:
                sftp.close()
        except Exception as e:
            logger.exception("SFTP 列目录失败: %s", path)
            QMessageBox.warning(self, "错误", f"无法列出目录: {e}")
            return

        self._current_path = path
        self._path_input.setText(path)

        # 排序：目录在前，然后按名称
        dirs = []
        files = []
        for attr in entries:
            name = attr.filename
            if name.startswith("."):
                continue
            is_dir = stat.S_ISDIR(attr.st_mode) if attr.st_mode else False
            if is_dir:
                dirs.append(attr)
            else:
                files.append(attr)

        dirs.sort(key=lambda a: a.filename.lower())
        files.sort(key=lambda a: a.filename.lower())

        for attr in dirs:
            item = QTreeWidgetItem([attr.filename, "", "目录"])
            item.setData(0, Qt.ItemDataRole.UserRole, "dir")
            self._tree.addTopLevelItem(item)

        for attr in files:
            size_str = self._format_size(attr.st_size or 0)
            item = QTreeWidgetItem([attr.filename, size_str, "文件"])
            item.setData(0, Qt.ItemDataRole.UserRole, "file")
            self._tree.addTopLevelItem(item)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        kind = item.data(0, Qt.ItemDataRole.UserRole)
        name = item.text(0)
        if kind == "dir":
            new_path = self._current_path.rstrip("/") + "/" + name
            self._navigate(new_path)
        else:
            # 双击文件直接选中确认
            self._selected = self._current_path.rstrip("/") + "/" + name
            self.accept()

    def _go_up(self) -> None:
        parent = self._current_path.rsplit("/", 1)[0]
        if not parent:
            parent = "/"
        self._navigate(parent)

    def _on_path_entered(self) -> None:
        path = self._path_input.text().strip()
        if path:
            self._navigate(path)

    def _on_accept(self) -> None:
        current = self._tree.currentItem()
        if current:
            name = current.text(0)
            self._selected = self._current_path.rstrip("/") + "/" + name
        else:
            # 没有选中项时，选择当前目录
            self._selected = self._current_path
        self.accept()

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
