from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    BUTTON_PRIMARY,
    CARD_TITLE,
    COLOR_TEXT_HINT,
    COLOR_BG_PAGE,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
    BUTTON_LINK,
    SCROLL_BAR_ELEGANT,
)

logger = logging.getLogger(__name__)

# 工具环境检测状态图标
_STATUS_PENDING = "..."
_STATUS_OK = "OK"
_STATUS_FAIL = "×"


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ── 批量环境检测 Worker ─────────────────────────────────────────────


class EnvBatchCheckWorker(QObject):
    """SSH 批量检测工具 conda 环境是否就绪。

    检测策略：运行 `conda env list --json`，解析环境路径列表，
    逐个比对工具 descriptor 中的 `conda_env` 字段。

    Signals:
        tool_checked(tool_id, env_name, ok): 单个工具检测完成
        finished(conda_envs_list): 全部完成，返回已有环境路径列表
        error(message): 检测出错
    """

    tool_checked = pyqtSignal(str, str, bool)   # tool_id, env_name, ok
    finished = pyqtSignal(list)                  # conda_envs_list
    error = pyqtSignal(str)                      # error_message

    def __init__(self, client, tools: list[dict]):
        """
        Args:
            client: paramiko SSHClient
            tools: [{"id": ..., "conda_env": ...}, ...]
        """
        super().__init__()
        self.client = client
        self.tools = tools

    @pyqtSlot()
    def run(self):
        try:
            import json as _json

            # ── 获取远程 conda 环境列表 ──────────────────────────────
            conda_envs: list[str] = []
            candidates = [
                "/home/zyserver/anaconda3/bin/conda env list --json",
                "/home/zyserver/miniconda3/bin/conda env list --json",
                "~/anaconda3/bin/conda env list --json",
                "~/miniconda3/bin/conda env list --json",
                "/opt/anaconda3/bin/conda env list --json",
                "/opt/miniconda3/bin/conda env list --json",
                "conda env list --json",
            ]

            for cmd in candidates:
                try:
                    _, stdout, stderr = self.client.exec_command(cmd, timeout=30)
                    # ★ 等待命令真正执行完毕
                    exit_code = stdout.channel.recv_exit_status()
                    output = stdout.read().decode("utf-8", errors="ignore").strip()
                    err_out = stderr.read().decode("utf-8", errors="ignore").strip()

                    logger.debug("conda cmd=%r exit=%d out_len=%d err=%s",
                                 cmd, exit_code, len(output), err_out[:80])

                    if exit_code != 0 or not output:
                        continue

                    json_start = output.find("{")
                    if json_start < 0:
                        continue

                    data = _json.loads(output[json_start:])
                    conda_envs = data.get("envs", [])
                    logger.info("conda env list 成功，共 %d 个环境（命令: %s）",
                                len(conda_envs), cmd)
                    break

                except _json.JSONDecodeError as e:
                    logger.warning("JSON 解析失败 cmd=%r: %s", cmd, e)
                    continue
                except Exception as e:
                    logger.debug("cmd=%r 失败: %s", cmd, e)
                    continue

            if not conda_envs:
                logger.warning("所有候选命令均未取到 conda 环境列表")

            # ── 构建环境名集合（取路径末尾段）───────────────────────
            env_names_set: set[str] = set()
            for path in conda_envs:
                name = path.rstrip("/").split("/")[-1]
                env_names_set.add(name)

            logger.debug("已知环境名: %s", env_names_set)

            # ── 逐个比对工具的 conda_env 字段 ──────────────────────
            for tool in self.tools:
                tool_id = tool.get("id", "")
                conda_env = tool.get("conda_env", "")

                if not conda_env:
                    self.tool_checked.emit(tool_id, "(系统路径)", True)
                    continue

                ok = conda_env in env_names_set
                logger.debug("tool=%s conda_env=%s ok=%s", tool_id, conda_env, ok)
                self.tool_checked.emit(tool_id, conda_env, ok)

            self.finished.emit(conda_envs)

        except Exception as e:
            logger.exception("EnvBatchCheckWorker 出错")
            self.error.emit(str(e))


# ── 环境安装 Worker ────────────────────────────────────────────────


class EnvInstallWorker(QObject):
    """SSH 执行 conda create 安装工具环境，实时流式输出。

    Signals:
        output_line(str): 每读到一行输出
        finished(bool): 安装完成，True=成功
        error(str): 异常
    """

    output_line = pyqtSignal(str)   # 每行输出
    finished = pyqtSignal(bool)     # True=成功
    error = pyqtSignal(str)

    def __init__(self, client, install_cmd: str):
        super().__init__()
        self.client = client
        self.install_cmd = install_cmd

    @pyqtSlot()
    def run(self):
        try:
            logger.info("开始安装环境: %s", self.install_cmd)
            self.output_line.emit(f"$ {self.install_cmd}\n")

            _, stdout, stderr = self.client.exec_command(
                self.install_cmd, timeout=900  # 最长 15 分钟
            )

            # 流式读取 stdout（conda 主要输出在 stdout）
            for line in iter(stdout.readline, ""):
                if not line:
                    break
                self.output_line.emit(line)

            # 等待命令完全结束，取退出码
            exit_code = stdout.channel.recv_exit_status()

            # 读取 stderr（conda 有时把进度写到 stderr）
            err_text = stderr.read().decode("utf-8", errors="ignore").strip()
            if err_text:
                for line in err_text.splitlines():
                    self.output_line.emit(f"[stderr] {line}\n")

            success = exit_code == 0
            logger.info("安装完成 exit_code=%d success=%s", exit_code, success)
            self.finished.emit(success)

        except Exception as e:
            logger.exception("EnvInstallWorker 出错")
            self.error.emit(str(e))


# ── 环境安装对话框 ─────────────────────────────────────────────────


class EnvInstallDialog(QDialog):
    """安装工具 conda 环境的确认 + 进度对话框。

    用法::
        dlg = EnvInstallDialog(client, tool_info, parent=self)
        dlg.install_succeeded.connect(callback)
        dlg.exec()
    """

    install_succeeded = pyqtSignal(str)  # tool_id

    def __init__(self, client, tool_info: dict, parent=None):
        """
        Args:
            client: paramiko SSHClient
            tool_info: {"id", "name", "conda_env", "install_cmd", "databases"}
        """
        super().__init__(parent)
        self.client = client
        self.tool_info = tool_info
        self._installing = False
        self._install_thread: Optional[QThread] = None
        self._install_worker: Optional[EnvInstallWorker] = None

        self.setWindowTitle("安装工具环境")
        self.setMinimumWidth(580)
        self.setMinimumHeight(440)
        self.setStyleSheet(f"background-color: {COLOR_BG_PAGE};")

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        tool_name = self.tool_info.get("name", self.tool_info.get("id", ""))
        conda_env = self.tool_info.get("conda_env", "")
        install_cmd = self.tool_info.get("install_cmd", "")
        databases = self.tool_info.get("databases", [])

        # ── 工具信息区 ──
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "background: #f0f4ff; border: 1px solid #c5d0e8; border-radius: 6px;"
        )
        info_layout = QFormLayout(info_frame)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setVerticalSpacing(8)

        def _info_lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 13px; color: #333;")
            return lbl

        info_layout.addRow("工具:", _info_lbl(f"{tool_name}  ({conda_env})"))
        info_layout.addRow("命令:", _info_lbl(install_cmd or "（未配置）"))

        if databases:
            db_ids = "、".join(d.get("id", "") for d in databases)
            db_hint = QLabel(
                f"⚠ 该工具需要数据库：{db_ids}\n"
                "安装环境完成后，请在「数据库路径配置」卡片中填写数据库路径。"
            )
            db_hint.setWordWrap(True)
            db_hint.setStyleSheet(
                "color: #8a6300; background: #fff8e1;"
                "border: 1px solid #ffe082; border-radius: 4px;"
                "padding: 8px; font-size: 12px;"
            )
            info_layout.addRow("", db_hint)
        else:
            info_layout.addRow("数据库:", _info_lbl("无（不需要额外数据库）"))

        layout.addWidget(info_frame)

        # ── 安装输出区 ──
        output_title = QLabel("安装输出：")
        output_title.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(output_title)

        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setStyleSheet(
            "background: #1e1e1e; color: #d4d4d4;"
            "font-family: Consolas, 'Courier New', monospace;"
            "font-size: 12px; border-radius: 4px; border: none;"
        )
        self.output_edit.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)
        self.output_edit.setMinimumHeight(180)
        layout.addWidget(self.output_edit)

        # ── 状态行 ──
        self.status_lbl = QLabel('点击「开始安装」执行 conda create 命令。安装可能需要 5-30 分钟。')
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self.install_btn = QPushButton("开始安装")
        self.install_btn.setFixedWidth(100)
        self.install_btn.setStyleSheet(BUTTON_PRIMARY)
        self.install_btn.clicked.connect(self._on_start_install)

        if not install_cmd:
            self.install_btn.setEnabled(False)
            self.status_lbl.setText("该工具未配置 install_cmd，无法自动安装。")

        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)

    def _on_start_install(self):
        if self._installing:
            return
        install_cmd = self.tool_info.get("install_cmd", "")
        if not install_cmd:
            return

        self._installing = True
        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_lbl.setText("安装中，请勿关闭窗口……（conda 安装可能需要 5-30 分钟）")
        self.status_lbl.setStyleSheet("color: #1565c0; font-size: 12px;")
        self.output_edit.clear()

        self._install_thread = QThread()
        self._install_worker = EnvInstallWorker(self.client, install_cmd)
        self._install_worker.moveToThread(self._install_thread)

        self._install_thread.started.connect(self._install_worker.run)
        self._install_worker.output_line.connect(self._append_output)
        self._install_worker.finished.connect(self._on_install_finished)
        self._install_worker.error.connect(self._on_install_error)
        self._install_worker.finished.connect(self._cleanup_install)

        self._install_thread.start()

    def _append_output(self, line: str):
        self.output_edit.insertPlainText(line)
        sb = self.output_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_install_finished(self, success: bool):
        self._installing = False
        self.cancel_btn.setEnabled(True)

        if success:
            self.output_edit.insertPlainText("\n✅ 安装成功！\n")
            self.status_lbl.setText("✅ 环境安装成功！")
            self.status_lbl.setStyleSheet(
                "color: #2e7d32; font-size: 13px; font-weight: bold;"
            )
            self.install_btn.setText("关闭")
            self.install_btn.setEnabled(True)
            # 断开旧信号，改为关闭对话框
            try:
                self.install_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self.install_btn.clicked.connect(self.accept)
            self.install_succeeded.emit(self.tool_info.get("id", ""))
        else:
            self.output_edit.insertPlainText("\n❌ 安装失败，请查看上方输出。\n")
            self.status_lbl.setText("❌ 安装失败，请检查网络或手动安装。")
            self.status_lbl.setStyleSheet("color: #c62828; font-size: 12px;")
            self.install_btn.setText("重试")
            self.install_btn.setEnabled(True)
            try:
                self.install_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self.install_btn.clicked.connect(self._on_start_install)

    def _on_install_error(self, msg: str):
        self._installing = False
        self.cancel_btn.setEnabled(True)
        self.install_btn.setText("重试")
        self.install_btn.setEnabled(True)
        self.status_lbl.setText(f"安装出错: {msg[:80]}")
        self.status_lbl.setStyleSheet(STATUS_ERROR)
        try:
            self.install_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.install_btn.clicked.connect(self._on_start_install)

    def _cleanup_install(self):
        for attr in ("_install_thread", "_install_worker"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            if attr == "_install_thread" and obj.isRunning():
                obj.quit()
                obj.wait(3000)
            obj.deleteLater()
            try:
                delattr(self, attr)
            except AttributeError:
                pass

    def _on_cancel(self):
        if self._installing:
            return  # 安装中不允许关闭
        self.reject()

    def closeEvent(self, event):
        if self._installing:
            event.ignore()  # 安装中禁止关闭
        else:
            self._cleanup_install()
            super().closeEvent(event)


# ── LinuxSettingsCard ─────────────────────────────────────────────


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片（含工具环境检测+安装）。

    功能：
      - 配置远程 Linux 项目的根路径。
      - 批量检测 16 个插件工具的 conda 环境是否就绪（一键检测）。
      - 对 ❌ 工具提供"安装"按钮，点击后弹出 EnvInstallDialog 执行 conda create。
      - 安装成功后自动重新检测；需要数据库的工具给出提示。
      - 支持 plugin_registry 外部注入（PluginRegistry 动态读取工具列表）。

    get_values() 返回字段（保持向后兼容）:
      linux_project_path, max_concurrent, poll_interval,
      conda_env_path(空), conda_env_name(空), is_locked
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None, plugin_registry=None):
        super().__init__(parent)
        self.setObjectName("LinuxSettingsCard")

        self.active_client = None
        self._is_locked = False
        self._checking = False
        self._in_edit_mode = False
        self._external_lock = False

        self._plugin_registry = plugin_registry

        # 每行工具状态标签: {tool_id: QLabel}
        self._status_labels: dict[str, QLabel] = {}
        # 每行安装按钮: {tool_id: QPushButton}
        self._install_btns: dict[str, QPushButton] = {}
        # 工具列表: [{"id", "name", "conda_env", "install_cmd", "databases"}]
        self._tools: list[dict] = []

        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold)

        self._build_ui()
        self._lock_inputs()

    # ── 公开 API ─────────────────────────────────────────

    def set_plugin_registry(self, plugin_registry) -> None:
        """外部注入 PluginRegistry，用于刷新工具列表。"""
        self._plugin_registry = plugin_registry
        self._refresh_tool_list()

    def set_active_client(self, client) -> None:
        """接收外部传入的 SSH 客户端实例。SSH 连接成功后自动触发一次环境检测。"""
        self.active_client = client
        connected = client is not None

        self.check_btn.setEnabled(connected and not self._is_locked and not self._external_lock)

        if connected:
            self.status_label.setText("SSH 已就绪，正在检测工具环境...")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            # SSH 连接成功后延迟 1s 自动触发检测（等 UI 渲染完毕）
            QTimer.singleShot(1000, self._on_batch_check)
        else:
            self.status_label.setText("等待 SSH 连接")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            for lbl in self._status_labels.values():
                lbl.setText(_STATUS_PENDING)
            for btn in self._install_btns.values():
                btn.setVisible(False)

    def get_values(self) -> dict:
        """供 SettingsPage 获取数据（向后兼容）。"""
        return {
            "linux_project_path": self.linux_project_path.text().strip(),
            "conda_env_path": "",       # 已移除，保留 key 兼容旧逻辑
            "conda_env_name": "",       # 已移除，保留 key 兼容旧逻辑
            "is_locked": self._is_locked,
            "max_concurrent": self.spin_concurrent.value(),
            "poll_interval": self.spin_poll.value(),
        }

    def set_values(
        self,
        project_path: str = "",
        conda_env: str = "",
        conda_env_name: str = "",
        max_concurrent: int = 3,
        poll_interval: int = 5,
    ) -> None:
        """供 SettingsPage 回填数据（签名向后兼容，conda_env 参数忽略）。"""
        self.linux_project_path.setText(project_path)
        self.spin_concurrent.setValue(max_concurrent)
        self.spin_poll.setValue(poll_interval)

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在 SSH 连接被占用时禁用编辑。"""
        if self._external_lock == locked:
            return
        self._external_lock = locked
        self._refresh_interaction_state()

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("LinuxSettingsCard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 头部（可点击折叠/展开）──
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.title_label = QLabel("Linux 端运行环境配置")
        self.title_label.setStyleSheet(CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setMinimumWidth(60)
        self.modify_btn.setStyleSheet(BUTTON_LINK)
        self.modify_btn.clicked.connect(self._enable_editing)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_btn)
        header_layout.addWidget(self.arrow_label)
        main_layout.addWidget(self.header_area)

        # ── 可折叠容器 ──
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(20, 0, 20, 20)
        c_layout.setSpacing(15)

        # ── 基础配置表单 ──
        form = QFormLayout()
        form.setVerticalSpacing(12)

        self.linux_project_path = QLineEdit()
        self.linux_project_path.setStyleSheet(INPUT_LINEEDIT)
        self.linux_project_path.setPlaceholderText("例如: /h2ometa/projects")

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 8)
        self.spin_concurrent.setValue(3)
        self.spin_concurrent.setSuffix(" 个任务")

        self.spin_poll = QSpinBox()
        self.spin_poll.setRange(1, 60)
        self.spin_poll.setValue(5)
        self.spin_poll.setSuffix(" 秒")

        form.addRow("项目根路径", self.linux_project_path)
        form.addRow("最大并发任务数", self.spin_concurrent)
        form.addRow("任务轮询间隔", self.spin_poll)
        c_layout.addLayout(form)

        # ── 工具环境检测区头部 ──
        env_header = QHBoxLayout()
        env_title = QLabel("工具环境检测状态：")
        env_title.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 13px;")
        self.check_btn = QPushButton("一键检测")
        self.check_btn.setMinimumWidth(90)
        self.check_btn.setStyleSheet(BUTTON_PRIMARY)
        self.check_btn.setEnabled(False)
        self.check_btn.clicked.connect(self._on_batch_check)

        env_header.addWidget(env_title)
        env_header.addStretch()
        env_header.addWidget(self.check_btn)
        c_layout.addLayout(env_header)

        # 工具环境状态滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(260)
        scroll.setStyleSheet("background: transparent;")
        scroll.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)

        self._tool_list_widget = QWidget()
        self._tool_list_widget.setStyleSheet("background: transparent;")
        self._tool_list_layout = QVBoxLayout(self._tool_list_widget)
        self._tool_list_layout.setContentsMargins(0, 4, 0, 4)
        self._tool_list_layout.setSpacing(6)

        self._placeholder_label = QLabel("（插件注册表未就绪，启动后自动填充）")
        self._placeholder_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
        self._tool_list_layout.addWidget(self._placeholder_label)
        self._tool_list_layout.addStretch()

        scroll.setWidget(self._tool_list_widget)
        c_layout.addWidget(scroll)

        # ── 状态行 + 保存按钮 ──
        row = QHBoxLayout()
        self.lock_btn = QPushButton("确认并保存")
        self.lock_btn.setMinimumWidth(110)
        self.lock_btn.setStyleSheet(BUTTON_PRIMARY)
        self.lock_btn.clicked.connect(self._on_save_and_lock)

        self.status_label = QLabel("等待 SSH 连接")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        row.addWidget(self.lock_btn)
        row.addWidget(self.status_label)
        row.addStretch()
        c_layout.addLayout(row)

        main_layout.addWidget(self.container)

    # ── 工具列表管理 ─────────────────────────────────────

    def _refresh_tool_list(self) -> None:
        """从 PluginRegistry 动态读取工具列表，重建状态行（含安装按钮）。"""
        self._tools = []
        self._status_labels = {}
        self._install_btns = {}

        # 清空布局
        while self._tool_list_layout.count():
            item = self._tool_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._plugin_registry:
            lbl = QLabel("（插件注册表未就绪）")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            self._tool_list_layout.addWidget(lbl)
            self._tool_list_layout.addStretch()
            return

        try:
            for tool_id in self._plugin_registry.list_all_ids():
                desc = self._plugin_registry.get_descriptor(tool_id)
                self._tools.append({
                    "id": tool_id,
                    "name": desc.get("name", tool_id),
                    "conda_env": desc.get("conda_env", ""),
                    "install_cmd": desc.get("install_cmd", ""),
                    "databases": desc.get("databases", []),
                })
        except Exception:
            logger.exception("读取插件列表失败")

        if not self._tools:
            lbl = QLabel("（未发现任何插件）")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            self._tool_list_layout.addWidget(lbl)
            self._tool_list_layout.addStretch()
            return

        # 表头行：[工具名 | 环境名 | 状态 | 操作]
        header_row = QHBoxLayout()
        for text, width in [("工具", 110), ("Conda 环境", 160), ("", 8), ("状态", 28), ("操作", 60)]:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {COLOR_TEXT_HINT}; font-size: 11px; font-weight: bold;"
            )
            if width:
                lbl.setFixedWidth(width)
            header_row.addWidget(lbl)
        self._tool_list_layout.addLayout(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLOR_TEXT_HINT};")
        self._tool_list_layout.addWidget(sep)

        for tool in self._tools:
            tid = tool["id"]
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)

            name_lbl = QLabel(tool["name"])
            name_lbl.setFixedWidth(110)
            name_lbl.setStyleSheet("font-size: 13px;")

            env_name = tool["conda_env"] or "(系统路径)"
            env_lbl = QLabel(env_name)
            env_lbl.setFixedWidth(160)
            env_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")

            status_lbl = QLabel(_STATUS_PENDING)
            status_lbl.setFixedWidth(28)
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # "安装"按钮：初始隐藏，检测到 ❌ 后显示
            install_btn = QPushButton("安装")
            install_btn.setFixedWidth(56)
            install_btn.setStyleSheet(
                "QPushButton {"
                "  font-size: 11px; padding: 2px 4px;"
                "  background: #1565c0; color: white;"
                "  border-radius: 4px; border: none;"
                "}"
                "QPushButton:hover { background: #1976d2; }"
                "QPushButton:disabled { background: #9e9e9e; }"
            )
            install_btn.setVisible(False)
            # 用默认参数捕获 tool 快照，避免 lambda 闭包陷阱
            _tool_snapshot = dict(tool)
            install_btn.clicked.connect(
                lambda checked=False, t=_tool_snapshot: self._on_install_click(t)
            )

            row_layout.addWidget(name_lbl)
            row_layout.addWidget(env_lbl)
            row_layout.addStretch()
            row_layout.addWidget(status_lbl)
            row_layout.addWidget(install_btn)
            self._tool_list_layout.addLayout(row_layout)

            self._status_labels[tid] = status_lbl
            self._install_btns[tid] = install_btn

        self._tool_list_layout.addStretch()

    # ── 批量检测 ─────────────────────────────────────────

    def _on_batch_check(self) -> None:
        """一键检测所有工具环境。"""
        if not self.active_client or self._checking or self._external_lock:
            return

        if not self._tools:
            self.status_label.setText("未发现工具，请检查插件目录")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        # 重置所有状态
        for lbl in self._status_labels.values():
            lbl.setText(_STATUS_PENDING)
        for btn in self._install_btns.values():
            btn.setVisible(False)

        self._checking = True
        self.check_btn.setEnabled(False)
        self.status_label.setText("正在检测工具环境...")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        self._cleanup_check_resources()

        self._check_thread = QThread()
        self._check_worker = EnvBatchCheckWorker(self.active_client, self._tools)
        self._check_worker.moveToThread(self._check_thread)

        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.tool_checked.connect(self._on_tool_checked)
        self._check_worker.finished.connect(self._on_batch_finished)
        self._check_worker.error.connect(self._on_batch_error)
        self._check_worker.finished.connect(self._cleanup_check_resources)

        self._check_thread.start()

    def _on_tool_checked(self, tool_id: str, env_name: str, ok: bool) -> None:
        """单个工具检测完成，更新状态图标和安装按钮可见性。"""
        lbl = self._status_labels.get(tool_id)
        if lbl:
            lbl.setText(_STATUS_OK if ok else _STATUS_FAIL)

        btn = self._install_btns.get(tool_id)
        if btn:
            # ❌ 显示安装按钮；✅ 隐藏
            btn.setVisible(not ok)
            # 检测进行中时禁用按钮（_on_batch_finished 再统一启用）
            btn.setEnabled(False)

    def _on_batch_finished(self, conda_envs: list) -> None:
        """全部检测完成。"""
        self._checking = False
        self.check_btn.setEnabled(True)

        # 统一启用所有可见的安装按钮
        for btn in self._install_btns.values():
            if btn.isVisible():
                btn.setEnabled(self.active_client is not None)

        ok_count = sum(
            1 for lbl in self._status_labels.values()
            if lbl.text() == _STATUS_OK
        )
        total = len(self._status_labels)
        fail_count = total - ok_count

        if fail_count > 0:
            self.status_label.setText(
                f"检测完成：{ok_count}/{total} 个环境就绪，{fail_count} 个需要安装"
            )
        else:
            self.status_label.setText(f"检测完成：{ok_count}/{total} 个环境全部就绪 ✅")

        if ok_count == total:
            self.status_label.setStyleSheet(STATUS_SUCCESS)
        elif ok_count == 0:
            self.status_label.setStyleSheet(STATUS_ERROR)
        else:
            self.status_label.setStyleSheet(STATUS_NEUTRAL)

    def _on_batch_error(self, msg: str) -> None:
        """检测出错。"""
        self._checking = False
        self.check_btn.setEnabled(True)
        self.status_label.setText(f"检测失败: {msg[:30]}")
        self.status_label.setStyleSheet(STATUS_ERROR)

    def _cleanup_check_resources(self) -> None:
        """清理检测线程资源。"""
        for attr in ("_check_thread", "_check_worker"):
            obj = getattr(self, attr, None)
            if obj is None:
                continue
            if attr == "_check_thread" and obj.isRunning():
                obj.quit()
                obj.wait(5000)
            obj.deleteLater()
            try:
                delattr(self, attr)
            except AttributeError:
                pass

    # ── 安装 ─────────────────────────────────────────────

    def _on_install_click(self, tool: dict) -> None:
        """点击"安装"按钮，弹出安装对话框。"""
        if not self.active_client:
            self.status_label.setText("SSH 未连接，无法安装")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        dlg = EnvInstallDialog(self.active_client, tool, parent=self)
        dlg.install_succeeded.connect(self._on_install_succeeded)
        dlg.exec()

    def _on_install_succeeded(self, tool_id: str) -> None:
        """某工具安装成功后：提示数据库（如需要），然后重新检测。"""
        tool = next((t for t in self._tools if t["id"] == tool_id), None)

        if tool and tool.get("databases"):
            from PyQt6.QtWidgets import QMessageBox
            db_ids = "\n".join(f"  • {d.get('id', '')}" for d in tool["databases"])
            QMessageBox.information(
                self,
                "请配置数据库路径",
                f"工具【{tool.get('name', tool_id)}】环境安装成功！\n\n"
                f"该工具运行需要以下数据库：\n{db_ids}\n\n"
                f"请在下方「数据库路径配置」卡片中填写对应路径。",
            )

        # 重新检测所有工具
        QTimer.singleShot(300, self._on_batch_check)

    # ── 保存/锁定 ─────────────────────────────────────────

    def _on_save_and_lock(self) -> None:
        """保存配置并切换锁定状态。"""
        if self._is_locked:
            # 解锁
            self._is_locked = False
            self.linux_project_path.setEnabled(True)
            self.spin_concurrent.setEnabled(True)
            self.spin_poll.setEnabled(True)
            self.check_btn.setEnabled(self.active_client is not None)
            self.lock_btn.setText("确认并保存")
            self.status_label.setText("配置已解锁，可修改")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            return

        project_path = self.linux_project_path.text().strip()
        if not project_path:
            self.status_label.setText("请填写项目根路径")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        self._is_locked = True
        self._lock_inputs()
        self.lock_btn.setText("修改配置")
        self.status_label.setText("配置已保存")
        self.status_label.setStyleSheet(STATUS_SUCCESS)
        self.request_save.emit()

        self._auto_fold_timer.start(1500)

    # ── 折叠/展开 ─────────────────────────────────────────

    def _toggle_container(self):
        if self._checking or self._external_lock:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

    def _auto_fold(self):
        if not self._in_edit_mode and self.container.isVisible():
            self.container.hide()
            self.arrow_label.setText("▼")

    def _enable_editing(self):
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")

        self.linux_project_path.setEnabled(True)
        self.spin_concurrent.setEnabled(True)
        self.spin_poll.setEnabled(True)
        if self.active_client:
            self.check_btn.setEnabled(True)
        self.lock_btn.show()
        self.lock_btn.setEnabled(True)

        self.status_label.setText("请修改配置并保存")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)
        self._in_edit_mode = True

    def _lock_inputs(self):
        self.linux_project_path.setEnabled(False)
        self.spin_concurrent.setEnabled(False)
        self.spin_poll.setEnabled(False)
        self.lock_btn.setText("修改配置")
        self._in_edit_mode = False

    def _refresh_interaction_state(self) -> None:
        if self._external_lock:
            for w in [
                self.linux_project_path, self.modify_btn, self.lock_btn,
                self.check_btn, self.spin_concurrent, self.spin_poll,
            ]:
                w.setEnabled(False)
            for btn in self._install_btns.values():
                btn.setEnabled(False)
            return

        if self._checking:
            return

        if self._in_edit_mode:
            self.linux_project_path.setEnabled(True)
            self.spin_concurrent.setEnabled(True)
            self.spin_poll.setEnabled(True)
            self.lock_btn.setEnabled(True)
            self.modify_btn.setEnabled(True)
            self.check_btn.setEnabled(self.active_client is not None)
        else:
            self.linux_project_path.setEnabled(False)
            self.spin_concurrent.setEnabled(False)
            self.spin_poll.setEnabled(False)
            self.modify_btn.setEnabled(True)
            self.check_btn.setEnabled(self.active_client is not None and not self._is_locked)

        for btn in self._install_btns.values():
            if btn.isVisible():
                btn.setEnabled(self.active_client is not None)
