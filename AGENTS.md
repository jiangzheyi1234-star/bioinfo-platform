# Persistent Agent Notes
## ⚠️ 最高优先级
失败必须大声抛出，禁止 silent fallback，禁止保留已删除字段的任何兜底引用。

## Codex Git 基线（必须复用）

1. 在 Codex / 当前 PowerShell agent 环境内执行 Git 操作时，禁止直接调用 `git ...`、`git.exe ...`、`where.exe git` 等普通外部进程链路。
2. 必须统一走仓库脚本 `scripts/codex_git.ps1`，示例：`& .\scripts\codex_git.ps1 status`。
3. `scripts/codex_git.ps1` 负责 `.NET ProcessStartInfo` 启动、`safe.directory` 注入，以及 `WSL_UTF8=1`、`PYTHONUTF8=1` 环境设置；禁止在其他脚本里各自复制一套 Git 启动兜底。
4. 若 `scripts/codex_git.ps1` 执行失败，必须直接抛错并暴露 stderr/exit code，禁止 silent fallback 到其他未验证调用方式。

## SSH 访问基线（必须复用）

1. 优先通过 ServiceLocator 复用 `core/remote/ssh_service.py`。
2. 应用代码禁止直接调用 `paramiko_client.exec_command()`，
   必须走 `SSHService.run(cmd, timeout)` 串行队列。


## Thread Safety & SSH Anti-Crash（必须复用）

**硬禁令，违反必崩：**

1. Qt slot / 主线程禁止直接调用 SSH 命令或任何阻塞操作，
   耗时操作必须放 `QThread+Worker`。 
   **包含 SSH 调用的私有方法，必须只从 Worker 内部调用，
   不得从 `__init__`、`setup()`、事件回调直接调用。**
2. 所有 SSH 命令必须走 `SSHService.run(cmd)` 单队列，
   禁止自建 `paramiko.SSHClient()` 或绕过队列并发调用。
3. QThread worker 内禁止直接操作 Qt Widget，
   结果只能通过 `pyqtSignal` 回传主线程更新 UI。
4. conda 安装 / 工具安装 / 大文件下载必须用后台分离 `screen`（detached）启动，
   参考 `core/environment/env_installer.py`。
## 远程 Conda（无 sudo）基线（必须复用）

1. Conda 路径优先用 `H2O_CONDA_EXE`（`core/environment/h2o_env_paths.py`），
   回退 `~/.h2ometa/conda/bin/conda`。

2. 自动化脚本用 `conda run -p ...`，不依赖 `conda activate`。

3. `condarc` 模板禁止内联。写入 `~/.h2ometa/runtime/condarc` 的内容
   必须且只能来自 `core/environment/miniforge_condarc.py` 的 profile API
   （默认使用 `build_condarc_template()`），
   禁止在其他文件复制、内联或重写该字符串。

## 执行流水线基线（必须复用）

1. `ToolEngine.execute()` 保持主线程轻量，远端操作归 `execution_preparer.py`。
2. `JobDispatcher.start_waiting()` 必须在主线程调用。
3. SQLite 执行状态只能用现有枚举：`pending/running/completed/failed/retrying`，
   新增持久化状态需附带迁移计划。

## UI 规范（必须复用）

- 圆角浮层必须加 `NoDropShadowWindowHint`，参考 `ui/widgets/project_selector.py`。
- 图标必须用 `qtawesome`，禁止 Unicode emoji 充当产品图标。

## ExecPlans

- 复杂特性、跨文件重构、长时程任务默认使用 `ExecPlan` 工作流：
  `Plan -> Edit -> Run tools -> Observe -> Repair -> Update docs -> Repeat`。
- 执行前必须先读取对应计划文档；若仓库内已有任务专属计划文档，则该文档优先作为唯一执行事实来源。
- 任务完成后应清理过期的阶段性计划/记忆文档，避免残留失效入口。
- ExecPlan 必须保持自包含、活文档、可恢复；每完成一个 milestone 立即运行对应验证，失败先修复，不允许带着失败进入下一 milestone。

## Large File Refactor Preference（必须遵守）

- 当目标文件已超过 600 行时，新增功能、复杂分支、结果构建、远程调用、数据解析，优先提取到相邻新模块；原文件只保留门面、绑定点和薄包装。
- 禁止在超 600 行文件中继续直接堆积重逻辑，除非用户明确要求只做局部热修且拆分会显著放大风险。
## 用户偏好

- **提交**：必须给 commit hash + 标题 + 变更摘要 + 文件清单。
- **本地权限错误**：直接提权继续，不反复重试。
- **Windows UTF-8**：设 `WSL_UTF8=1` + `PYTHONUTF8=1`，参考 `scripts/codex_wsl_utf8_doctor.ps1`。

## 当前任务状态

最近完成：数据库管理系统 3 日计划（Task 1-7）✅ — 472 passed, 7 skipped
当前：等待下一任务

