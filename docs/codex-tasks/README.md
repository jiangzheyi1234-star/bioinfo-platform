# 数据库管理系统 — Codex 任务清单

## 项目背景
为 H2OMeta 宏基因组桌面分析平台构建完整的参考数据库生命周期管理：声明、配置、状态检测、半自动安装（含真实进度条）、完整性校验。全部通过 SSH 远端操作。

详细设计文档见：`../.claude/plans/nifty-singing-flask.md`

## 执行顺序与依赖

```
Task 1 ─────┐
             ├──→ Task 3 ──→ Task 4 ──→ Task 5
Task 2 ─────┘                              │
                                           ↓
                              Task 6 (settings + tool_bridge)
                                           │
                                           ↓
                                       Task 7 (cleanup)
```

| 顺序 | 文件 | 任务 | 依赖 |
|------|------|------|------|
| 1 | `task-01-databases-yaml.md` | databases.yaml 路径相对化 + 分类 | 无 |
| 2 | `task-02-config-migration.md` | config.py 数据库配置结构升级 | 无 |
| 3 | `task-03-database-service.md` | 新建 core/data/database_service.py | Task 1, 2 |
| 4 | `task-04-ui-components.md` | 新建 UI 组件（卡片、对话框、Worker） | Task 3 |
| 5 | `task-05-database-page.md` | 新建数据库页面 + 侧边栏集成 | Task 3, 4 |
| 6 | `task-06-integration.md` | settings_page 适配 + tool_bridge 路径解析 | Task 2, 3 |
| 7 | `task-07-cleanup.md` | 清理 tool.yaml 硬编码 + 更新 __init__.py | Task 4, 5 |

## 可并行的任务
- Task 1 和 Task 2 可以并行
- Task 4 和 Task 6 可以并行（都只依赖 Task 3）

## 关键约束（每个任务都需遵守）
- Core 层（core/）：只允许 PyQt6.QtCore，禁止 QtWidgets/QtGui
- UI 页面 ≤ 400 行，复杂卡片 ≤ 500 行
- SQL/SSH/数据解析放 core/，UI 只做渲染+信号绑定
- 新建 widget 必须更新 __init__.py
- 禁止硬编码服务器信息
- 响应式布局，禁止硬编码固定宽度

## 验证命令
```bash
# 全量测试
QT_QPA_PLATFORM=offscreen pytest -p no:cacheprovider tests -q

# UI 冒烟测试
QT_QPA_PLATFORM=offscreen pytest tests/test_ui_smoke.py -v

# YAML 语法检查
python -c "import yaml; yaml.safe_load(open('plugins/databases.yaml'))"
```
