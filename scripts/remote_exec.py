from __future__ import annotations

import os
import base64
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password  # noqa: E402
from core.remote.ssh_connector import ssh_connect  # noqa: E402


def main() -> int:
    command = sys.argv[1] if len(sys.argv) >= 2 else os.environ.get("REMOTE_EXEC_COMMAND", "")
    if not command and os.environ.get("REMOTE_EXEC_COMMAND_B64"):
        command = base64.b64decode(os.environ["REMOTE_EXEC_COMMAND_B64"]).decode("utf-8")
    if not command:
        print("usage: remote_exec.py <command>", file=sys.stderr)
        return 2
    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=auth_mode == "agent",
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        print(f"SSH failed: {result.message}", file=sys.stderr)
        return 1
    try:
        _stdin, stdout, stderr = result.client.exec_command(command, timeout=1800)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        return exit_code
    finally:
        result.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
