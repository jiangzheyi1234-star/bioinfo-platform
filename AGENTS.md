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

Last completed: 数据库管理系统 3 日计划（Task 1-7） ✅
  - 新增数据库服务与独立数据库页面（含安装/状态/进度逻辑）
  - 配置结构升级为 `databases: { db_root, overrides }`，并完成兼容迁移
  - 路径解析优先级落地：`overrides > db_root+registry > legacy`
  - 清理插件 `tool.yaml` 中数据库绝对路径 `default`
  - Gate 与全量测试通过（`472 passed, 7 skipped`）
  - 修复 Windows `offscreen` UI 测试退出期崩溃：测试模式禁用 SSH/Conda 自动线程与 QtWebEngine 初始化

Now working on: 等待下一任务
  - 如需可继续执行提交（commit）或拆分 PR 说明文档

Blocked tasks: 无
