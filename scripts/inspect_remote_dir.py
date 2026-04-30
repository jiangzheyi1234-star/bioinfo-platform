from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_config, normalize_ssh_config, resolve_ssh_password, resolve_ssh_config_target
from core.remote.ssh_connector import ssh_connect


def main() -> int:
    path = sys.argv[1]
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
    client = result.client
    try:
        cmd = (
            f"printf 'PATH=%s\\n' {path!r}; "
            f"if [ -d {path!r} ]; then "
            f"printf 'TYPE=dir\\n'; "
            f"find {path!r} -maxdepth 1 -mindepth 1 -printf '%f|%y\\n' | sort; "
            f"else printf 'TYPE=missing-or-file\\n'; ls -ld {path!r}; fi"
        )
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=20)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(out)
        if err:
            print(err, file=sys.stderr)
        return exit_code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
