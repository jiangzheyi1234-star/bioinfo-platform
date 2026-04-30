#!/usr/bin/env python3
"""Remove remote database smoke-test records and fixture directories."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
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


API_BASE = "http://127.0.0.1:8765"
TEST_PATH_MARKERS = (
    "/database-mvp/",
    "/database-real-smoke/",
    "/smoke-databases/",
)
TEST_TEXT_MARKERS = ("smoke", "mvp", "fixture", "test")
REMOTE_TEST_DIRS = (
    "$HOME/.h2ometa/runner/shared/data/database-mvp",
    "$HOME/.h2ometa/runner/shared/data/database-real-smoke",
    "$HOME/.h2ometa/smoke-databases",
)


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


def http_json(method: str, path: str, *, timeout: float = 20) -> Any:
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc


def should_delete_database(item: dict[str, Any]) -> bool:
    path = str(item.get("path") or "").replace("\\", "/")
    if any(marker in path for marker in TEST_PATH_MARKERS):
        return True
    text = " ".join(str(item.get(key) or "") for key in ("id", "name", "description", "source")).lower()
    return any(marker in text for marker in TEST_TEXT_MARKERS)


def connect_ssh():
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
        raise RuntimeError(f"SSH failed: {result.message}")
    return result.client


def ssh_run(client, command: str, *, timeout: int = 120) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return exit_code, out, err


def main() -> int:
    health = http_json("GET", "/health", timeout=10)
    print_json("LOCAL_API_HEALTH", health)

    databases = http_json("GET", "/api/v1/databases", timeout=20)["data"]["items"]
    candidates = [item for item in databases if should_delete_database(item)]
    print_json(
        "DATABASE_CLEANUP_CANDIDATES",
        [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "path": item.get("path"),
                "templateId": (item.get("metadata") or {}).get("templateId"),
            }
            for item in candidates
        ],
    )

    deleted_records: list[str] = []
    for item in candidates:
        database_id = str(item.get("id") or "")
        if not database_id:
            continue
        http_json("DELETE", f"/api/v1/databases/{urllib.parse.quote(database_id, safe='')}", timeout=20)
        deleted_records.append(database_id)
    print_json("DATABASE_RECORDS_DELETED", deleted_records)

    client = connect_ssh()
    try:
        quoted_dirs = " ".join(f'"{path}"' for path in REMOTE_TEST_DIRS)
        command = (
            "set -e; "
            f"for path in {quoted_dirs}; do "
            "expanded=$(eval printf '%s' \"$path\"); "
            "if [ -e \"$expanded\" ]; then printf 'DELETE %s\\n' \"$expanded\"; rm -rf \"$expanded\"; "
            "else printf 'SKIP %s\\n' \"$expanded\"; fi; "
            "done"
        )
        exit_code, stdout, stderr = ssh_run(client, command, timeout=300)
        print_json("REMOTE_DIRECTORY_CLEANUP", {"exitCode": exit_code, "stdout": stdout, "stderr": stderr})
        return exit_code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
