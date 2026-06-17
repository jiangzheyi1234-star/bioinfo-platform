"""Collect a diagnostics bundle for H2OMeta troubleshooting.

Exports system info, health endpoints, queue state, worker state,
and recent logs. Filters sensitive fields (tokens, passwords, paths).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
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
    endpoints = [
        "/health/startup",
        "/health/live",
        "/health/ready",
        "/health/meta",
        "/health/workers",
        "/health/execution-diagnostics",
    ]
    for endpoint in endpoints:
        url = f"{api_base}{endpoint}"
        try:
            req = urllib.request.Request(url, method="GET")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
                results[endpoint] = filter_sensitive({"httpStatus": int(resp.status), "body": body})
        except urllib.error.HTTPError as exc:
            body = _json_http_error_body(exc)
            results[endpoint] = filter_sensitive(body) if body else {"error": str(exc)}
        except urllib.error.URLError as exc:
            results[endpoint] = _runner_unreachable_error(exc)
        except Exception as exc:
            results[endpoint] = {"error": str(exc)}
    return results


def _json_http_error_body(exc) -> dict[str, Any] | None:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        body = json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    return {"httpStatus": int(exc.code), "body": body}


def _runner_unreachable_error(exc: BaseException) -> dict[str, Any]:
    return {
        "httpStatus": None,
        "body": None,
        "error": {
            "reasonCode": "RUNNER_UNREACHABLE",
            "message": str(exc),
            "errorType": type(exc).__name__,
        },
    }


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


def build_operator_diagnostics_bundle(
    *,
    local_api_base: str = "http://127.0.0.1:8765",
    remote_runner_base: str = "http://127.0.0.1:9876",
    runner_token: str = "",
    server_id: str = "",
    run_id: str = "",
    scenario_id: str = "",
    release_tag: str = "",
    source_commit: str = "",
    output_path: str | None = None,
) -> dict[str, Any]:
    collected_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    local_api = collect_health_via_http(local_api_base)
    remote_runner = collect_remote_runner_health(remote_runner_base, runner_token)
    bundle: dict[str, Any] = {
        "schemaVersion": "operator-diagnostics-bundle.v1",
        "collectedAt": collected_at,
        "identity": {
            "serverId": str(server_id or ""),
            "runId": str(run_id or ""),
            "scenarioId": str(scenario_id or ""),
        },
        "release": {
            "releaseTag": str(release_tag or ""),
            "sourceCommit": str(source_commit or ""),
        },
        "system": collect_system_info(),
        "environment": collect_environment(),
        "localApi": local_api,
        "remoteRunner": remote_runner,
        "disk": collect_disk_info(os.environ.get("H2OMETA_DATA_ROOT", "") or "/"),
        "includedSections": [
            "system",
            "environment",
            "localApi",
            "remoteRunner",
            "disk",
        ],
        "redactionPolicy": {
            "schemaVersion": "diagnostics-redaction.v1",
            "sensitiveKeys": sorted(SENSITIVE_KEYS),
            "sensitivePathParts": sorted(SENSITIVE_PATH_PARTS),
        },
    }
    bundle["summary"] = summarize_operator_diagnostics(bundle)
    bundle = filter_sensitive(bundle)
    bundle["bundleHash"] = _stable_bundle_hash(bundle)
    bundle["bundleId"] = f"opdiag_{bundle['bundleHash'][:16]}"
    if output_path:
        write_operator_diagnostics_bundle(bundle, Path(output_path))
    return bundle


def summarize_operator_diagnostics(bundle: dict[str, Any]) -> dict[str, Any]:
    remote = bundle.get("remoteRunner") if isinstance(bundle.get("remoteRunner"), dict) else {}
    endpoint_statuses: dict[str, Any] = {}
    reason_codes: list[str] = []
    reachable = False
    for endpoint, payload in sorted(remote.items()):
        endpoint_name = _endpoint_name(endpoint)
        status = _endpoint_status(payload)
        endpoint_statuses[endpoint_name] = status
        reachable = reachable or status.get("httpStatus") is not None
        reason_code = str(status.get("reasonCode") or "").strip()
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
    if not reachable and "RUNNER_UNREACHABLE" not in reason_codes:
        reason_codes.append("RUNNER_UNREACHABLE")
    ready = endpoint_statuses.get("ready") or {}
    return {
        "remoteRunnerReachable": reachable,
        "readinessOk": bool(ready.get("ok")),
        "reasonCodes": reason_codes,
        "endpointStatuses": endpoint_statuses,
    }


def write_operator_diagnostics_bundle(bundle: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def archive_operator_diagnostics_bundle_file(bundle: dict[str, Any], output_path: str) -> dict[str, Any]:
    from apps.remote_runner.config import load_remote_runner_config
    from apps.remote_runner.operator_diagnostics_bundle import archive_operator_diagnostics_bundle

    return archive_operator_diagnostics_bundle(
        load_remote_runner_config(),
        bundle=bundle,
        bundle_path=Path(output_path),
    )


def _endpoint_name(endpoint: str) -> str:
    return endpoint.strip("/").split("/")[-1].replace("-", "_")


def _endpoint_status(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"httpStatus": None, "ok": False, "reasonCode": "RUNNER_UNREACHABLE"}
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    readiness = data.get("readiness") if isinstance(data.get("readiness"), dict) else {}
    reason_code = (
        body.get("reasonCode")
        or data.get("reasonCode")
        or readiness.get("reasonCode")
        or error.get("reasonCode")
        or ""
    )
    status = body.get("status") or data.get("status") or ""
    return {
        "httpStatus": payload.get("httpStatus"),
        "ok": _status_ok(body=body, data=data, status=status),
        "status": str(status or ""),
        "reasonCode": str(reason_code or ""),
        "error": dict(error),
    }


def _status_ok(*, body: dict[str, Any], data: dict[str, Any], status: Any) -> bool:
    if "ok" in body:
        return bool(body.get("ok"))
    if "ok" in data:
        return bool(data.get("ok"))
    return str(status or "").lower() == "ok"


def _stable_bundle_hash(bundle: dict[str, Any]) -> str:
    comparable = {key: value for key, value in bundle.items() if key not in {"bundleHash", "bundleId"}}
    payload = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect H2OMeta diagnostics bundle")
    parser.add_argument("--local-api", default="http://127.0.0.1:8765", help="Local API base URL")
    parser.add_argument("--remote-runner", default="http://127.0.0.1:9876", help="Remote runner base URL")
    parser.add_argument("--token", default="", help="Remote runner auth token (or set H2OMETA_RUNNER_TOKEN)")
    parser.add_argument("--output", "-o", default="", help="Output file path (default: stdout)")
    parser.add_argument("--operator-bundle", action="store_true", help="Emit operator-diagnostics-bundle.v1")
    parser.add_argument("--server-id", default="", help="Server id to attach to an operator bundle")
    parser.add_argument("--run-id", default="", help="Run id to attach to an operator bundle")
    parser.add_argument("--scenario-id", default="", help="Scenario id to attach to an operator bundle")
    parser.add_argument("--release-tag", default="", help="Release tag to attach to an operator bundle")
    parser.add_argument("--source-commit", default="", help="Source commit to attach to an operator bundle")
    parser.add_argument("--archive", action="store_true", help="Archive the operator bundle in the remote-runner ledger")
    args = parser.parse_args()
    token = args.token or os.environ.get("H2OMETA_RUNNER_TOKEN", "")
    if args.operator_bundle:
        bundle = build_operator_diagnostics_bundle(
            local_api_base=args.local_api,
            remote_runner_base=args.remote_runner,
            runner_token=token,
            server_id=args.server_id,
            run_id=args.run_id,
            scenario_id=args.scenario_id,
            release_tag=args.release_tag,
            source_commit=args.source_commit,
            output_path=args.output or None,
        )
        if args.archive:
            if not args.output:
                raise SystemExit("--archive requires --output for stable artifact materialization")
            archive = archive_operator_diagnostics_bundle_file(bundle, args.output)
            print(json.dumps({"evidenceArchive": archive}, indent=2, ensure_ascii=False, default=str))
    else:
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
