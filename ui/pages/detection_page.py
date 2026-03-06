from __future__ import annotations

import logging
import os
import time
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QWidget, QStackedWidget, QLabel,
    QPushButton, QButtonGroup, QComboBox, QLineEdit, QTableWidgetItem, QFileDialog,
    QMessageBox
)

from ui.page_base import BasePage
from ui.widgets import styles, BlastResourceCard, BlastSampleCard, BlastRunCard, ExecutionHistoryCard
from config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class _BlastSubmitWorker(QThread):
    """后台提交 BLAST 任务（上传文件 + 提交到 ToolEngine）"""

    progress = pyqtSignal(str)
    submitted = pyqtSignal(str, str)  # execution_id, sample_id
    failed = pyqtSignal(str)  # error message

    def __init__(self, locator, fasta_path: str, db_path: str):
        super().__init__()
        self._locator = locator
        self._fasta_path = fasta_path
        self._db_path = db_path

    def run(self):
        try:
            ssh = self._locator.ssh_service
            pm = self._locator.project_manager
            registry = self._locator.data_registry
            engine = self._locator.tool_engine

            sample_name = f"blast_{int(time.time())}"
            sample_id = registry.add_sample(sample_name)

            self.progress.emit("正在上传序列文件...")
            from core.data_importer import DataImporter
            importer = DataImporter(ssh_service=ssh, registry=registry)
            data_id = importer.import_file(
                local_path=self._fasta_path,
                sample_id=sample_id,
                data_type="fasta",
                project_remote_base=pm.current_project.remote_base,
            )

            self.progress.emit("正在启动远程 BLAST 比对...")
            execution_id = engine.execute(
                tool_id="blastn",
                input_data_ids=[data_id],
                parameters={},
                sample_id=sample_id,
                triggered_by="manual",
                database_paths={"db": self._db_path},
            )

            self.submitted.emit(execution_id, sample_id)

        except Exception as e:
            logger.exception("BLAST 提交失败")
            self.failed.emit(str(e))


class DetectionPage(BasePage):
    """病原体检测页面：采用上下布局，上方功能导航区（选项卡式），下方内容展示区。"""

    def __init__(self, main_window=None):
        super().__init__("🧫 病原体检测")
        if hasattr(self, "label"):
            self.label.hide()

        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self.main_window = main_window
        self.all_data = [] # 缓存所有比对行数据
        self.current_page = 0
        self.page_size = 20
        self._current_execution_id: Optional[str] = None
        self._current_sample_id: Optional[str] = None
        self._submit_worker: Optional[_BlastSubmitWorker] = None
        self._build_ui()
        # 初始化默认路径
        self.run_card.path_input.setText(DEFAULT_CONFIG.get('local_output_dir', ''))
        # 连接 ServiceLocator 信号
        self._connect_locator_signals()

    def get_ssh_client(self):
        """获取SSH客户端，通过主窗口获取"""
        if self.main_window:
            return self.main_window.get_ssh_service()
        return None

    def _set_settings_lock(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        if self.main_window and hasattr(self.main_window, "set_settings_locked"):
            self.main_window.set_settings_locked(locked, reason)

    def _get_locator(self):
        """获取 ServiceLocator"""
        if self.main_window and hasattr(self.main_window, 'service_locator'):
            return self.main_window.service_locator
        return None

    def _connect_locator_signals(self) -> None:
        """连接 ServiceLocator 执行信号"""
        locator = self._get_locator()
        if locator is None:
            return
        locator.execution_completed.connect(self._on_execution_completed)
        locator.execution_failed.connect(self._on_execution_failed)

    def _build_ui(self):
        # 页面整体布局参数
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(10)

        # 顶部标题
        header = QLabel("病原体检测")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        self.layout.addWidget(header)

        # 上方：选项卡式功能切换区 (Top Navigation)
        self.nav_bar = QWidget()
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)  # 按钮间距紧凑

        # 使用 QButtonGroup 管理按钮的互斥高亮逻辑
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        # 创建功能按钮（无图标、压缩尺寸、带高亮逻辑）
        self.btn_blast = self._create_nav_button("🧬 BLASTN 比对", 1)
        self.btn_history = self._create_nav_button("📋 任务历史", 2)
        self.btn_other = self._create_nav_button("🔬 其他分析", 3)

        nav_layout.addWidget(self.btn_blast)
        nav_layout.addWidget(self.btn_history)
        nav_layout.addWidget(self.btn_other)
        nav_layout.addStretch()
        self.layout.addWidget(self.nav_bar)

        # 细分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {styles.COLOR_BORDER}; max-height: 1px; border:none;")
        self.layout.addWidget(line)

        # 下方：对应功能的操作页面 (Content Area)
        self.content_stack = QStackedWidget()
        self.layout.addWidget(self.content_stack)

        # 初始化各个功能页面
        self._setup_stack_pages()

        # 默认选中第一个功能
        self.btn_blast.setChecked(True)
        self.content_stack.setCurrentIndex(1)

    def _create_nav_button(self, text: str, index: int):
        """创建具备高亮和切换功能的精简按钮"""
        btn = QPushButton(text)
        btn.setCheckable(True)  # 开启可选状态
        btn.setAutoExclusive(True)  # 开启自动互斥（同组内只能选一个）
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 样式：未选中时浅蓝色调，选中时蓝色高亮
        btn.setStyleSheet(styles.BUTTON_NAV_TOGGLE)
        
        # 点击后直接切换堆栈窗口，无需返回键逻辑
        btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(index))
        self.nav_group.addButton(btn)
        return btn

    def _setup_stack_pages(self):
        """配置下方内容区的各个子页面"""
        # 页面 0: 占位/欢迎
        self.welcome_page = QLabel("请选择工具...")
        self.welcome_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_page.setStyleSheet(f"color: {styles.COLOR_TEXT_HINT}; font-size: 14px;")
        
        # 页面 1: BLAST 操作页
        self.blast_page = QWidget()
        self._init_blast_workflow_ui()
        
        # 页面 2: 任务历史页
        self.history_page = QWidget()
        self._init_history_page_ui()
        
        # 页面 3: 其他分析页
        self.other_page = QWidget()
        self._init_other_workflow_ui()

        self.content_stack.addWidget(self.welcome_page)  # Index 0
        self.content_stack.addWidget(self.blast_page)    # Index 1
        self.content_stack.addWidget(self.history_page)  # Index 2
        self.content_stack.addWidget(self.other_page)    # Index 3

    def _init_blast_workflow_ui(self):
        """优化的三步走布局"""
        layout = QVBoxLayout(self.blast_page)
        layout.setSpacing(15)

        # 1 & 2 步横向
        top_row = QHBoxLayout()
        self.resource_card = BlastResourceCard(self.get_ssh_client)
        self.sample_card = BlastSampleCard()
        top_row.addWidget(self.resource_card, 1)
        top_row.addWidget(self.sample_card, 1)
        layout.addLayout(top_row)

        # 3 步纵向
        self.run_card = BlastRunCard()
        layout.addWidget(self.run_card, 2)

        # 信号绑定
        self.resource_card.save_btn.clicked.connect(self._sync_status)
        self.sample_card.file_selected.connect(self._sync_status)
        self.run_card.run_btn.clicked.connect(self._on_start)
        self.run_card.browse_btn.clicked.connect(self._on_browse_output_dir)
        self.resource_card.ssh_usage_changed.connect(self._set_settings_lock)
        
        # 绑定分页按钮事件
        self.run_card.prev_btn.clicked.connect(lambda: self._change_page(-1))
        self.run_card.next_btn.clicked.connect(lambda: self._change_page(1))

    def _init_history_page_ui(self):
        """初始化执行历史页面（基于 SQLite）"""
        layout = QVBoxLayout(self.history_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        self.execution_history = ExecutionHistoryCard()
        layout.addWidget(self.execution_history)

        # 尝试设置数据库连接
        self._refresh_history_db()

    def _refresh_history_db(self) -> None:
        """更新执行历史的数据库连接"""
        if not hasattr(self, 'execution_history'):
            return
        locator = self._get_locator()
        if locator is None:
            return
        pm = locator.project_manager
        if pm and pm.current_project is not None:
            try:
                self.execution_history.set_db_connection(pm.db)
            except Exception:
                pass

    def _on_view_result(self, local_path: str):
        """查看结果文件 — 加载本地 TSV 到 BLAST 表格"""
        if os.path.exists(local_path):
            try:
                with open(local_path, 'r', encoding='utf-8') as f:
                    self.all_data = [line.strip().split('\t') for line in f if line.strip()]

                self.current_page = 0
                self._update_table_view()

                if self.all_data:
                    top = self.all_data[0]
                    interpretation = f"<b>自动解读：</b> 发现最佳匹配项 <u>{top[1]}</u>，一致性为 <b>{top[2]}%</b>，E-value 为 <b>{top[10]}</b>。"
                    self.run_card.interpret_label.setText(interpretation)
                    self.run_card.interpret_box.show()

                self.run_card.path_display.setText(f" 结果文件: {local_path}")
                self.run_card.path_display.show()

                # 切换到 BLAST 页面显示结果
                self.btn_blast.setChecked(True)
                self.content_stack.setCurrentIndex(1)

            except Exception as e:
                QMessageBox.warning(self, "错误", f"读取结果失败: {e}")
        else:
            QMessageBox.warning(self, "提示", f"结果文件不存在: {local_path}")

    def _sync_status(self):
        db = self.resource_card.get_db_path()
        file = self.sample_card.get_file_path()
        if db and file:
            self.run_card.run_btn.setEnabled(True)
            self.run_card.status_msg.setText(" 参数就绪，可以开始比对")
        else:
            self.run_card.run_btn.setEnabled(False)

    def _on_browse_output_dir(self):
        """弹出目录选择对话框"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.run_card.path_input.text())
        if dir_path:
            self.run_card.path_input.setText(dir_path)

    def _on_start(self):
        """启动 BLAST 比对（通过 ToolEngine）"""
        locator = self._get_locator()
        ssh = locator.ssh_service if locator else None

        if locator is None or ssh is None or not getattr(ssh, 'is_connected', False):
            self.run_card.status_msg.setText(" 请先在设置页连接服务器")
            return

        pm = locator.project_manager
        if pm.current_project is None:
            self.run_card.status_msg.setText(" 请先选择或创建项目")
            return

        if locator.data_registry is None or locator.tool_engine is None:
            self.run_card.status_msg.setText(" 请先打开项目")
            return

        # 锁定 UI
        self.resource_card.setEnabled(False)
        self.sample_card.setEnabled(False)
        self._set_settings_lock(True)
        self.run_card.run_btn.setEnabled(False)
        self.run_card.browse_btn.setEnabled(False)
        self.run_card.pbar.show()
        self.run_card.pbar.setRange(0, 0)

        # 在后台线程中执行上传 + 提交
        self._submit_worker = _BlastSubmitWorker(
            locator=locator,
            fasta_path=self.sample_card.get_file_path(),
            db_path=self.resource_card.get_db_path(),
        )
        self._submit_worker.progress.connect(self.run_card.status_msg.setText)
        self._submit_worker.submitted.connect(self._on_submit_succeeded)
        self._submit_worker.failed.connect(self._on_submit_failed)
        self._submit_worker.start()

    def _on_submit_succeeded(self, execution_id: str, sample_id: str) -> None:
        """BLAST 任务提交成功"""
        self._current_execution_id = execution_id
        self._current_sample_id = sample_id
        self.run_card.status_msg.setText(f"BLAST 任务已提交，正在执行... (ID: {execution_id})")
        # 清理 worker
        if self._submit_worker:
            self._submit_worker.deleteLater()
            self._submit_worker = None

    def _on_submit_failed(self, error: str) -> None:
        """BLAST 任务提交失败"""
        self._unlock_blast_ui()
        self.run_card.status_msg.setText(f"启动失败: {error}")
        # 清理 worker
        if self._submit_worker:
            self._submit_worker.deleteLater()
            self._submit_worker = None

    def _unlock_blast_ui(self) -> None:
        """解锁 BLAST 操作界面"""
        self.resource_card.setEnabled(True)
        self.sample_card.setEnabled(True)
        self._set_settings_lock(False)
        self.run_card.run_btn.setEnabled(True)
        self.run_card.browse_btn.setEnabled(True)
        self.run_card.pbar.hide()

    def _on_execution_completed(self, execution_id: str) -> None:
        """ToolEngine 执行完成回调 — 下载结果并展示"""
        if execution_id != self._current_execution_id:
            return

        try:
            locator = self._get_locator()
            if locator is None:
                return

            pm = locator.project_manager
            project = pm.current_project
            sample_id = self._current_sample_id
            output_dir = f"{project.remote_base}/intermediate/{sample_id}/blastn"
            remote_path = f"{output_dir}/{sample_id}.blastn.tsv"

            local_out_dir = self.run_card.path_input.text()
            os.makedirs(local_out_dir, exist_ok=True)
            local_path = os.path.join(local_out_dir, f"blast_res_{execution_id}.txt")

            self.run_card.status_msg.setText("远程任务完成，正在同步结果...")
            ssh = locator.ssh_service
            ssh.download(remote_path, local_path)

            self._handle_result(True, f"分析完成！\n执行ID: {execution_id}", local_path)
        except Exception as e:
            logger.exception("下载 BLAST 结果失败")
            self._handle_result(False, f"下载结果失败: {e}", "")

        # 刷新执行历史
        self._refresh_history_db()

    def _on_execution_failed(self, execution_id: str, error: str) -> None:
        """ToolEngine 执行失败回调"""
        if execution_id != self._current_execution_id:
            return
        self._handle_result(False, f"BLAST 执行失败: {error}", "")
        # 刷新执行历史
        self._refresh_history_db()

    def _handle_result(self, success, msg, local_path):
        """处理任务结束：解析数据并开启分页展示"""
        # 恢复 UI 交互
        self._unlock_blast_ui()

        self.run_card.show_loading(False)
        self.run_card.status_msg.setText(msg)

        if success and os.path.exists(local_path):
            # 显示保存路径和结果摘要
            result_summary = f" 结果已存至: {local_path}"
            try:
                with open(local_path, 'r', encoding='utf-8') as f:
                    self.all_data = [line.strip().split('\t') for line in f if line.strip()]

                # 显示结果摘要
                total_matches = len(self.all_data)
                if total_matches > 0:
                    result_summary += f" (共 {total_matches} 个匹配项)"

                # 自动解读 (Top Hit)
                interpretation = "未发现显著匹配项。"
                if self.all_data:
                    top = self.all_data[0]
                    interpretation = f"<b>自动解读：</b> 发现最佳匹配项 <u>{top[1]}</u>，一致性为 <b>{top[2]}%</b>，E-value 为 <b>{top[10]}</b>。建议查看详细比对表。"

                self.current_page = 0
                self._update_table_view()
                self.run_card.interpret_label.setText(interpretation)
                self.run_card.interpret_box.show()
                if len(self.all_data) > self.page_size:
                    self.run_card.page_nav.show()
            except Exception as e:
                self.run_card.status_msg.setText(f"解析失败: {e}")

            self.run_card.path_display.setText(result_summary)
            self.run_card.path_display.show()
        else:
            self.run_card.path_display.hide()

        # 清理 worker 对象，避免内存泄漏
        if self._submit_worker:
            self._submit_worker.deleteLater()
            self._submit_worker = None

    def _update_table_view(self):
        """根据当前页码更新表格内容"""
        self.run_card.result_table.setRowCount(0)
        start = self.current_page * self.page_size
        end = start + self.page_size
        items = self.all_data[start:end]
        self.run_card.result_table.setRowCount(len(items))
        for r, row in enumerate(items):
            for c, val in enumerate(row):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 2 and float(val) >= 95.0:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.run_card.result_table.setItem(r, c, item)
        
        total_pages = (len(self.all_data) + self.page_size - 1) // self.page_size
        self.run_card.page_label.setText(f"第 {self.current_page+1} / {total_pages} 页")
        self.run_card.prev_btn.setEnabled(self.current_page > 0)
        self.run_card.next_btn.setEnabled(end < len(self.all_data))

    def _change_page(self, delta):
        self.current_page += delta
        self._update_table_view()

    def _init_other_workflow_ui(self):
        """其他分析操作界面的具体布局逻辑入口"""
        layout = QVBoxLayout(self.other_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)

        # 其他分析详情内容占位符
        placeholder = QLabel("其他分析详情页（待实现）")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(styles.LABEL_MUTED)
        layout.addWidget(placeholder, 1)
