# 更新日志

## 2024-03-07

### 多版本执行支持
- ✅ 输出目录包含 execution_id（`{tool_id}_{execution_id}`）
- ✅ 避免同一工具多次执行时覆盖输出
- ✅ 数据库 schema 扩展：`is_final_version`, `archived_at`
- ✅ 新增 `ExecutionCleaner` 模块：归档旧执行、标记最终版本
- ✅ 新增 `DataRegistry` 方法：`list_executions()`, `find_by_execution()`
- ✅ 数据库自动迁移（向后兼容）
- ✅ 44 个测试全部通过

**相关文件**：
- `core/tool_engine.py` - 输出目录生成逻辑
- `core/project_manager.py` - 数据库 schema 和迁移
- `core/data_registry.py` - 历史执行查询
- `core/execution_cleaner.py` - 执行清理器（新增）
- `tests/test_tool_engine_versioning.py` - 多版本测试（新增）
- `tests/test_execution_cleaner.py` - 清理器测试（新增）
- `tests/test_execution_record_fields.py` - 字段测试（新增）

### 项目管理增强
- ✅ 新增项目删除功能（已归档项目可永久删除）
- ✅ 新增 `project_deleted` 信号
- ✅ UI 显示删除按钮（仅已归档项目）
- ✅ 删除前二次确认
- ✅ 新增清理脚本 `scripts/clean_test_projects.py`

**相关文件**：
- `core/project_manager.py` - `delete_project()` 方法
- `ui/pages/project_page.py` - 删除按钮和处理逻辑
- `scripts/clean_test_projects.py` - 批量清理脚本（新增）

### Bug 修复
- ✅ 修复 `_row_to_record` 未处理新字段的问题
- ✅ 修复测试 fixture 参数不匹配
- ✅ 使用 try-except 处理向后兼容（sqlite3.Row 不支持 `.get()`）

### 文档更新
- ✅ 更新 CLAUDE.md：整理模块状态、测试覆盖、工具脚本
- ✅ 新增"输出目录结构"章节
- ✅ 更新"待完成功能"列表
- ✅ 删除临时实现文档 IMPLEMENTATION_SUMMARY.md

## 待完成（下一步）

### P1 优先级
- [ ] UI 层添加历史执行选择器（analysis_page / assembly_page）
- [ ] 结果文件下载逻辑（fastp JSON / kreport 从远端下载到本地）
- [ ] `ChartWidget` / `ResultsPanel` 注册到 `ui/widgets/__init__.py`
- [ ] `analysis_page._on_pipeline_completed()` 调用 `ResultsPanel.load_results()`

### P2 优先级
- [ ] 结果浏览页（`results_page.py`）
- [ ] 数据库管理页（`database_page.py`）
- [ ] AMR 分析页（`amr_page.py`）
- [ ] DAG 视图（`dag_widget.py`）
- [ ] `ResultSyncManager`（任务完成后自动同步结果文件）
