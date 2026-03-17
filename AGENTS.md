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
