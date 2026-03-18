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
