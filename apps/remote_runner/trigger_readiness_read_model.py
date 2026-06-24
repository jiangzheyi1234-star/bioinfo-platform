from __future__ import annotations

import hashlib
from typing import Any

from .config import RemoteRunnerConfig
from .trigger_readiness_watcher_storage import fetch_readiness_observation
from .trigger_storage import require_workflow_trigger


READINESS_OBSERVATION_SCHEMA = "workflow-trigger-readiness-observation.v1"


def get_workflow_trigger_readiness_observation_from_storage(
    cfg: RemoteRunnerConfig,
    trigger_id: str,
) -> dict[str, Any]:
    trigger = require_workflow_trigger(cfg, trigger_id)
    observation = fetch_readiness_observation(cfg, trigger_id)
    return {
        "data": {
            "schemaVersion": READINESS_OBSERVATION_SCHEMA,
            "triggerId": trigger["triggerId"],
            "sourceType": trigger["sourceType"],
            "observation": _readiness_observation_for_read(observation) if observation else None,
        }
    }


def _readiness_observation_for_read(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "triggerId": observation["triggerId"],
        "sourceType": observation["sourceType"],
        "resourceType": observation["resourceType"],
        "resourceIdentity": _resource_identity_for_read(observation),
        "watcherAdapter": observation["watcherAdapter"],
        "observationHash": observation["observationHash"],
        "observedVersion": observation["observedVersion"],
        "observedChecksum": observation["observedChecksum"],
        "observedState": observation["observedState"],
        "dispatchState": observation["dispatchState"],
        "triggerEventId": observation["triggerEventId"],
        "runId": observation["runId"],
        "error": _readiness_error_for_read(observation.get("error")),
        "observedAt": observation["observedAt"],
        "createdAt": observation["createdAt"],
        "updatedAt": observation["updatedAt"],
        "resourceUriPresent": bool(str(observation.get("resourceUri") or "").strip()),
    }


def _resource_identity_for_read(observation: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(observation.get("resourceId") or "").strip()
    return {
        "type": str(observation.get("resourceType") or "").strip(),
        "idPresent": bool(resource_id),
        "idLength": len(resource_id),
        **({"idHash": _stable_hash(resource_id)} if resource_id else {}),
    }


def _readiness_error_for_read(error: Any) -> dict[str, str] | None:
    if not isinstance(error, dict) or not error:
        return None
    error_type = str(error.get("errorType") or "").strip()
    message = str(error.get("message") or "").strip()
    reason_code = message.split(":", 1)[0].strip() if message else ""
    return {
        **({"errorType": error_type} if error_type else {}),
        **({"reasonCode": reason_code} if reason_code else {}),
    } or None


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
