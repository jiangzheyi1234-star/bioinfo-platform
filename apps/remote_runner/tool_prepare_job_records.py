from __future__ import annotations

import json
from typing import Any


def job_row_to_dict(row: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    request = json.loads(row["request_json"] or "{}")
    result = json.loads(row["result_json"] or "{}") if row["result_json"] else None
    item = {
        "jobId": row["job_id"],
        "status": row["status"],
        "stage": row["stage"],
        "message": row["message"],
        "toolId": row["tool_id"],
        "reservation": {
            "key": row["reservation_key"],
            "packageSpec": row["reservation_package_spec"],
            "validationTarget": row["reservation_validation_target"],
        },
        "lease": {
            "claimedBy": row["claimed_by"],
            "claimedUntil": row["claimed_until"],
            "heartbeatAt": row["heartbeat_at"],
            "attempts": int(row["attempts"] or 0),
            "maxAttempts": int(row["max_attempts"] or 0),
            "nextAttemptAt": row["next_attempt_at"],
            "exhaustedAt": row["exhausted_at"],
        },
        "request": request,
        "result": result,
        "errorCode": row["error_code"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "cancelledAt": row["cancelled_at"],
        "events": events,
    }
    missing_resources = missing_resources_from_events(str(row["status"] or ""), events)
    if missing_resources:
        item["missingResources"] = missing_resources
    if isinstance(result, dict):
        for key in ("validationResultId", "evidenceId"):
            value = str(result.get(key) or "").strip()
            if value:
                item[key] = value
    return item


def event_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "eventId": row["event_id"],
        "stage": row["stage"],
        "level": row["level"],
        "message": row["message"],
        "details": json.loads(row["details_json"] or "{}"),
        "createdAt": row["created_at"],
    }


def missing_resources_from_events(status: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if status != "waiting_resource":
        return []
    for event in reversed(events):
        if event.get("stage") != "waiting_resource":
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        resource = missing_resource_from_details(details)
        return [resource] if resource else []
    return []


def missing_resource_from_details(details: dict[str, Any]) -> dict[str, Any] | None:
    key = str(details.get("key") or details.get("resourceKey") or "").strip()
    if not key:
        return None
    resource: dict[str, Any] = {
        "key": key,
        "resourceType": str(details.get("resourceType") or "database"),
        "configKey": str(details.get("configKey") or key),
        "candidates": _candidate_list(details.get("candidates")),
    }
    accepted_templates = _string_list(details.get("acceptedTemplates"))
    if accepted_templates:
        resource["acceptedTemplates"] = accepted_templates
    accepted_capabilities = _string_list(details.get("acceptedCapabilities"))
    if accepted_capabilities:
        resource["acceptedCapabilities"] = accepted_capabilities
    return resource


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in (str(item).strip() for item in value) if item]
    if isinstance(value, str):
        return [item for item in (part.strip() for part in value.split(",")) if item]
    return []


def _candidate_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    candidates: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id") or "").strip()
        if not candidate_id:
            continue
        candidates.append(
            {
                "id": candidate_id,
                "name": str(item.get("name") or ""),
                "templateId": str(item.get("templateId") or ""),
                "version": str(item.get("version") or ""),
                "status": str(item.get("status") or ""),
            }
        )
    return candidates
