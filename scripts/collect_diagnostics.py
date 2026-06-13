"""Collect a diagnostics bundle for H2OMeta troubleshooting.

Exports system info, health endpoints, queue state, worker state,
and recent logs. Filters sensitive fields (tokens, passwords, paths).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "token",
    "password",
    "password_ref",
    "secret",
    "api_key",
    "apiKey",
    "authorization",
    "runner_token",
    "ssh_password",
    "identity_ref",
}

SENSITIVE_PATH_PARTS = {
    ".ssh",
    ".env",
    "keyring",
    "credential",
}


def filter_sensitive(data: Any) -> Any:
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if _is_sensitive_key(key):
                result[key] = "***REDACTED***"
            elif _is_sensitive_path(key, value):
                result[key] = "***PATH_REDACTED***"
            else:
                result[key] = filter_sensitive(value)
        return result
    if isinstance(data, list):
        return [filter_sensitive(item) for item in data]
    if isinstance(data, str) and _looks_like_secret(data):
        return "***REDACTED***"
    return data


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return lower in SENSITIVE_KEYS


def _is_sensitive_path(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lower_key = key.lower()
    if "path" not in lower_key and "dir" not in lower_key and "file" not in lower_key:
        return False
    for part in SENSITIVE_PATH_PARTS:
        if part in value:
            return True
    return False


def _looks_like_secret(value: str) -> bool:
    if len(value) < 8:
        return False
    if re.match(r"^(Bearer|Basic)\s+\S+", value):
        return True
    if re.match(r"^[A-Za-z0-9+/]{20,}={0,2}$", value):
        return True
    return False


def collect_system_info() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "pid": os.getpid(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cpuCount": os.cpu_count(),
    }


def collect_disk_info(path: str) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": path,
            "totalGb": round(usage.total / (1024**3), 2),
            "freeGb": round(usage.free / (1024**3), 2),
            "usagePercent": round(usage.used / usage.total * 100, 1),
        }
    except OSError as exc:
        return {"path": path, "error": str(exc)}


def collect_health_via_http(api_base: str) -> dict[str, Any]:
    import urllib.request
    import urllib.error

    results: dict[str, Any] = {}
    endpoints = ["/health", "/api/v1/service-info"]
    for endpoint in endpoints:
        url = f"{api_base}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
                results[endpoint] = filter_sensitive(body)
        except urllib.error.URLError as exc:
            results[endpoint] = {"error": str(exc)}
        except Exception as exc:
            results[endpoint] = {"error": str(exc)}
    return results


def collect_remote_runner_health(api_base: str, token: str) -> dict[str, Any]:
    import urllib.request
    import urllib.error

    results: dict[str, Any] = {}
    endpoints = ["/health/startup", "/health/live", "/health/ready", "/health/workers"]
    for endpoint in endpoints:
        url = f"{api_base}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
                results[endpoint] = filter_sensitive(body)
        except urllib.error.URLError as exc:
            results[endpoint] = {"error": str(exc)}
        except Exception as exc:
            results[endpoint] = {"error": str(exc)}
    return results


def collect_environment() -> dict[str, str]:
    allowed_prefixes = ("H2OMETA_", "UV_", "CONDA_", "MAMBA_", "SNAKEMAKE_")
    result: dict[str, str] = {}
    for key, value in sorted(os.environ.items()):
        if any(key.startswith(p) for p in allowed_prefixes):
            if any(s in key.lower() for s in ("token", "password", "secret", "key")):
                result[key] = "***REDACTED***"
            else:
                result[key] = value
    return result


def build_diagnostics_bundle(
    *,
    local_api_base: str = "http://127.0.0.1:8765",
    remote_runner_base: str = "http://127.0.0.1:9876",
    runner_token: str = "",
    output_path: str | None = None,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "diagnosticsVersion": "1.0",
        "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system": collect_system_info(),
        "environment": collect_environment(),
        "localApi": collect_health_via_http(local_api_base),
        "remoteRunner": collect_remote_runner_health(remote_runner_base, runner_token),
    }
    data_root = os.environ.get("H2OMETA_DATA_ROOT", "")
    if data_root:
        bundle["disk"] = collect_disk_info(data_root)
    else:
        bundle["disk"] = collect_disk_info("/")
    bundle = filter_sensitive(bundle)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"Diagnostics bundle written to: {path}")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect H2OMeta diagnostics bundle")
    parser.add_argument("--local-api", default="http://127.0.0.1:8765", help="Local API base URL")
    parser.add_argument("--remote-runner", default="http://127.0.0.1:9876", help="Remote runner base URL")
    parser.add_argument("--token", default="", help="Remote runner auth token (or set H2OMETA_RUNNER_TOKEN)")
    parser.add_argument("--output", "-o", default="", help="Output file path (default: stdout)")
    args = parser.parse_args()
    token = args.token or os.environ.get("H2OMETA_RUNNER_TOKEN", "")
    bundle = build_diagnostics_bundle(
        local_api_base=args.local_api,
        remote_runner_base=args.remote_runner,
        runner_token=token,
        output_path=args.output or None,
    )
    if not args.output:
        print(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
