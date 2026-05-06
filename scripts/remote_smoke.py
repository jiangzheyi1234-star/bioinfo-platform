#!/usr/bin/env python3
"""Control-plane smoke test for the configured H2OMeta remote server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = "http://127.0.0.1:8765"
MINIMAL_PIPELINE_ID = "file-summary-v1"
FIXED_STALE_PORT = 8876
WINDOWS_CONDA = r"C:\Users\Administrator\miniconda3\Scripts\conda.exe"
CANONICAL_SKILL_REMOTE_SMOKE = "skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py"
CANONICAL_SKILL_REMOTE_PIPELINE = "skills/h2ometa-remote-smoke-test/scripts/remote_pipeline_smoke.py"


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


def unwrap_data(payload: Any) -> Any:
    current = payload
    while isinstance(current, dict) and isinstance(current.get("data"), dict):
        keys = set(current.keys())
        if keys == {"data"}:
            current = current["data"]
            continue
        if keys == {"data", "requestId"}:
            current = current["data"]
            continue
        if keys == {"data", "location", "retryAfter", "requestId"}:
            current = current["data"]
            continue
        break
    return current


def _iter_mappings(payload: Any):
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _iter_mappings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_mappings(value)


def _find_mapping(payload: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    for mapping in _iter_mappings(payload):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, dict):
                return value
    return None


def extract_bootstrap_metadata(payload: Any) -> dict[str, Any]:
    data = unwrap_data(payload)
    metadata = _find_mapping(data, ("bootstrapMetadata", "bootstrap_metadata"))
    return metadata or {}


def _health_phase_report(payload: Any) -> dict[str, str] | None:
    data = unwrap_data(payload)
    health = _find_mapping(data, ("health",))
    if not isinstance(health, dict):
        return None
    ready = health.get("ready")
    if isinstance(ready, dict):
        ok = bool(ready.get("ok"))
        message = str(ready.get("message") or "")
        return {"phase": "readiness", "state": "ok" if ok else "failed", "message": message}
    return None


def _normalize_phase_state(phase: str, payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    ok = payload.get("ok")
    if phase == "rollback":
        restored = payload.get("restored")
        attempted = payload.get("attempted")
        if restored is True or ok is True or status in {"ok", "completed", "restored", "success"}:
            return "ok"
        if attempted is False and not status:
            return "skipped"
        if status in {"skipped", "not_needed", "not-needed"}:
            return "skipped"
        if attempted is True or ok is False or status in {"failed", "error"}:
            return "failed"
        return status or "unknown"
    if ok is True or status in {"ok", "ready", "completed", "passed", "success"}:
        return "ok"
    if ok is False or status in {"failed", "error", "not_ready", "not-ready"}:
        return "failed"
    if status in {"skipped", "not_needed", "not-needed"}:
        return "skipped"
    return status or "unknown"


def extract_bootstrap_phase_reports(payload: Any) -> list[dict[str, str]]:
    reports: list[dict[str, str]] = []
    health_report = _health_phase_report(payload)
    if health_report is not None:
        reports.append(health_report)

    metadata = extract_bootstrap_metadata(payload)
    for phase in ("canary", "rollback"):
        phase_payload = metadata.get(phase)
        if not isinstance(phase_payload, dict):
            continue
        reports.append(
            {
                "phase": phase,
                "state": _normalize_phase_state(phase, phase_payload),
                "message": str(phase_payload.get("message") or ""),
            }
        )
    return reports


def print_bootstrap_phase_report(payload: Any) -> None:
    reports = extract_bootstrap_phase_reports(payload)
    if not reports:
        return
    summary = ", ".join(f"{report['phase']}={report['state']}" for report in reports)
    print(f"BOOTSTRAP_PHASES: {summary}")
    for report in reports:
        if report["message"]:
            print(f"{report['phase'].upper()}_DETAIL: {report['message']}")


def detect_failed_bootstrap_phase(payload: Any) -> str | None:
    for report in extract_bootstrap_phase_reports(payload):
        if report["state"] not in {"ok", "skipped"}:
            return report["phase"]
    return None


def print_failure(summary: str, *, hints: list[str], detail: str | None = None) -> None:
    print(f"ERROR: {summary}")
    if detail:
        print(f"DETAIL: {detail}")
    print("NEXT:")
    for hint in hints:
        print(f"  - {hint}")


def running_in_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    proc_version = Path("/proc/version")
    try:
        return "microsoft" in proc_version.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def _windows_arg(arg: str) -> str:
    if not arg or any(ch.isspace() for ch in arg) or '"' in arg:
        escaped = arg.replace('"', '\\"')
        return f'"{escaped}"'
    return arg


def build_windows_conda_command(script_path: str, argv: list[str]) -> str:
    joined = " ".join(_windows_arg(arg) for arg in argv)
    suffix = f" {joined}" if joined else ""
    return f"{WINDOWS_CONDA} run -n bio_ui python {script_path}{suffix}"


def abort_for_wsl(script_path: str, argv: list[str]) -> None:
    if not running_in_wsl():
        return
    command = build_windows_conda_command(script_path, argv)
    raise SystemExit(
        "ERROR: this smoke must be started from Windows, not from WSL.\n"
        "DETAIL: WSL cannot validate the Windows Local API correctly, and calling "
        "Windows conda.exe from inside WSL is not a supported fallback for this workflow.\n"
        "NEXT:\n"
        "  - Open Windows PowerShell or cmd in E:\\code\\bio_ui.\n"
        f"  - Run `{command}`.\n"
        "  - If you need the web stack first, start `run.bat --web` from the same Windows shell."
    )


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
        raise RuntimeError(
            "failed to import project modules. If this is WSL Python, stop and rerun from "
            "Windows PowerShell or cmd instead of invoking Windows conda.exe from WSL: "
            + build_windows_conda_command(CANONICAL_SKILL_REMOTE_SMOKE, [])
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


def ssh_diagnostics() -> list[str]:
    return [
        "Run `python scripts/print_ssh_config_public.py` to confirm the resolved SSH target.",
        "If the host is reachable but auth fails, verify the configured password ref, key file, or SSH agent state.",
        "After SSH is fixed, rerun `python scripts/remote_smoke.py --bootstrap` before the pipeline smoke.",
    ]


def local_api_diagnostics(api_base: str) -> list[str]:
    return [
        "Start the Windows Local API with `run.bat --web` if it is not already running.",
        f"Verify `{api_base.rstrip('/')}/health` responds before retrying.",
        "If startup still fails, treat that as a Local API problem before debugging the remote runner.",
    ]


def runner_diagnostics(api_base: str, server_id: str | None = None, phase: str | None = None) -> list[str]:
    hints = [
        f"Inspect `{api_base.rstrip('/')}/api/v1/servers` and confirm the expected server is registered.",
        "Run `python scripts/inspect_remote_runner_service.py` to inspect the remote service status and tail the runner log.",
        "Run `python scripts/check_remote_runtime_conda.py` if the runner log suggests workflow-runtime unpack or conda issues.",
    ]
    if server_id:
        hints.insert(1, f"Inspect `{api_base.rstrip('/')}/api/v1/servers/{server_id}/health` for `ready.ok` and bootstrap detail.")
    if phase == "readiness":
        hints.insert(2, "If bootstrap failed in readiness, verify the remote health payload reports `workflowRuntime.ok=true` and that the managed workflow profile assets exist.")
    elif phase == "canary":
        hints.insert(2, "If bootstrap failed in canary, inspect the bootstrap canary run metadata or saved server bootstrap detail for the failed `file-summary-v1` run.")
    elif phase == "rollback":
        hints.insert(2, "If bootstrap failed in rollback, confirm the previous release was restored and compare the saved runner version and deployment action on the server record.")
    return hints


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


def check_local_api(api_base: str, timeout: float, *, bootstrap: bool) -> tuple[bool, dict[str, Any] | None]:
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
        print_failure("local API is not reachable", hints=local_api_diagnostics(api_base))
        return False, None

    items = (((servers_payload or {}).get("data") or {}).get("items") or [])
    if not items:
        print_failure(
            "local API returned no registered servers",
            hints=[
                f"Inspect `{api_base.rstrip('/')}/api/v1/servers` and register the intended remote target first.",
                "Confirm the Local API has loaded the expected server configuration.",
                "Rerun this smoke after the server appears in `/api/v1/servers`.",
            ],
        )
        return False, None

    server = items[0]
    server_id = str(server.get("serverId") or "")
    service_port_raw = server.get("service_port")
    if service_port_raw is None:
        service_port_raw = server.get("servicePort")
    service_port = int(service_port_raw) if service_port_raw not in (None, "") else None
    context = {
        "serverId": server_id,
        "label": server.get("label", ""),
        "connected": server.get("connected", False),
        "ready": server.get("ready", False),
        "service_port": service_port,
        "dynamic_port_expected": None if service_port is None else service_port != FIXED_STALE_PORT,
    }
    print_json("SERVER_SELECTED", context)

    if not server_id:
        print_failure(
            "selected server entry is missing `serverId`",
            hints=[
                f"Inspect `{api_base.rstrip('/')}/api/v1/servers` and repair the saved server record.",
                "Rerun this smoke once the Local API returns a valid `serverId`.",
            ],
        )
        return False, None

    if bootstrap:
        ok, payload = http_json("POST", api_base, f"/api/v1/servers/{server_id}/ensure-runner", timeout=120)
        print_json(f"API POST /api/v1/servers/{server_id}/ensure-runner", {"ok": ok, "payload": payload})
        print_bootstrap_phase_report(payload)
        if not ok:
            failed_phase = detect_failed_bootstrap_phase(payload)
            print_failure(
                "runner bootstrap failed",
                detail=f"POST /api/v1/servers/{server_id}/ensure-runner did not succeed",
                hints=runner_diagnostics(api_base, server_id, phase=failed_phase),
            )
            return False, context

    ok, payload = http_json("GET", api_base, f"/api/v1/servers/{server_id}/health", timeout=timeout)
    print_json(f"API GET /api/v1/servers/{server_id}/health", {"ok": ok, "payload": payload})
    if not ok:
        print_failure(
            "runner health check failed",
            detail=f"GET /api/v1/servers/{server_id}/health did not succeed",
            hints=runner_diagnostics(api_base, server_id),
        )
        return False, context

    ready_ok = bool((((payload or {}).get("data") or {}).get("ready") or {}).get("ok"))
    if not ready_ok:
        print_failure(
            "runner health reported `ready.ok != true`",
            hints=runner_diagnostics(api_base, server_id, phase="readiness"),
        )
        return False, context

    refreshed_ok, refreshed = http_json("GET", api_base, f"/api/v1/servers/{server_id}", timeout=timeout)
    print_json(f"API GET /api/v1/servers/{server_id}", {"ok": refreshed_ok, "payload": refreshed})
    print_bootstrap_phase_report(refreshed)
    if not refreshed_ok:
        print_failure(
            "failed to reload saved server state after health check",
            hints=runner_diagnostics(api_base, server_id),
        )
        return False, context

    data = (refreshed or {}).get("data") or {}
    refreshed_port_raw = data.get("service_port")
    if refreshed_port_raw is None:
        refreshed_port_raw = data.get("servicePort")
    refreshed_port = int(refreshed_port_raw) if refreshed_port_raw not in (None, "") else None
    if refreshed_port == FIXED_STALE_PORT:
        print_failure(
            "runner still reports the stale fixed port 8876 after health check",
            hints=runner_diagnostics(api_base, server_id),
        )
        return False, context

    return True, context


def run_control_plane_smoke(api_base: str, timeout: float, *, bootstrap: bool) -> int:
    phase_label = "bootstrap readiness/canary/rollback + " if bootstrap else ""
    print(f"SMOKE_PATH: control-plane {phase_label}health check for minimal pipeline `{MINIMAL_PIPELINE_ID}`")
    try:
        ssh_ok, ssh_payload = test_ssh()
    except RuntimeError as exc:
        print_failure(str(exc), detail=str(exc.__cause__ or ""), hints=ssh_diagnostics())
        return 1

    if not ssh_ok:
        print_failure("SSH connectivity check failed", detail=str(ssh_payload.get("message") or ""), hints=ssh_diagnostics())
        return 1

    api_ok, _server = check_local_api(api_base, timeout, bootstrap=bootstrap)
    if not api_ok:
        return 1

    print("RESULT: ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Step 1 of the minimal remote smoke path: validate SSH, the Windows Local API, and remote runner "
            f"readiness/bootstrap phases before running `{MINIMAL_PIPELINE_ID}`."
        )
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Local backend API base URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Mutating: call ensure-runner, print readiness/canary/rollback phase summaries when available, then verify steady-state health.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    abort_for_wsl(CANONICAL_SKILL_REMOTE_SMOKE, args_list)
    parser = build_parser()
    args = parser.parse_args(args_list)
    return run_control_plane_smoke(args.api_base, args.timeout, bootstrap=args.bootstrap)


if __name__ == "__main__":
    raise SystemExit(main())
