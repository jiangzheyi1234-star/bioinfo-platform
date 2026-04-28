#!/usr/bin/env python3
"""Clean the installed H2OMeta remote runner release on the configured SSH server."""

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
    from core.remote_runner.bundle import REMOTE_RUNNER_VERSION

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

    release = f"$HOME/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}"
    bundle = f"$HOME/.h2ometa/runner/bundle-{REMOTE_RUNNER_VERSION}.tar.gz"
    command = (
        "set -e; "
        "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
        "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true; "
        "rm -rf "
        f"{release} "
        "$HOME/.h2ometa/runner/current "
        "$HOME/.h2ometa/runner/shared/runtime/runner-state.json "
        f"{bundle}"
    )
    try:
        stdin, stdout, stderr = result.client.exec_command(command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        print_json(
            "REMOTE_CLEAN",
            {
                "exit_code": exit_code,
                "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
                "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
                "removed_release": f"~/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}",
                "preserved_shared_data": True,
            },
        )
        return 0 if exit_code == 0 else 1
    finally:
        result.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
