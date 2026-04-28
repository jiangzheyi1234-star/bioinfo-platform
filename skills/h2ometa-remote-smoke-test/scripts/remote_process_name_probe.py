#!/usr/bin/env python3
"""Read-only probe for the remote runner process name."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def main() -> int:
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

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
        print_json("SSH_RESULT", {"ok": False, "message": result.message})
        return 1

    commands = {
        "release_run_prctl": "grep -nE 'prctl|_set_process_name|h2ometa-remote|ctypes' ~/.h2ometa/runner/current/remote_runner/run.py || true",
        "release_run_head": "sed -n '1,45p' ~/.h2ometa/runner/current/remote_runner/run.py",
        "runner_pid": "python3 -c \"import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/runtime/runner-state.json').read_text())['pid'])\"",
        "runner_comm": "pid=$(python3 -c \"import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/runtime/runner-state.json').read_text())['pid'])\"); cat /proc/$pid/comm 2>/dev/null || true",
        "runner_cmdline": "pid=$(python3 -c \"import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/runtime/runner-state.json').read_text())['pid'])\"); tr '\\0' ' ' </proc/$pid/cmdline 2>/dev/null || true",
        "runner_ss": "port=$(python3 -c \"import json,pathlib; print(json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/runtime/runner-state.json').read_text())['bindPort'])\"); ss -lntup 2>/dev/null | grep \":$port \" || true",
    }
    try:
        for label, command in commands.items():
            _stdin, stdout, stderr = result.client.exec_command(command, timeout=20)
            exit_code = stdout.channel.recv_exit_status()
            print_json(
                f"REMOTE_{label.upper()}",
                {
                    "exit_code": exit_code,
                    "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
                    "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
                },
            )
    finally:
        result.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
