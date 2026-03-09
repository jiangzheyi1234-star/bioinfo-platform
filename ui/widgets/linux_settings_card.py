from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    BUTTON_PRIMARY,
    CARD_TITLE,
    COLOR_TEXT_HINT,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
    BUTTON_LINK,
)

logger = logging.getLogger(__name__)

# 工具环境检测状态图标
_STATUS_PENDING = "⏳"
_STATUS_OK = "✅"
_STATUS_FAIL = "❌"


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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

            # ── 第一步：获取远程 conda 环境列表 ──────────────────
            # 优先用绝对路径，避免 PATH 未初始化的问题。
            # 关键：必须等 channel.recv_exit_status() 确保命令执行完毕，
            # exec_command 本身是异步的，直接 .read() 可能拿到空内容。
            conda_envs: list[str] = []
            candidates = [
                # 按实际服务器路径优先排列
                "/home/zyserver/anaconda3/bin/conda env list --json",
                "/home/zyserver/miniconda3/bin/conda env list --json",
                # 通用绝对路径
                "~/anaconda3/bin/conda env list --json",
                "~/miniconda3/bin/conda env list --json",
                "/opt/anaconda3/bin/conda env list --json",
                "/opt/miniconda3/bin/conda env list --json",
                # fallback：依赖 PATH
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

            # ── 第二步：构建环境名集合（取路径末尾段）──────────────
            # conda env list --json 返回完整路径，如：
            #   /home/zyserver/anaconda3/envs/fastp_env
            # 末尾段即环境名：fastp_env
            env_names_set: set[str] = set()
            for path in conda_envs:
                name = path.rstrip("/").split("/")[-1]
                env_names_set.add(name)

            logger.debug("已知环境名: %s", env_names_set)

            # ── 第三步：逐个比对工具的 conda_env 字段 ───────────────
            for tool in self.tools:
                tool_id = tool.get("id", "")
                conda_env = tool.get("conda_env", "")

                if not conda_env:
                    # 工具无 conda_env 声明 → 直接系统调用，视为就绪
                    self.tool_checked.emit(tool_id, "(系统路径)", True)
                    continue

                ok = conda_env in env_names_set
                logger.debug("tool=%s conda_env=%s ok=%s", tool_id, conda_env, ok)
                self.tool_checked.emit(tool_id, conda_env, ok)

            self.finished.emit(conda_envs)

        except Exception as e:
            logger.exception("EnvBatchCheckWorker 出错")
            self.error.emit(str(e))


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片（重构版）。

    功能：
      - 配置远程 Linux 项目的根路径。
      - 批量检测 16 个插件工具的 conda 环境是否就绪。
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

        # plugin_registry 可由外部注入，也可后续通过 set_plugin_registry() 设置
        self._plugin_registry = plugin_registry

        # 每行工具状态: {tool_id: QLabel}
        self._status_labels: dict[str, QLabel] = {}
        # 工具列表: [{"id": ..., "name": ..., "conda_env": ...}]
        self._tools: list[dict] = []

        # 自动折叠定时器
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
            # 清除检测状态
            for lbl in self._status_labels.values():
                lbl.setText(_STATUS_PENDING)

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

        # ── 工具环境检测区 ──
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
        scroll.setFixedHeight(220)
        scroll.setStyleSheet("background: transparent;")

        self._tool_list_widget = QWidget()
        self._tool_list_widget.setStyleSheet("background: transparent;")
        self._tool_list_layout = QVBoxLayout(self._tool_list_widget)
        self._tool_list_layout.setContentsMargins(0, 4, 0, 4)
        self._tool_list_layout.setSpacing(6)

        # 占位提示（插件列表加载前显示）
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
        """从 PluginRegistry 动态读取工具列表，重建状态行。"""
        self._tools = []
        self._status_labels = {}

        # 清空布局（保留 stretch）
        while self._tool_list_layout.count():
            item = self._tool_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._plugin_registry:
            self._placeholder_label = QLabel("（插件注册表未就绪）")
            self._placeholder_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            self._tool_list_layout.addWidget(self._placeholder_label)
            self._tool_list_layout.addStretch()
            return

        try:
            for tool_id in self._plugin_registry.list_all_ids():
                desc = self._plugin_registry.get_descriptor(tool_id)
                tool_name = desc.get("name", tool_id)
                conda_env = desc.get("conda_env", "")
                self._tools.append({
                    "id": tool_id,
                    "name": tool_name,
                    "conda_env": conda_env,
                })
        except Exception:
            logger.exception("读取插件列表失败")

        if not self._tools:
            lbl = QLabel("（未发现任何插件）")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")
            self._tool_list_layout.addWidget(lbl)
            self._tool_list_layout.addStretch()
            return

        # 建立每行：[工具名]  [环境名]  [状态图标]
        header_row = QHBoxLayout()
        h_tool = QLabel("工具")
        h_env = QLabel("Conda 环境")
        h_status = QLabel("状态")
        for lbl in (h_tool, h_env, h_status):
            lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 11px; font-weight: bold;")
        h_tool.setFixedWidth(120)
        h_env.setFixedWidth(180)
        h_status.setFixedWidth(28)
        header_row.addWidget(h_tool)
        header_row.addWidget(h_env)
        header_row.addStretch()
        header_row.addWidget(h_status)
        self._tool_list_layout.addLayout(header_row)

        # 分割线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLOR_TEXT_HINT};")
        self._tool_list_layout.addWidget(sep)

        for tool in self._tools:
            tid = tool["id"]
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)

            name_lbl = QLabel(tool["name"])
            name_lbl.setFixedWidth(120)
            name_lbl.setStyleSheet("font-size: 13px;")

            env_name = tool["conda_env"] or "(系统路径)"
            env_lbl = QLabel(env_name)
            env_lbl.setFixedWidth(180)
            env_lbl.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px;")

            status_lbl = QLabel(_STATUS_PENDING)
            status_lbl.setFixedWidth(28)
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            row_layout.addWidget(name_lbl)
            row_layout.addWidget(env_lbl)
            row_layout.addStretch()
            row_layout.addWidget(status_lbl)
            self._tool_list_layout.addLayout(row_layout)
            self._status_labels[tid] = status_lbl

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

        # 重置状态图标
        for lbl in self._status_labels.values():
            lbl.setText(_STATUS_PENDING)

        self._checking = True
        self.check_btn.setEnabled(False)
        self.status_label.setText("正在检测工具环境...")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        # 清理旧线程
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
        """单个工具检测完成，更新状态图标。"""
        lbl = self._status_labels.get(tool_id)
        if lbl:
            lbl.setText(_STATUS_OK if ok else _STATUS_FAIL)

    def _on_batch_finished(self, conda_envs: list) -> None:
        """全部检测完成。"""
        self._checking = False
        self.check_btn.setEnabled(True)

        ok_count = sum(
            1 for lbl in self._status_labels.values()
            if lbl.text() == _STATUS_OK
        )
        total = len(self._status_labels)
        self.status_label.setText(f"检测完成：{ok_count}/{total} 个环境就绪")
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

        # 延迟折叠
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
