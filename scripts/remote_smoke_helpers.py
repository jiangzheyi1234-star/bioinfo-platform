"""Pure payload helpers for the remote smoke scripts."""

from __future__ import annotations

from typing import Any, Iterable


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


def _iter_mappings(payload: Any) -> Iterable[dict[str, Any]]:
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
    return metadata if metadata is not None else {}


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


def response_data_mapping(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{label} data must be an object")
    return data


def server_items_from_payload(payload: Any) -> list[dict[str, Any]]:
    data = response_data_mapping(payload, "servers response")
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("servers response data.items must be a list")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("servers response data.items entries must be objects")
    return items


def service_port_from_server(server: dict[str, Any]) -> int | None:
    service_port_raw = server.get("service_port")
    if service_port_raw is None:
        service_port_raw = server.get("servicePort")
    return int(service_port_raw) if service_port_raw not in (None, "") else None


def server_context(server: dict[str, Any], *, stale_port: int) -> dict[str, Any]:
    service_port = service_port_from_server(server)
    return {
        "serverId": str(server.get("serverId") or ""),
        "label": server.get("label", ""),
        "connected": server.get("connected", False),
        "ready": server.get("ready", False),
        "service_port": service_port,
        "dynamic_port_expected": None if service_port is None else service_port != stale_port,
    }


def ready_ok_from_health_payload(payload: Any) -> bool:
    data = response_data_mapping(payload, "server health")
    ready = data.get("ready")
    if not isinstance(ready, dict):
        raise ValueError("server health ready must be an object")
    return bool(ready.get("ok"))
