from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    INPUT_COMBOBOX,
    BUTTON_PRIMARY,
    CARD_TITLE,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
    BUTTON_LINK,
)


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class EnvFetchWorker(QObject):
    finished = pyqtSignal(bool, list, str)  # 成功标志, 环境列表, 错误信息

    def __init__(self, client):
        super().__init__()
        self.client = client

    @pyqtSlot()
    def run(self):
        try:
            # 记录开始
            logging.info("开始获取远程 conda 环境列表")
            
            # 尝试多个可能的 conda 路径
            commands = [
                "conda env list --json",
                "source ~/.bashrc && conda env list --json",
                "/opt/anaconda3/bin/conda env list --json",
                "~/anaconda3/bin/conda env list --json",
                "~/miniconda3/bin/conda env list --json"
            ]

            output = ""
            error = ""
            
            for cmd in commands:
                logging.debug(f"尝试命令: {cmd}")
                try:
                    stdin, stdout, stderr = self.client.exec_command(cmd, timeout=10)
                    output = stdout.read().decode('utf-8', errors='ignore').strip()
                    error = stderr.read().decode('utf-8', errors='ignore').strip()
                    
                    logging.debug(f"输出长度: {len(output)}, 错误长度: {len(error)}")
                    
                    if output:
                        # 查找 JSON 起始位置，忽略可能的 shell 输出
                        json_start = output.find('{')
                        if json_start >= 0:
                            output = output[json_start:]
                            
                            data = json.loads(output)
                            envs = data.get('envs', [])
                            
                            logging.info(f"成功解析，找到 {len(envs)} 个环境")
                            self.finished.emit(True, envs, "")
                            return
                
                except json.JSONDecodeError as je:
                    logging.warning(f"JSON 解析失败，尝试下一个命令: {je}")
                    continue
                except Exception as e:
                    logging.debug(f"命令 '{cmd}' 执行失败: {e}")
                    continue
            
            # 如果所有命令都失败
            if not output and error:
                logging.error(f"所有命令都失败，最终错误: {error}")
                self.finished.emit(False, [], error)
            else:
                # 成功执行但没有环境
                logging.info("命令执行成功但未找到任何环境")
                self.finished.emit(True, [], "")  # 成功但无环境

        except Exception as e:
            logging.error(f"获取环境列表时发生异常: {str(e)}")
            self.finished.emit(False, [], str(e))


class LinuxSettingsCard(QFrame):
    """Linux 项目与运行环境配置卡片。
    
    功能：
      - 配置远程 Linux 项目的根路径。
      - 自动拉取并选择远程 Conda 环境。
      - 生成并同步 config.env 配置文件到服务器。
    """

    request_save = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LinuxSettingsCard")
        
        self.active_client = None  # 存储由外部（如 SettingsPage）传入的 SSHClient
        self._is_locked = False
        self._fetching = False  # 添加标志来跟踪是否正在获取环境
        self._in_edit_mode = False  # 添加编辑模式标志
        self._external_lock = False  # 添加外部锁定标志

        # 自动折叠定时器
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold)

        self._build_ui()
        self._lock_inputs()  # 默认锁定状态

    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("LinuxSettingsCard"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 头部区域 (可点击折叠/展开)
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.title_label = QLabel("Linux 端运行环境配置")
        self.title_label.setStyleSheet(CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setFixedWidth(60)
        self.modify_btn.setStyleSheet(BUTTON_LINK)
        self.modify_btn.clicked.connect(self._enable_editing)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_btn)
        header_layout.addWidget(self.arrow_label)
        main_layout.addWidget(self.header_area)

        # 容器布局
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(20, 0, 20, 20)

        # 表单布局
        form = QFormLayout()
        form.setVerticalSpacing(15)

        # 1. Linux 项目根路径
        self.linux_project_path = QLineEdit()
        self.linux_project_path.setStyleSheet(INPUT_LINEEDIT)
        self.linux_project_path.setPlaceholderText("例如: /home/zyserver/bioinfo-platform")

        # 2. Conda 环境下拉框
        self.conda_combo = QComboBox()
        self.conda_combo.setPlaceholderText("请先连接服务器并获取列表...")
        self.conda_combo.setEnabled(False)
        # 使用 styles.py 中定义的 INPUT_COMBOBOX 样式
        self.conda_combo.setStyleSheet(INPUT_COMBOBOX)

        form.addRow("项目根路径", self.linux_project_path)
        form.addRow("Conda 环境", self.conda_combo)
        c_layout.addLayout(form)

        # 按钮与状态行
        row = QHBoxLayout()
        self.fetch_btn = QPushButton("获取远程环境")
        self.fetch_btn.setFixedWidth(110)
        self.fetch_btn.setStyleSheet(BUTTON_PRIMARY)
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.clicked.connect(self._on_fetch_envs)

        self.lock_btn = QPushButton("确认并锁定")
        self.lock_btn.setFixedWidth(110)
        self.lock_btn.setStyleSheet(BUTTON_PRIMARY)
        self.lock_btn.clicked.connect(self._on_save_and_lock)

        self.status_label = QLabel("等待 SSH 连接")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        row.addWidget(self.fetch_btn)
        row.addWidget(self.lock_btn)
        row.addWidget(self.status_label)
        row.addStretch()
        c_layout.addLayout(row)

        main_layout.addWidget(self.container)

    def set_active_client(self, client) -> None:
        """接收外部传入的 SSH 客户端实例。"""
        self.active_client = client
        connected = client is not None
        
        self.fetch_btn.setEnabled(connected and not self._is_locked)
        self.lock_btn.setEnabled(connected)
        
        if connected:
            self.status_label.setText("SSH 已就绪")
            self.status_label.setStyleSheet(STATUS_SUCCESS)
        else:
            self.status_label.setText("等待 SSH 连接")
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            self.conda_combo.clear()
            self.conda_combo.setEnabled(False)

    def _on_fetch_envs(self) -> None:
        """执行远程命令获取 Conda 环境列表。"""
        if not self.active_client or self._fetching or self._external_lock:
            return

        # 首先更新UI状态
        self.status_label.setText("正在同步环境 (后台运行)...")
        self.fetch_btn.setEnabled(False)
        self._fetching = True

        # 确保之前的线程已经完全清理
        if hasattr(self, '_thread') and self._thread:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(3000)  # 等待最多3秒
            self._thread.deleteLater()
        
        if hasattr(self, '_worker') and self._worker:
            self._worker.deleteLater()

        # 创建新线程和worker
        self._thread = QThread()
        self._worker = EnvFetchWorker(self.active_client)
        self._worker.moveToThread(self._thread)

        # 信号绑定 - 在启动前连接
        self._thread.started.connect(self._worker.run)
        
        # 断开之前的信号连接（如果存在），然后连接新的信号
        try:
            self._worker.finished.disconnect()
        except:
            pass  # 如果没有连接的信号，则忽略异常
        
        self._worker.finished.connect(self._on_fetch_finished)
        self._worker.finished.connect(self._cleanup_fetch_resources)

        # 启动线程
        self._thread.start()

    def _cleanup_fetch_resources(self):
        """独立的资源清理方法"""
        # 从主线程中清理资源
        if hasattr(self, '_thread') and self._thread:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(5000)  # 等待最多5秒
            self._thread.deleteLater()
            try:
                delattr(self, '_thread')
            except AttributeError:
                pass  # 如果属性已被删除，则忽略
            
        if hasattr(self, '_worker') and self._worker:
            self._worker.deleteLater()
            try:
                delattr(self, '_worker')
            except AttributeError:
                pass  # 如果属性已被删除，则忽略

    def _on_fetch_finished(self, success, envs, error_msg):
        """线程结束后的回调"""
        # 确保在主线程中执行，避免竞态条件
        if hasattr(self, '_fetching') and self._fetching:
            self._fetching = False
            self.fetch_btn.setEnabled(True)

        if success:
            self.conda_combo.clear()
            for path in envs:
                name = path.split('/')[-1] if '/' in path else path
                self.conda_combo.addItem(name, path)
            self.conda_combo.setEnabled(True)
            self.status_label.setText(f"成功获取 {len(envs)} 个环境")
            self.status_label.setStyleSheet(STATUS_SUCCESS)
        else:
            self.status_label.setText(f"获取失败: {error_msg[:20]}...")
            self.status_label.setStyleSheet(STATUS_ERROR)

    def _on_save_and_lock(self) -> None:
        """生成远程 config.env 并切换锁定状态。"""
        if self._is_locked:
            # 解锁逻辑
            self._is_locked = False
            self.linux_project_path.setEnabled(True)
            self.conda_combo.setEnabled(True)
            self.fetch_btn.setEnabled(True)
            self.lock_btn.setText("确认并锁定")
            self.status_label.setText("配置已解锁")
            return

        # 锁定逻辑
        project_path = self.linux_project_path.text().strip()
        env_path = self.conda_combo.currentData()

        if not project_path or not env_path:
            self.status_label.setText("请填写路径并选择环境")
            self.status_label.setStyleSheet(STATUS_ERROR)
            return

        try:
            # 远程写入配置
            config_content = f"CONDA_ENV_PATH={env_path}\\nPROJECT_ROOT={project_path}"
            # 创建 config 目录并写入 config.env
            cmd = f"mkdir -p {project_path}/config && echo -e '{config_content}' > {project_path}/config/config.env"
            self.active_client.exec_command(cmd)

            self._is_locked = True
            self.linux_project_path.setEnabled(False)
            self.conda_combo.setEnabled(False)
            self.fetch_btn.setEnabled(False)
            self.lock_btn.setText("修改配置")
            
            self.status_label.setText("远程配置已生成并锁定")
            self.status_label.setStyleSheet(STATUS_SUCCESS)
            self.request_save.emit()
        except Exception as e:
            self.status_label.setText(f"保存失败: {str(e)}")
            self.status_label.setStyleSheet(STATUS_ERROR)

    def get_values(self) -> dict:
        """供 SettingsPage 获取数据。"""
        return {
            "linux_project_path": self.linux_project_path.text().strip(),
            "conda_env_path": self.conda_combo.currentData() or "",
            "is_locked": self._is_locked
        }

    def set_values(self, project_path: str = "", conda_env: str = "") -> None:
        """供 SettingsPage 回填数据。"""
        self.linux_project_path.setText(project_path)
        # Conda 环境由于涉及远程获取，通常在连接后由用户选择或自动匹配

    def _toggle_container(self):
        """折叠/展开"""
        if self._fetching or self._external_lock:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

    def _auto_fold(self):
        """自动折叠，仅在锁定且可见时触发"""
        if not self._in_edit_mode and self.container.isVisible():
            self.container.hide()
            self.arrow_label.setText("▼")

    def _enable_editing(self):
        """进入编辑模式：解锁输入框，修改按钮保持可见，显示保存按钮"""
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")

        self.linux_project_path.setEnabled(True)
        self.conda_combo.setEnabled(True)

        self.lock_btn.show()
        self.lock_btn.setEnabled(True)
        self.modify_btn.show()  # 修改按钮保持可见

        self.status_label.setText("请修改配置并保存")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)
        self._in_edit_mode = True

    def _lock_inputs(self):
        """锁定模式：禁用输入框，修改按钮保持可见"""
        self.linux_project_path.setEnabled(False)
        self.conda_combo.setEnabled(False)

        self.lock_btn.setText("修改配置")
        self.modify_btn.show()  # 修改按钮始终保持可见
        if self._is_locked:
            self.status_label.setText("配置已保存")
        else:
            self.status_label.setText("等待配置")
        self._in_edit_mode = False

    def set_external_lock(self, locked: bool) -> None:
        """外部锁定功能，用于在SSH连接被占用时禁用编辑"""
        if self._external_lock == locked:
            return
        self._external_lock = locked
        self._refresh_interaction_state()

    def _refresh_interaction_state(self) -> None:
        """刷新交互状态，处理外部锁定等情况"""
        if self._external_lock:
            for w in [self.linux_project_path, self.conda_combo, self.modify_btn, self.lock_btn]:
                w.setEnabled(False)
            return

        if self._fetching:
            return

        if self._in_edit_mode:
            self.linux_project_path.setEnabled(True)
            self.conda_combo.setEnabled(True)
            self.lock_btn.setEnabled(True)
            self.modify_btn.setEnabled(True)
        else:
            self.linux_project_path.setEnabled(False)
            self.conda_combo.setEnabled(False)
            self.modify_btn.setEnabled(True)
