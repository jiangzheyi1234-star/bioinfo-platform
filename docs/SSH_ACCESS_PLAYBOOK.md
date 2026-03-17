# SSH Access Playbook (H2OMeta)

## 1. Config source

Use local config file:

- Windows: `%APPDATA%\\H2OMeta\\config.json`
- Key fields: `ssh.host`, `ssh.port`, `ssh.user`, `ssh.password`, `ssh.use_key`, `ssh.key_file`

## 2. Preferred integration path

Use project service first:

- `core/remote/ssh_service.py`
- wired through `core/service_locator.py`

Avoid creating duplicate SSH connection managers in UI/business code.

## 3. Direct remote diagnostics template

```python
import json
import pathlib
import paramiko

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

## 4. Safe command rules

- Always quote remote paths: `shlex.quote(path)`
- Check `is_connected` before `run/download/upload`
- Keep command timeout explicit (10s default for diagnostics)

## 5. Task-state reconciliation rules

For long-running jobs (`screen` + status files), determine truth in this order:

1. `status.txt`
2. `exit_code.txt`
3. `heartbeat.txt`
4. `screen -ls`

If `status.txt == DONE` or `exit_code.txt == 0`, mark completed even if detached screen session still exists.

## 6. Common pitfalls

- Missing file during artifact cache should be treated as "skip" (debug), not hard warning.
- Detached `screen` may remain after completion and should not force task to stay `running`.
- Read/write local `project.db` may require elevated permission outside sandbox.
