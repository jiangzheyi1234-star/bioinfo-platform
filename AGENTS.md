# Persistent Agent Notes

## SSH Access Baseline (Must Reuse)

When a task requires remote checks/runs/downloads, always follow this order:

1. Read SSH config from `%APPDATA%\\H2OMeta\\config.json`.
2. Prefer existing project service (`core/remote/ssh_service.py`) via ServiceLocator.
3. If a direct script is needed, use Paramiko with:
   - `host/port/user/password` (or `key_file` when `use_key=true`)
   - timeout 10s
   - `AutoAddPolicy` only for this internal environment.
4. For remote commands with paths, always wrap with `shlex.quote(...)`.
5. Before run/download, ensure connection is active (`is_connected`).
6. For workflow status checks, read in this priority:
   - `status.txt`
   - `exit_code.txt`
   - `heartbeat.txt`
   - `screen -ls` session
7. If `status.txt = DONE` or `exit_code.txt = 0`, treat as completed even if detached `screen` session still exists.

## Minimal Paramiko Template

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

## Reference

- `docs/SSH_ACCESS_PLAYBOOK.md`
- `docs/ops/remote-conda-no-sudo.md`

## Remote Conda (No Sudo) Baseline (Must Reuse)

When remote dependency setup is needed, do **not** use `sudo` by default.

1. Resolve conda path in this order:
   - `%APPDATA%\\H2OMeta\\config.json` -> `linux.conda_executable`
   - fallback: `/home/zyserver/anaconda3/bin/conda`
2. Create env with user permissions only:
   - `<conda> create -y -n <env_name> python=3.10`
3. Install dependencies into the target env:
   - `<conda> run -n <env_name> python -m pip install <pkg>`
   - or `<conda> install -y -n <env_name> -c conda-forge <pkg>`
4. Verify:
   - `<conda> run -n <env_name> python -V`
5. Prefer `conda run -n ...` over `conda activate` in automated scripts.
6. If a package needs system binaries (e.g. `unrar`) and no sudo is available:
   - keep pipeline Python fallback path enabled (e.g. `rarfile`),
   - or switch test input to `.zip` / `.tar.gz`.

### Last Verified

- Date: `2026-03-17`
- Remote environment creation success: `codex_probe_20260317`
- Python in env: `3.10.20`

## User Preference: Commit Output (Must Reuse)

When user asks `提交`:

1. Always provide:
   - commit hash
   - commit title (subject)
   - detailed summary of what was added/changed/fixed
   - changed file list
2. The summary should be explicit enough for quick rollback decisions.
3. Never return only the title.

## User Preference: Local Permission Errors (Must Reuse)

When local command/test failures are caused by permission-denied temp/cache paths:

1. Do not spend extra rounds on repeated local cleanup attempts.
2. Escalate immediately and continue with elevated command execution.
3. Treat this as preferred default unless user explicitly asks otherwise.

## Windows Codex UTF-8 Baseline (Must Reuse)

When running local shell commands on Windows (especially `bash`/WSL), always align encoding first:

1. Prefer UTF-8 code page and stream encoding in current session.
2. Ensure `WSL_UTF8=1` for Codex -> WSL command path.
3. Also set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` to avoid mixed decoding.
4. If `wsl --status` or `wsl -e ...` returns `E_ACCESSDENIED`, treat it as WSL permission/service issue first; do not misdiagnose as pure encoding.
5. Use `scripts/codex_wsl_utf8_doctor.ps1` for repeatable diagnosis and session-level fix.

## Execution Pipeline Baseline (Must Reuse)

When changing the tool execution path, preserve the current two-stage async model:

1. `ToolEngine.execute()` must stay lightweight on the main thread.
2. Remote preparation belongs in `core/execution/execution_preparer.py`, not directly in `ToolEngine.execute()`.
3. Preparation includes:
   - expanding `remote_base` when it starts with `~`
   - creating `output_dir`
   - optional plugin `workflow/` upload
   - building the final command
4. Queue submission should happen only after preparation succeeds.
5. `ServiceLocator` owns the handoff from:
   - preparation success -> `JobQueue.submit()`
   - queue start -> async screen dispatch
6. Screen dispatch SSH work belongs in `TaskRunner`, not in the main Qt slot.
7. `JobDispatcher.start_waiting()` must remain on the main thread; do not move waiter registration into a worker thread.
8. For compatibility with existing SQLite project DBs, keep persisted execution status within the current schema set:
   - `pending`
   - `running`
   - `completed`
   - `failed`
   - `retrying`
   Do not introduce a new persisted `preparing` status without an explicit migration plan.
9. If `ToolEngine` is used without a preparation scheduler, keep the synchronous fallback path working instead of silently dropping execution.

## Qt Popup 圆角浮层 (Must Reuse)

实现带圆角的下拉菜单/浮层时：
- **必须加 `NoDropShadowWindowHint`** 关闭系统原生阴影
- **顶层透明** (`WA_TranslucentBackground = True`)，**内层panel负责视觉**
- **外层留 margin** 给自定义阴影留空间
- 参考：`ui/widgets/project_selector.py`

## Current Task State（Codex 每次完成后更新）

Last completed: 启动升级提示 + 数据库路径缺失错误文案增强 ✅
  - MainWindow 启动时检测 legacy 数据库配置并一次性提示升级（支持“去设置”直达数据库页 ⚙️）
  - 提示确认状态持久化为 `runtime.db_config_upgrade_notice_ack_v1`
  - 工具执行前必需数据库路径缺失时，错误信息增加 db_id 与排查指引（overrides/db_root/设置入口）
  - 新增测试：`tests/test_main_window_db_notice.py`
  - 更新测试：`tests/test_tool_bridge_database_paths.py`（校验新错误文案）
  - 全量回归通过（`500 passed, 7 skipped`）

Previous completed: 数据库路径配置彻底收敛（移除 legacy + 引入 DatabasePathResolver） ✅
  - 新增 `core/data/database_path_resolver.py`，集中解析顺序：`overrides[db_id] > db_root+registry`
  - `ToolBridgeService.build_database_paths()` 改为薄封装，移除 legacy flat 兜底读取
  - `~` 在 SSH 在线时展开并缓存；SSH 离线时保留原值
  - `config.normalize_config()` 移除数据库旧字段迁移逻辑；非标准 databases 结构直接回退空标准结构
  - 更新测试：移除 legacy 命中预期，新增 resolver 单测与配置收敛断言
  - 定向与回归测试通过（路径解析、数据库页、ui smoke）

Previous completed: 数据库页改为“仅 ⚙️ 弹窗配置”并接入候选路径磁盘信息 ✅
  - 主页面移除 db_root 输入行，顶部新增 32x32 圆形 `⚙️` 按钮（与“全部刷新”并排）
  - 新增数据库设置弹窗：根目录输入 + `📁 浏览` + 只读服务器信息 + 取消/保存
  - 服务器信息实时展示：SSH 用户、`~` 展开后的真实路径、候选路径分区磁盘剩余
  - 保存链路复用既有严格校验：路径解析 -> `-d/-x/-w` -> `touch/rm` 探针 -> 自动 `mkdir -p`（仅不存在时）
  - 空路径策略与“记住选择”策略保持：`~/databases / 手动输入 / 取消`
  - 保持执行链路优先级：`overrides > db_root+registry > legacy`，兼容旧 override key
  - 新增与回归测试通过（数据库页/路径解析/UI smoke 定向用例）

Now working on: 等待下一任务
  - 如需可继续执行提交（commit）或拆分 PR 说明文档

Blocked tasks: 无
