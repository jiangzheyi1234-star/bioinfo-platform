from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from typing import Any, Protocol

from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.layout import remote_runner_bootstrap_layout


class RemoteRunnerDiagnosticClient(Protocol):
    def get_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        ...

    def probe_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        ...


OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS = (
    "/health/startup",
    "/health/live",
    "/health/ready",
    "/health/meta",
    "/health/workers",
    "/health/execution-diagnostics",
)
REMOTE_RUNNER_LIFECYCLE_DIAGNOSTICS_SCHEMA = (
    "remote-runner-lifecycle-diagnostics.v1"
)
_SENSITIVE_LOG_PATTERNS = (
    re.compile(
        r"(?i)(authorization|token|password|secret|api[_-]?key)(=|:)\s*[^,\r\n]+"
    ),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
)


def build_execution_diagnostics(client: RemoteRunnerDiagnosticClient) -> dict[str, Any]:
    return client.get_json("/health/execution-diagnostics")["data"]


def build_remote_runner_lifecycle_diagnostics(
    ssh_service,
    *,
    home_dir: str,
    release_tag: str = "",
    log_tail_lines: int = 80,
) -> dict[str, Any]:
    version = str(release_tag or REMOTE_RUNNER_VERSION).strip() or REMOTE_RUNNER_VERSION
    paths = remote_runner_bootstrap_layout(home_dir, version)
    current = _inspect_current_release(ssh_service, paths.current, paths.release)
    artifact = _inspect_artifact_marker(ssh_service, f"{paths.current}/artifact.sha256")
    runtime_state = _inspect_runtime_state(ssh_service, paths.runtime_state)
    systemd = _inspect_systemd_user_service(ssh_service)
    log_tail = _inspect_runner_log_tail(
        ssh_service,
        paths.log,
        line_count=max(1, min(int(log_tail_lines or 80), 200)),
    )
    reason_codes = _lifecycle_reason_codes(current, artifact, runtime_state)
    return {
        "schemaVersion": REMOTE_RUNNER_LIFECYCLE_DIAGNOSTICS_SCHEMA,
        "status": "collected",
        "ok": not reason_codes,
        "reasonCodes": reason_codes,
        "layout": {
            "root": "$HOME/.h2ometa/runner",
            "shared": "$HOME/.h2ometa/runner/shared",
            "pathsRedacted": True,
        },
        "currentRelease": current,
        "artifactMarker": artifact,
        "runtimeState": runtime_state,
        "systemdUserService": systemd,
        "runnerLogTail": log_tail,
        "redactionPolicy": {
            "schemaVersion": "diagnostics-redaction.v1",
            "rawPathsExposed": False,
            "secretsExposed": False,
            "logTailSensitivePatternsRedacted": True,
        },
    }


def build_remote_runner_lifecycle_unavailable(
    *,
    reason_code: str,
    detail: str,
    error_type: str = "",
) -> dict[str, Any]:
    return {
        "schemaVersion": REMOTE_RUNNER_LIFECYCLE_DIAGNOSTICS_SCHEMA,
        "status": "unavailable",
        "ok": False,
        "reasonCodes": [str(reason_code or "RUNNER_LIFECYCLE_DIAGNOSTICS_UNAVAILABLE")],
        "error": {
            "type": str(error_type or ""),
            "message": _truncate(str(detail or "runner lifecycle diagnostics unavailable"), 500),
        },
        "redactionPolicy": {
            "schemaVersion": "diagnostics-redaction.v1",
            "rawPathsExposed": False,
            "secretsExposed": False,
        },
    }


def build_operator_diagnostics_bundle(
    client: RemoteRunnerDiagnosticClient,
    *,
    server_id: str = "",
    run_id: str = "",
    scenario_id: str = "",
    release_tag: str = "",
    source_commit: str = "",
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    remote_runner = {
        endpoint: client.probe_json(endpoint, accepted_statuses={200, 503})
        for endpoint in OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
    }
    collected_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    bundle = {
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
        "remoteRunner": remote_runner,
        "includedSections": ["remoteRunner"],
        "redactionPolicy": {"schemaVersion": "diagnostics-redaction.v1"},
    }
    if lifecycle:
        bundle["remoteLifecycle"] = lifecycle
        bundle["includedSections"].append("remoteLifecycle")
    bundle["summary"] = operator_diagnostics_summary(remote_runner, lifecycle=lifecycle)
    bundle["bundleHash"] = _stable_bundle_hash(bundle)
    bundle["bundleId"] = f"opdiag_{bundle['bundleHash'][:16]}"
    return bundle


def operator_diagnostics_summary(
    remote_runner: dict[str, Any],
    *,
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint_statuses: dict[str, Any] = {}
    reason_codes: list[str] = []
    reachable = False
    for endpoint, payload in sorted(remote_runner.items()):
        status = _operator_endpoint_status(payload)
        endpoint_statuses[endpoint.strip("/").split("/")[-1].replace("-", "_")] = (
            status
        )
        reachable = reachable or status.get("httpStatus") is not None
        reason_code = str(status.get("reasonCode") or "").strip()
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
    if not reachable and "RUNNER_UNREACHABLE" not in reason_codes:
        reason_codes.append("RUNNER_UNREACHABLE")
    ready = endpoint_statuses.get("ready") or {}
    lifecycle_reason_codes = []
    if isinstance(lifecycle, dict):
        for code in lifecycle.get("reasonCodes") or []:
            normalized = str(code or "").strip()
            if normalized:
                lifecycle_reason_codes.append(normalized)
                if normalized not in reason_codes:
                    reason_codes.append(normalized)
    return {
        "remoteRunnerReachable": reachable,
        "readinessOk": bool(ready.get("ok")),
        "reasonCodes": reason_codes,
        "endpointStatuses": endpoint_statuses,
        "lifecycleDiagnosticsOk": (
            bool(lifecycle.get("ok")) if isinstance(lifecycle, dict) else None
        ),
        "lifecycleReasonCodes": lifecycle_reason_codes,
    }


def _inspect_current_release(
    ssh_service,
    current_path: str,
    expected_release_path: str,
) -> dict[str, Any]:
    probe = _run_remote_probe(
        ssh_service,
        "if [ -e {path} ] || [ -L {path} ]; then readlink -f {path}; else exit 44; fi".format(
            path=shlex.quote(current_path),
        ),
    )
    target = probe["stdout"].strip().splitlines()[0] if probe["exitCode"] == 0 and probe["stdout"].strip() else ""
    target_release = _path_basename(target)
    expected_release = _path_basename(expected_release_path)
    return {
        "exists": probe["exitCode"] == 0 and bool(target_release),
        "targetRelease": target_release,
        "targetPathSha256": _sha256_text(target) if target else "",
        "expectedRelease": expected_release,
        "matchesExpectedRelease": bool(expected_release and target_release == expected_release),
        "probe": _probe_public(probe),
    }


def _inspect_artifact_marker(ssh_service, marker_path: str) -> dict[str, Any]:
    probe = _run_remote_probe(
        ssh_service,
        "if [ -f {path} ]; then head -c 256 {path}; else exit 44; fi".format(
            path=shlex.quote(marker_path),
        ),
    )
    marker = probe["stdout"].strip().splitlines()[0] if probe["exitCode"] == 0 else ""
    return {
        "present": bool(marker),
        "sha256": marker if _looks_like_sha256(marker) else "",
        "valueSha256": _sha256_text(marker) if marker else "",
        "probe": _probe_public(probe),
    }


def _inspect_runtime_state(ssh_service, runtime_state_path: str) -> dict[str, Any]:
    probe = _run_remote_probe(
        ssh_service,
        "if [ -f {path} ]; then cat {path}; else exit 44; fi".format(
            path=shlex.quote(runtime_state_path),
        ),
    )
    if probe["exitCode"] != 0:
        return {"present": False, "valid": False, "probe": _probe_public(probe)}
    try:
        payload = json.loads(probe["stdout"])
    except json.JSONDecodeError:
        return {"present": True, "valid": False, "probe": _probe_public(probe)}
    if not isinstance(payload, dict):
        return {"present": True, "valid": False, "probe": _probe_public(probe)}
    return {
        "present": True,
        "valid": True,
        "service": str(payload.get("service") or ""),
        "version": str(payload.get("version") or ""),
        "pid": _safe_int(payload.get("pid")),
        "bindHost": str(payload.get("bindHost") or ""),
        "bindPort": _safe_int(payload.get("bindPort")),
        "startedAt": str(payload.get("startedAt") or ""),
        "probe": _probe_public(probe),
    }


def _inspect_systemd_user_service(ssh_service) -> dict[str, Any]:
    command = (
        "if command -v systemctl >/dev/null 2>&1 "
        "&& systemctl --user show-environment >/dev/null 2>&1; then "
        "systemctl --user show h2ometa-remote.service "
        "--property=LoadState,ActiveState,SubState,UnitFileState,NeedDaemonReload "
        "--no-pager; else echo SYSTEMD_USER_UNAVAILABLE; fi"
    )
    probe = _run_remote_probe(ssh_service, command)
    properties = _parse_key_value_lines(probe["stdout"])
    available = "SYSTEMD_USER_UNAVAILABLE" not in probe["stdout"]
    return {
        "available": available and probe["exitCode"] == 0,
        "properties": properties if available else {},
        "probe": _probe_public(probe),
    }


def _inspect_runner_log_tail(
    ssh_service,
    log_path: str,
    *,
    line_count: int,
) -> dict[str, Any]:
    probe = _run_remote_probe(
        ssh_service,
        "if [ -f {path} ]; then tail -n {line_count} {path}; else exit 44; fi".format(
            path=shlex.quote(log_path),
            line_count=int(line_count),
        ),
    )
    lines = []
    if probe["exitCode"] == 0:
        lines = [_redact_log_line(line) for line in probe["stdout"].splitlines()]
    return {
        "available": probe["exitCode"] == 0,
        "lineCount": len(lines),
        "tail": lines[-line_count:],
        "probe": _probe_public(probe),
    }


def _lifecycle_reason_codes(
    current: dict[str, Any],
    artifact: dict[str, Any],
    runtime_state: dict[str, Any],
) -> list[str]:
    reason_codes = []
    if not current.get("exists"):
        reason_codes.append("RUNNER_CURRENT_RELEASE_MISSING")
    if not artifact.get("present"):
        reason_codes.append("RUNNER_ARTIFACT_MARKER_MISSING")
    if not runtime_state.get("present"):
        reason_codes.append("RUNNER_RUNTIME_STATE_MISSING")
    elif not runtime_state.get("valid"):
        reason_codes.append("RUNNER_RUNTIME_STATE_INVALID")
    return reason_codes


def _run_remote_probe(ssh_service, command: str, *, timeout: int = 10) -> dict[str, Any]:
    try:
        exit_code, stdout, stderr = ssh_service.run(command, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - diagnostics must report probe errors.
        return {
            "exitCode": -1,
            "stdout": "",
            "stderr": str(exc),
            "errorType": type(exc).__name__,
        }
    return {
        "exitCode": int(exit_code),
        "stdout": str(stdout or ""),
        "stderr": str(stderr or ""),
        "errorType": "",
    }


def _probe_public(probe: dict[str, Any]) -> dict[str, Any]:
    stderr = _redact_log_line(str(probe.get("stderr") or ""))
    return {
        "exitCode": int(probe.get("exitCode") or 0),
        "stderr": _truncate(stderr, 500),
        "errorType": str(probe.get("errorType") or ""),
    }


def _operator_endpoint_status(payload: Any) -> dict[str, Any]:
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
        "ok": _operator_status_ok(body=body, data=data, status=status),
        "status": str(status or ""),
        "reasonCode": str(reason_code or ""),
        "error": dict(error),
    }


def _operator_status_ok(
    *, body: dict[str, Any], data: dict[str, Any], status: Any
) -> bool:
    if "ok" in body:
        return bool(body.get("ok"))
    if "ok" in data:
        return bool(data.get("ok"))
    return str(status or "").lower() == "ok"


def _parse_key_value_lines(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in str(raw or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _truncate(_redact_log_line(value.strip()), 200)
    return values


def _redact_log_line(line: str) -> str:
    redacted = str(line or "")
    for pattern in _SENSITIVE_LOG_PATTERNS:
        redacted = pattern.sub(_redacted_match, redacted)
    return _truncate(redacted, 500)


def _redacted_match(match: re.Match[str]) -> str:
    if len(match.groups()) >= 2:
        return f"{match.group(1)}{match.group(2)}***REDACTED***"
    return "Bearer ***REDACTED***"


def _path_basename(path: str) -> str:
    normalized = str(path or "").strip().rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _looks_like_sha256(value: str) -> bool:
    text = str(value or "").strip()
    return len(text) == 64 and all(char in "0123456789abcdefABCDEF" for char in text)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _stable_bundle_hash(bundle: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in bundle.items()
        if key not in {"bundleHash", "bundleId"}
    }
    payload = json.dumps(
        comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
