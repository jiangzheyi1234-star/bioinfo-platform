from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QWidget, QStackedWidget, QLabel,
    QPushButton, QButtonGroup, QComboBox, QLineEdit, QTableWidgetItem, QFileDialog,
    QMessageBox
)

from ui.page_base import BasePage
from ui.widgets import styles, BlastResourceCard, BlastSampleCard, BlastRunCard, TaskHistoryCard
from core.blast_worker import BlastWorker
from core.task_recovery_worker import TaskRecoveryWorker, SingleTaskMonitorWorker
from config import DEFAULT_CONFIG
import os


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
        self._build_ui()
        # 初始化默认路径
        self.run_card.path_input.setText(DEFAULT_CONFIG.get('local_output_dir', ''))

    def get_ssh_client(self):
        """获取SSH客户端，通过主窗口获取"""
        if self.main_window:
            return self.main_window.get_ssh_service()
        return None

    def _set_settings_lock(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        if self.main_window and hasattr(self.main_window, "set_settings_locked"):
            self.main_window.set_settings_locked(locked, reason)

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
        """初始化任务历史页面"""
        layout = QVBoxLayout(self.history_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)
        
        self.history_card = TaskHistoryCard()
        self.history_card.resume_task.connect(self._on_resume_task)
        self.history_card.view_result.connect(self._on_view_result)
        self.history_card.refresh_requested.connect(self._on_refresh_tasks)
        layout.addWidget(self.history_card)

    def _on_resume_task(self, job_id: str):
        """继续监控某个任务"""
        client = self.get_ssh_client()
        if not client:
            QMessageBox.warning(self, "提示", "请先在设置页连接服务器")
            return
        
        self.monitor_worker = SingleTaskMonitorWorker(
            client_provider=self.get_ssh_client,
            job_id=job_id
        )
        self.monitor_worker.progress.connect(lambda msg: self.history_card.hint_label.setText(msg))
        self.monitor_worker.finished.connect(self._on_monitor_finished)
        self.history_card.refresh_btn.setEnabled(False)
        self.monitor_worker.start()

    def _on_monitor_finished(self, success, msg, local_path):
        """监控任务完成"""
        self.history_card.refresh_btn.setEnabled(True)
        self.history_card.refresh_list()
        
        if success:
            QMessageBox.information(self, "任务完成", msg)
            if local_path:
                self._on_view_result(local_path)
        else:
            self.history_card.hint_label.setText(msg)
        
        if hasattr(self, 'monitor_worker') and self.monitor_worker:
            self.monitor_worker.deleteLater()
            self.monitor_worker = None

    def _on_view_result(self, local_path: str):
        """查看结果文件"""
        if os.path.exists(local_path):
            # 加载结果到 BLAST 页面
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

    def _on_refresh_tasks(self):
        """刷新任务状态（从服务器检查）"""
        client = self.get_ssh_client()
        if not client:
            self.history_card.refresh_list()  # 只刷新本地列表
            return
        
        self.recovery_worker = TaskRecoveryWorker(client_provider=self.get_ssh_client)
        self.recovery_worker.progress.connect(lambda msg: self.history_card.hint_label.setText(msg))
        self.recovery_worker.task_updated.connect(self._on_task_updated)
        self.recovery_worker.all_checked.connect(self._on_all_tasks_checked)
        self.history_card.refresh_btn.setEnabled(False)
        self.recovery_worker.start()

    def _on_task_updated(self, job_id, status, msg, local_path):
        """单个任务状态更新"""
        self.history_card.update_task_status(job_id, status)

    def _on_all_tasks_checked(self, total, done, failed):
        """所有任务检查完成"""
        self.history_card.refresh_btn.setEnabled(True)
        self.history_card.refresh_list()
        if total > 0:
            self.history_card.hint_label.setText(f"✅ 检查完成: {total} 个任务, {done} 个已完成, {failed} 个失败")
        
        if hasattr(self, 'recovery_worker') and self.recovery_worker:
            self.recovery_worker.deleteLater()
            self.recovery_worker = None

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
        client = self.get_ssh_client()
        if not client:
            self.run_card.status_msg.setText(" 请先在设置页连接服务器")
            return

        # --- 【关键改进】锁死步骤一和步骤二按钮/交互 ---
        self.resource_card.setEnabled(False)
        self.sample_card.setEnabled(False)
        
        # 获取配置中的工具路径 (来自设置页保存的结果)
        blast_bin = DEFAULT_CONFIG.get('blast_bin', '/usr/bin/blastn')
        
        self.worker = BlastWorker(
            client_provider=self.get_ssh_client,
            local_fasta=self.sample_card.get_file_path(),
            db_path=self.resource_card.get_db_path(),
            task=self.resource_card.get_task(),
            blast_bin=blast_bin,
            local_out_dir=self.run_card.path_input.text()  # 传递用户选择的目录
        )

        self.worker.progress.connect(self.run_card.status_msg.setText)
        self.worker.finished.connect(self._handle_result)
        self._set_settings_lock(True)
        
        self.run_card.run_btn.setEnabled(False)
        self.run_card.browse_btn.setEnabled(False)  # 运行时锁定目录选择
        self.run_card.pbar.show()
        self.run_card.pbar.setRange(0, 0) # 忙碌滚动
        self.worker.start()

    def _handle_result(self, success, msg, local_path):
        """处理任务结束：解析数据并开启分页展示"""
        # --- 【关键改进】恢复步骤一和步骤二交互 ---
        self.resource_card.setEnabled(True)
        self.sample_card.setEnabled(True)
        self._set_settings_lock(False)

        self.run_card.show_loading(False)
        self.run_card.status_msg.setText(msg)

        # 重新启用按钮
        self.run_card.run_btn.setEnabled(True)
        self.run_card.browse_btn.setEnabled(True)
        self.run_card.pbar.hide()

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

        # 清理worker对象，避免内存泄漏
        if hasattr(self, 'worker') and self.worker:
            self.worker.deleteLater()
            self.worker = None

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
