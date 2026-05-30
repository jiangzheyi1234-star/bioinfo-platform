from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


def import_repo_script(module_name: str) -> Any:
    scripts_dir = find_repo_root() / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return __import__(module_name)


def response_data(payload: dict[str, Any]) -> Any:
    data = payload["data"]
    if isinstance(data, dict) and set(data.keys()) == {"data"}:
        return data["data"]
    return data


def selected_server_id(api_base: str, *, timeout: float = 5.0) -> str:
    remote_smoke = import_repo_script("remote_smoke")
    ready, context = remote_smoke.check_local_api(api_base, timeout, bootstrap=False)
    if not ready or not context:
        raise RuntimeError("Local API did not return a ready server context.")
    server_id = str(context.get("serverId") or "").strip()
    if not server_id:
        raise RuntimeError("Local API server context did not include serverId.")
    return server_id
