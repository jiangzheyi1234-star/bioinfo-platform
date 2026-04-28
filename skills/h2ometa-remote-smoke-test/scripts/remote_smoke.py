#!/usr/bin/env python3
"""Project-local smoke test for the configured H2OMeta remote server."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
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


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if "password" in key_lower or "token" in key_lower or key_lower.endswith("_ref"):
                redacted[key] = "<redacted>" if item else ""
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(redact(payload), ensure_ascii=False, sort_keys=True)}")


def load_project_modules():
    try:
        from config import (
            get_config,
            normalize_ssh_config,
            resolve_ssh_config_target,
            resolve_ssh_password,
        )
        from core.remote.ssh_connector import ssh_connect
    except Exception as exc:
        raise SystemExit(
            "ERROR: failed to import project modules. If this is WSL Python, rerun through "
            "Windows conda: C:\\Users\\Administrator\\miniconda3\\Scripts\\conda.exe "
            "run -n bio_ui python skills\\h2ometa-remote-smoke-test\\scripts\\remote_smoke.py\n"
            f"DETAIL: {exc}"
        ) from exc
    return get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password, ssh_connect


def http_json(method: str, api_base: str, path: str, timeout: float) -> tuple[bool, Any]:
    url = f"{api_base.rstrip('/')}{path}"
    data = b"{}" if method.upper() in {"POST", "PUT", "PATCH"} else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = raw
        return False, {"status": exc.code, "error": body}
    except Exception as exc:
        return False, {"error": str(exc)}


def test_ssh() -> tuple[bool, dict[str, Any]]:
    get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password, ssh_connect = load_project_modules()
    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    use_agent = auth_mode == "agent"
    target = {
        "auth_mode": auth_mode,
        "host": resolved.get("host", ""),
        "port": int(resolved.get("port", 22)),
        "user": resolved.get("user", ""),
        "timeout_sec": int(resolved.get("timeout_sec", 5)),
        "auto_connect_on_startup": bool(ssh_cfg.get("auto_connect_on_startup", False)),
        "credential_available": bool(password),
        "key_file_configured": bool(key_file),
        "use_agent": use_agent,
    }
    print_json("SSH_TARGET", target)
    result = ssh_connect(
        ip=str(target["host"]),
        port=int(target["port"]),
        user=str(target["user"]),
        password=password,
        key_file=key_file,
        use_agent=use_agent,
        timeout=int(target["timeout_sec"]),
    )
    if result.client:
        result.client.close()
    payload = {
        "ok": bool(result.ok),
        "message": result.message,
        "host": target["host"],
        "port": target["port"],
        "user": target["user"],
    }
    print_json("SSH_RESULT", payload)
    return bool(result.ok), payload


def check_local_api(api_base: str, timeout: float, *, bootstrap: bool, require_api: bool) -> bool:
    checks = [
        ("GET", "/health"),
        ("GET", "/api/v1/ssh/status"),
        ("GET", "/api/v1/servers"),
    ]
    api_ok = True
    servers_payload: Any = None
    for method, path in checks:
        ok, payload = http_json(method, api_base, path, timeout)
        print_json(f"API {method} {path}", {"ok": ok, "payload": payload})
        api_ok = api_ok and ok
        if path == "/api/v1/servers":
            servers_payload = payload

    if not api_ok:
        if require_api or bootstrap:
            print("ERROR: local API is required but not reachable")
            return False
        print("WARN: local API is not running; SSH connectivity was still tested")
        return True

    items = (((servers_payload or {}).get("data") or {}).get("items") or [])
    if not items:
        print("WARN: local API returned no registered servers")
        return True

    server = items[0]
    server_id = str(server.get("serverId") or "")
    service_port_raw = server.get("service_port")
    if service_port_raw is None:
        service_port_raw = server.get("servicePort")
    service_port = int(service_port_raw) if service_port_raw not in (None, "") else None
    print_json(
        "SERVER_SELECTED",
        {
            "serverId": server_id,
            "label": server.get("label", ""),
            "connected": server.get("connected", False),
            "ready": server.get("ready", False),
            "service_port": service_port,
            "dynamic_port_expected": None if service_port is None else service_port != 8876,
        },
    )

    if not bootstrap:
        if service_port == 8876:
            print("WARN: saved service_port is still 8876; run --bootstrap to verify the dynamic-port path")
        return True

    if not server_id:
        print("ERROR: cannot bootstrap because serverId is missing")
        return False

    ok, payload = http_json("POST", api_base, f"/api/v1/servers/{server_id}/ensure-runner", timeout=120)
    print_json(f"API POST /api/v1/servers/{server_id}/ensure-runner", {"ok": ok, "payload": payload})
    if not ok:
        return False

    ok, payload = http_json("GET", api_base, f"/api/v1/servers/{server_id}/health", timeout=timeout)
    print_json(f"API GET /api/v1/servers/{server_id}/health", {"ok": ok, "payload": payload})
    if not ok:
        return False

    refreshed_ok, refreshed = http_json("GET", api_base, f"/api/v1/servers/{server_id}", timeout=timeout)
    print_json(f"API GET /api/v1/servers/{server_id}", {"ok": refreshed_ok, "payload": refreshed})
    if refreshed_ok:
        data = (refreshed or {}).get("data") or {}
        refreshed_port = int(data.get("service_port") or data.get("servicePort") or 0)
        if refreshed_port == 8876:
            print("ERROR: bootstrap completed but service_port is still the stale fixed port 8876")
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test this repo's configured H2OMeta remote server.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765", help="Local backend API base URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    parser.add_argument("--bootstrap", action="store_true", help="Run the mutating remote runner bootstrap through local API")
    parser.add_argument("--require-api", action="store_true", help="Fail if local API is not reachable")
    args = parser.parse_args()

    ssh_ok, _ = test_ssh()
    api_ok = check_local_api(args.api_base, args.timeout, bootstrap=args.bootstrap, require_api=args.require_api)
    if ssh_ok and api_ok:
        print("RESULT: ok")
        return 0
    print("RESULT: failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
