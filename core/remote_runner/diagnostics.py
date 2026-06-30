from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol


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


def build_execution_diagnostics(client: RemoteRunnerDiagnosticClient) -> dict[str, Any]:
    return client.get_json("/health/execution-diagnostics")["data"]


def build_operator_diagnostics_bundle(
    client: RemoteRunnerDiagnosticClient,
    *,
    server_id: str = "",
    run_id: str = "",
    scenario_id: str = "",
    release_tag: str = "",
    source_commit: str = "",
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
    bundle["summary"] = operator_diagnostics_summary(remote_runner)
    bundle["bundleHash"] = _stable_bundle_hash(bundle)
    bundle["bundleId"] = f"opdiag_{bundle['bundleHash'][:16]}"
    return bundle


def operator_diagnostics_summary(remote_runner: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "remoteRunnerReachable": reachable,
        "readinessOk": bool(ready.get("ok")),
        "reasonCodes": reason_codes,
        "endpointStatuses": endpoint_statuses,
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
