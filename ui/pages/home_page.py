# ui/pages/home_page.py
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QStackedWidget, QLabel, 
    QPushButton, QButtonGroup, QFileDialog, QLineEdit, QProgressBar, QFrame,
    QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt
from ui.page_base import BasePage
from ui.widgets import styles
from core.db_builder_worker import DbBuilderWorker
from core.accession_worker import AccessionWorker  # 确保引入了新写的 Worker
from config import DEFAULT_CONFIG
import os

class HomePage(BasePage):
    def __init__(self, main_window=None):
        super().__init__(" 项目首页")
        if hasattr(self, "label"): self.label.hide()
        self.main_window = main_window
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_APP};")
        self._build_ui()

    def get_ssh_client(self):
        return self.main_window.get_ssh_service() if self.main_window else None

    def _set_settings_lock(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        if self.main_window and hasattr(self.main_window, "set_settings_locked"):
            self.main_window.set_settings_locked(locked, reason)

    def _build_ui(self):
        """完全参考 DetectionPage 的结构"""
        self.layout.setContentsMargins(30, 15, 30, 20)
        self.layout.setSpacing(10)

        # 1. 顶部标题
        header = QLabel("项目概览与自定义管理")
        header.setStyleSheet(styles.PAGE_HEADER_TITLE)
        self.layout.addWidget(header)

        # 2. 上方选项卡导航 (模仿 DetectionPage)
        self.nav_bar = QWidget()
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(5)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.btn_db = self._create_nav_button("️ 自定义建库", 1)
        self.btn_info = self._create_nav_button(" 系统概览", 2)

        nav_layout.addWidget(self.btn_db)
        nav_layout.addWidget(self.btn_info)
        nav_layout.addStretch()
        self.layout.addWidget(self.nav_bar)

        # 细分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {styles.COLOR_BORDER}; max-height: 1px; border:none;")
        self.layout.addWidget(line)

        # 3. 下方内容区
        self.content_stack = QStackedWidget()
        self._setup_stack_pages()
        self.layout.addWidget(self.content_stack)

        self.btn_db.setChecked(True)
        self.content_stack.setCurrentIndex(1)

    def _create_nav_button(self, text, index):
        """直接复用 DetectionPage 的按钮逻辑和样式"""
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(styles.BUTTON_NAV_TOGGLE)
        btn.clicked.connect(lambda: self.content_stack.setCurrentIndex(index))
        self.nav_group.addButton(btn)
        return btn

    def _setup_stack_pages(self):
        # 页面 0: 欢迎
        self.welcome_page = QLabel("请选择功能模块...")
        self.welcome_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 页面 1: 建库工作流 (参考 DetectionPage 的三步走)
        self.db_page = QWidget()
        self._init_db_workflow_ui()

        # 页面 2: 概览
        self.info_page = QLabel("系统运行状态监测（待实现）")
        self.info_label_style = f"color: {styles.COLOR_TEXT_HINT}; font-size: 14px;"
        self.info_page.setStyleSheet(self.info_label_style)
        self.info_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.content_stack.addWidget(self.welcome_page)
        self.content_stack.addWidget(self.db_page)
        self.content_stack.addWidget(self.info_page)

    def _init_db_workflow_ui(self):
        """步骤 1 UI构建：单列检索模式 (参考BlastSettingsCard样式)"""
        layout = QVBoxLayout(self.db_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(15)

        # === 步骤 1: Excel元数据获取卡片 (参考BlastSettingsCard样式) ===
        self.card_excel = QFrame()
        self.card_excel.setObjectName("ExcelMetadataCard")
        self.card_excel.setStyleSheet(styles.CARD_FRAME("ExcelMetadataCard"))
        card_layout = QVBoxLayout(self.card_excel)
        card_layout.setContentsMargins(20, 15, 20, 15)
        card_layout.setSpacing(12)

        # 标题
        title = QLabel("步骤 1：批量获取基因组信息 (NCBI Datasets)")
        title.setStyleSheet(styles.CARD_TITLE)
        card_layout.addWidget(title)

        # 文件导入行
        file_row = QHBoxLayout()
        self.excel_path_edit = QLineEdit()
        self.excel_path_edit.setPlaceholderText("请选择 .xlsx 文件...")
        self.excel_path_edit.setReadOnly(True)
        self.excel_path_edit.setStyleSheet(styles.INPUT_LINEEDIT)
        
        self.btn_import_excel = QPushButton("导入 Excel")
        self.btn_import_excel.setStyleSheet(styles.BUTTON_SECONDARY)
        self.btn_import_excel.setFixedWidth(100)
        self.btn_import_excel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_excel.clicked.connect(self._on_import_excel)
        
        file_row.addWidget(self.excel_path_edit)
        file_row.addWidget(self.btn_import_excel)
        card_layout.addLayout(file_row)

        # 检索配置行
        config_row = QHBoxLayout()
        config_row.addWidget(QLabel("选择列:", styleSheet=styles.FORM_LABEL))
        self.combo_target_col = QComboBox()
        self.combo_target_col.setPlaceholderText("请选择一列进行检索...")
        self.combo_target_col.setStyleSheet("""
            QComboBox {
                padding: 6px 10px;
                border: 1px solid %s;
                border-radius: 4px;
                background: white;
                min-width: 150px;
            }
            QComboBox:disabled {
                background: %s;
                color: %s;
            }
        """ % (styles.COLOR_BORDER_INPUT, styles.COLOR_BG_INPUT_DISABLED, styles.COLOR_TEXT_DISABLED))
        self.combo_target_col.setEnabled(False)  # 导入后启用
        
        config_row.addWidget(self.combo_target_col)
        config_row.addStretch()
        card_layout.addLayout(config_row)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self.btn_start_search = QPushButton("开始检索并回填")
        self.btn_start_search.setStyleSheet(styles.BUTTON_PRIMARY)
        self.btn_start_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_search.clicked.connect(self._on_start_accession_search)
        self.btn_start_search.setEnabled(False)
        
        self.search_status = QLabel("等待导入 Excel...")
        self.search_status.setStyleSheet(styles.LABEL_HINT)
        
        btn_row.addWidget(self.btn_start_search)
        btn_row.addWidget(self.search_status)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        # 进度条
        self.pbar_search = QProgressBar()
        self.pbar_search.setFixedHeight(6)
        self.pbar_search.setTextVisible(False)
        self.pbar_search.hide()
        self.pbar_search.setStyleSheet(f"""
            QProgressBar {{
                border-radius: 3px;
                background: {styles.COLOR_BG_PROGRESS_BAR};
            }}
            QProgressBar::chunk {{
                background: {styles.COLOR_BG_PROGRESS_CHUNK};
            }}
        """)
        card_layout.addWidget(self.pbar_search)
        
        layout.addWidget(self.card_excel)
        
        # --- 保留原有的 Step 2 和 Step 3 占位 ---
        self.card_download = QFrame() # 这里建议保留你原本的 Step2 UI 代码，或暂时用空 Frame 占位
        layout.addWidget(self.card_download)
        self.card_build = QFrame()    # 这里建议保留你原本的 Step3 UI 代码
        layout.addWidget(self.card_build)
    def _on_import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 文件", "", "Excel Files (*.xlsx *.xls)")
        if not path: return
        
        self.excel_path_edit.setText(path)
        try:
            import pandas as pd
            
            # 一次性读取所有sheets
            all_sheets = pd.read_excel(path, sheet_name=None)
            
            # 从第一个sheet获取列名（通常所有sheet结构相似）
            first_sheet_name = list(all_sheets.keys())[0]
            df = all_sheets[first_sheet_name]
            cols = df.columns.tolist()
            
            # 填充列下拉框
            self.combo_target_col.clear()
            self.combo_target_col.addItems(cols)
            
            # 智能预选 (根据表头关键词猜一下)
            for col in cols:
                lower = col.lower()
                if "name" in lower or "organism" in lower or "英文" in lower:
                    self.combo_target_col.setCurrentText(col)
                elif "tax" in lower or "id" in lower:
                    self.combo_target_col.setCurrentText(col)
            
            # 启用控件
            self.combo_target_col.setEnabled(True)
            self.btn_start_search.setEnabled(True)
            # 明确显示当前导入的文件名和工作表数量
            filename = os.path.basename(path)
            self.search_status.setText(f"Excel '{filename}' 已加载，共 {len(all_sheets)} 个工作表，请确认检索依据列")
            
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"无法读取 Excel 文件: {str(e)}")

    def _on_start_accession_search(self):
        excel_path = self.excel_path_edit.text()
        target_col = self.combo_target_col.currentText()
        
        if not target_col:
            QMessageBox.warning(self, "警告", "请选择要检索的列")
            return
        
        # 检查是否已有正在运行的worker，如果有则先安全停止
        if hasattr(self, 'acc_worker') and self.acc_worker and self.acc_worker.isRunning():
            # 请求中断并等待完成
            self.acc_worker.requestInterruption()
            self.acc_worker.quit()
            self.acc_worker.wait()  # 等待线程真正退出
        
        # UI 锁定
        self.btn_start_search.setEnabled(False)
        self.btn_import_excel.setEnabled(False)
        self.combo_target_col.setEnabled(False)
        self.pbar_search.show()
        
        # 从JSON配置文件中获取NCBI API Key
        import json
        import os
        from config import DEFAULT_CONFIG  # 作为备用
        
        config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        config_path = os.path.join(config_dir, "config.json")
        
        api_key = ""
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                api_key = config_data.get("ncbi_api_key", "")
            else:
                # 如果配置文件不存在，使用默认配置
                api_key = DEFAULT_CONFIG.get("ncbi_api_key", "")
        except Exception as e:
            # 如果读取配置文件出错，使用默认配置
            api_key = DEFAULT_CONFIG.get("ncbi_api_key", "")
            print(f"读取配置文件出错: {e}")
        
        # 调试输出
        print(f"使用API Key: {'***' if api_key else 'None'} (长度: {len(api_key)})")

        # 创建新的线程对象
        self.acc_worker = AccessionWorker(excel_path, target_col, api_key)
        
        # 连接信号槽
        self.acc_worker.progress_val.connect(self.pbar_search.setValue)
        self.acc_worker.progress_msg.connect(self.search_status.setText)
        self.acc_worker.finished.connect(self._on_search_finished)
        # 确保在线程结束后正确清理资源 - 使用独立的方法避免引用问题
        self.acc_worker.finished.connect(self._cleanup_worker)
        
        # 启动线程
        self.acc_worker.start()

    def _on_search_finished(self, success, msg, out_path):
        # UI 解锁
        self.btn_start_search.setEnabled(True)
        self.btn_import_excel.setEnabled(True)
        self.combo_target_col.setEnabled(True)
        self.pbar_search.hide()
        
        if success:
            # 不弹窗，只在状态栏显示信息
            # 重新计算新文件的工作表数量
            try:
                import pandas as pd
                all_sheets = pd.read_excel(out_path, sheet_name=None)
                sheet_count = len(all_sheets)
                self.search_status.setText(f"✅ 检索完成，结果已保存至: {out_path} (共 {sheet_count} 个工作表)")
            except:
                # 如果无法读取新文件，就只显示基本完成信息
                self.search_status.setText(f"✅ 检索完成，结果已保存至: {out_path}")
            # 自动将新生成的文件路径填回输入框
            self.excel_path_edit.setText(out_path)
        else:
            # 错误情况下仍弹窗提醒
            QMessageBox.critical(self, "错误", msg)
            self.search_status.setText(msg)
        
        # 更新下拉框状态
        self._update_combo_state()
        
        # 确保worker对象被正确清理（如果还未被自动清理的话）
        # 不再在这里手动处理，因为已通过信号槽连接了_cleanup_worker

    def _cleanup_worker(self):
        """独立的worker清理方法，避免在finished信号中直接访问self.acc_worker"""
        if hasattr(self, 'acc_worker') and self.acc_worker:
            # 标记worker为None以避免其他地方尝试访问
            self.acc_worker = None

    def _update_combo_state(self):
        """更新下拉框状态"""
        # 仅在导入Excel后启用目标列选择
        excel_loaded = self.combo_target_col.count() > 0
        self.combo_target_col.setEnabled(excel_loaded)

    def _on_browse_fasta(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择参考序列", "", "FASTA (*.fasta *.fa *.fna)")
        if path: self.file_path_edit.setText(path)

    def _on_start_build(self):
        """参考 DetectionPage 的锁死和异步逻辑"""
        local_fasta = self.file_path_edit.text()
        db_name = self.db_name_input.text().strip()

        if not local_fasta or not db_name:
            self.status_label.setText(" 请先完成步骤 1 和 步骤 2")
            return

        if not self.get_ssh_client():
            self.status_label.setText(" 错误：SSH 未连接")
            return

        # 锁死前两步交互
        self.card_file.setEnabled(False)
        self.card_name.setEnabled(False)
        self.run_btn.setEnabled(False)
        
        self.worker = DbBuilderWorker(self.get_ssh_client, local_fasta, db_name)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self._on_build_finished)
        self._set_settings_lock(True)
        
        self.pbar.show()
        self.pbar.setRange(0, 0)
        self.worker.start()

    def _on_build_finished(self, success, msg, db_path):
        # 恢复交互
        self.card_file.setEnabled(True)
        self.card_name.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.pbar.hide()
        self._set_settings_lock(False)
        
        self.status_label.setText(msg)
        if success:
            self.result_info.setText(f" 远程路径：{db_path}\n您现在可以在‘资源确认’步骤中使用此路径。")
        else:
            self.result_info.setText(f" 详情：{msg}")
