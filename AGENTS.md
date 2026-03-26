# 持久化代理说明

## SSH 访问基线（必须复用）

当任务需要远程检查 / 执行 / 下载时，始终按以下顺序：

1. 从 `%APPDATA%\\H2OMeta\\config.json` 读取 SSH 配置。
2. 优先通过 ServiceLocator 复用现有项目服务（`core/remote/ssh_service.py`）。
3. 应用代码中禁止直接调用 `paramiko_client.exec_command()`；必须通过 `SSHService.run(cmd, timeout)` 串行执行。
4. 若必须使用直连脚本（仅限一次性诊断场景），使用 Paramiko 且满足：
   - `host/port/user/password`（当 `use_key=true` 时使用 `key_file`）
   - 超时 10s
   - `AutoAddPolicy` 仅用于当前内部环境
5. 远程命令中涉及路径时，必须使用 `shlex.quote(...)` 包裹。
6. 执行/下载前，必须确认连接可用（`is_connected`）。
7. 工作流状态检查按以下优先级读取：
   - `status.txt`
   - `exit_code.txt`
   - `heartbeat.txt`
   - `screen -ls` 会话状态
8. 若 `status.txt = DONE` 或 `exit_code.txt = 0`，即使后台分离的 `screen` 仍存在，也视为任务完成。

## 最小 Paramiko 诊断模板（仅一次性脚本）

以下模板仅用于一次性诊断脚本，不可用于 UI/业务运行时代码：

```python
import json, pathlib, paramiko

cfg = json.loads((pathlib.Path.home() / "AppData/Roaming/H2OMeta/config.json").read_text(encoding="utf-8"))
ssh_cfg = cfg["ssh"]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(
    hostname=ssh_cfg["host"],
    port=int(ssh_cfg.get("port", 22)),
    username=ssh_cfg["user"],
    password=ssh_cfg.get("password") or None,
    key_filename=ssh_cfg.get("key_file") or None if ssh_cfg.get("use_key") else None,
    timeout=10,
)
stdin, stdout, stderr = client.exec_command("hostname && whoami", timeout=10)
print(stdout.read().decode("utf-8", "ignore"))
print(stderr.read().decode("utf-8", "ignore"))
client.close()
```

说明：在应用运行时（尤其 UI 线程或多线程场景）禁止直接调用 `exec_command`，统一走 `SSHService.run()` 串行队列。

## 参考资料

- `docs/SSH_ACCESS_PLAYBOOK.md`
- `docs/ops/remote-conda-no-sudo.md`

## 远程 Conda（无 sudo）基线（必须复用）

当需要远程依赖安装时，默认**不要**使用 `sudo`。

1. Conda 路径按以下顺序解析：
   - 首选 `core/environment/h2o_env_paths.py` 中的自管路径常量（`H2O_CONDA_EXE`）
   - `%APPDATA%\\H2OMeta\\config.json` -> `linux.conda_executable`
   - 回退：`~/.h2ometa/conda/bin/conda`
2. 仅使用用户权限创建环境：
   - `<conda> create -y -p ~/.h2ometa/conda/envs/<env_name> python=3.10`
3. 依赖安装到目标环境：
   - `<conda> run -p ~/.h2ometa/conda/envs/<env_name> python -m pip install <pkg>`
   - 或 `<conda> install -y -p ~/.h2ometa/conda/envs/<env_name> -c conda-forge <pkg>`
4. 验证：
   - `<conda> run -p ~/.h2ometa/conda/envs/<env_name> python -V`
5. 自动化脚本中优先使用 `conda run -p ...`，不要依赖 `conda activate`。
6. 若某些包依赖系统二进制（如 `unrar`）且无法使用 sudo：
   - 保持流水线 Python 回退方案（如 `rarfile`）可用，
   - 或改用 `.zip` / `.tar.gz` 测试输入。

## 远程长耗时安装基线（必须复用）

对于预计超过约 30s 的远程安装/下载/引导任务（如 Miniforge、工具环境安装、数据库下载），必须使用**远程后台分离任务**模型：

1. 不要将长耗时远程安装绑定到本地 UI 进程生命周期。
2. 远程以后台分离模式启动（优先 `screen`），并持久化任务元数据。
3. 状态文件写入与对账顺序必须是：
   - `status.txt`
   - `exit_code.txt`
   - `heartbeat.txt`
   - 后台分离会话状态（`screen -ls`）
4. 应用关闭/重启后，任务必须继续在远端运行；下次启动应通过任务元数据 + 状态文件恢复监控。
5. `status.txt = DONE` 或 `exit_code.txt = 0` 即视为完成，即使后台分离会话仍存在。
6. 启动阶段 UX 规则：
   - 自动引导成功不弹阻塞式成功对话框
   - 进度/成功使用非阻塞状态提示（状态栏/Toast）
   - 仅在需要用户决策时使用阻塞对话框（失败/磁盘/权限升级）
7. 复用以下现有模式：
   - `core/environment/env_installer.py`
   - `core/execution/execution_reconcile_service.py`
   - `core/execution/job_monitor.py`

### 最后验证

- 日期：`2026-03-17`
- 远程环境创建成功：`codex_probe_20260317`
- 环境内 Python：`3.10.20`

## 用户偏好：提交输出（必须复用）

当用户说 `提交` 时：

1. 必须始终提供：
   - commit hash
   - commit 标题（主题行）
   - 详细变更摘要（新增/修改/修复）
   - 变更文件清单
2. 摘要必须足够明确，便于快速判断是否回滚。
3. 绝不能只返回标题。

## 用户偏好：本地权限错误（必须复用）

当本地命令/测试因 temp/cache 路径权限拒绝失败时：

1. 不要在本地清理上反复尝试多轮。
2. 立即升级执行权限并继续。
3. 除非用户明确要求，否则将此作为默认处理策略。

## Windows Codex UTF-8 基线（必须复用）

在 Windows 上运行本地 shell 命令（尤其 `bash`/WSL）时，先统一编码环境：

1. 当前会话优先设置 UTF-8 代码页与流编码。
2. 确保 Codex -> WSL 路径设置 `WSL_UTF8=1`。
3. 同时设置 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8`，避免混合解码问题。
4. 若 `wsl --status` 或 `wsl -e ...` 返回 `E_ACCESSDENIED`，优先判定为 WSL 权限/服务问题，不要误判成纯编码问题。
5. 使用 `scripts/codex_wsl_utf8_doctor.ps1` 做可复现诊断与会话级修复。

## 执行流水线基线（必须复用）

修改工具执行链路时，必须保持现有“两阶段异步模型”：

1. `ToolEngine.execute()` 必须保持主线程轻量。
2. 远程准备逻辑必须放在 `core/execution/execution_preparer.py`，不能直接写在 `ToolEngine.execute()`。
3. 准备阶段包含：
   - 当 `remote_base` 以 `~` 开头时做展开
   - 创建 `output_dir`
   - 可选上传插件 `workflow/`
   - 构建最终命令
4. 只有准备成功后才能提交队列。
5. `ServiceLocator` 负责以下交接：
   - 准备成功 -> `JobQueue.submit()`
   - 队列启动 -> 异步 screen 下发
6. Screen 下发的 SSH 工作必须归属 `TaskRunner`，不应放在主 Qt 槽中。
7. `JobDispatcher.start_waiting()` 必须留在主线程，不要把 waiter 注册移到 worker 线程。
8. 为兼容现有 SQLite 项目库，持久化执行状态必须保持在当前 schema 集合内：
   - `pending`
   - `running`
   - `completed`
   - `failed`
   - `retrying`
   未有明确迁移方案前，不要新增持久化 `preparing` 状态。
9. 若 `ToolEngine` 在无准备调度器场景下使用，必须保留同步回退路径，不能静默丢弃执行。

## Qt 弹出圆角浮层（必须复用）

实现带圆角的下拉菜单/浮层时：
- **必须加 `NoDropShadowWindowHint`** 关闭系统原生阴影
- **顶层透明**（`WA_TranslucentBackground = True`），**内层 panel 负责视觉**
- **外层留 margin** 给自定义阴影留空间
- 参考：`ui/widgets/project_selector.py`

## UI 图标基线（必须复用）

1. **必须**使用 `qtawesome` 作为 UI 图标来源（例如 `qta.icon("ph.xxx")`）。
2. **禁止**在状态栏、按钮、导航、卡片中使用 Unicode emoji（`⏳/✅/❌/⚙️`）充当视觉图标。
3. 状态文本保持语义表达，图标语义由 `qtawesome` 承担。
4. 图标**必须**支持统一颜色与 hover/active 样式。
5. Emoji 仅允许用于用户输入/第三方原始文本，不得用于产品图标体系。

## Thread Safety & SSH Anti-Crash（Must Reuse）

**三条硬禁令，违反必崩：**

1. Qt slot / 主线程中 **禁止**直接调用任何 SSH 命令或阻塞操作。
2. 所有 SSH 命令必须走 `SSHService.run(cmd)` 单队列，
   **禁止** 自建 `paramiko.SSHClient()` 或绕过队列并发调用。
3. QThread worker 内 **禁止** 直接操作任何 Qt Widget，
   结果只能通过 `pyqtSignal` 回传主线程再更新 UI。

**长任务（>5s）额外禁令：**

4. conda 安装 / 工具安装 / 大文件下载必须用 detached `screen` 启动，
   不得绑定本地进程生命周期，参考 `core/environment/env_installer.py`。

**提交前自检：**
- 新增 SSH 调用是否走了 `SSHService.run()`？
- 新增 worker 是否有直接操作 Widget？
- 新增按钮回调是否有阻塞（sleep / wait / run）？

## 当前任务状态（Codex 每次完成后更新）

最近完成：数据库管理系统 3 日计划（Task 1-7） ✅
  - 新增数据库服务与独立数据库页面（含安装/状态/进度逻辑）
  - 配置结构升级为 `databases: { db_root, overrides }`，并完成兼容迁移
  - 路径解析优先级落地：`overrides > db_root+registry > legacy`
  - 清理插件 `tool.yaml` 中数据库绝对路径 `default`
  - Gate 与全量测试通过（`472 passed, 7 skipped`）
  - 修复 Windows `offscreen` UI 测试退出期崩溃：测试模式禁用 SSH/Conda 自动线程与 QtWebEngine 初始化

当前进行中：等待下一任务
  - 如需可继续执行提交（commit）或拆分 PR 说明文档

阻塞任务：无
