from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from .api_models import WorkflowTriggerReadinessEventRequest
from .config import RemoteRunnerConfig, load_remote_runner_config
from .storage_core import now_iso
from .trigger_readiness_watcher_storage import fetch_readiness_observation, upsert_readiness_observation
from .trigger_service import READINESS_RESOURCE_TYPES_BY_SOURCE, READINESS_TRIGGER_SOURCES
from .trigger_service import submit_workflow_trigger_readiness_event_from_request
from .trigger_storage import list_workflow_triggers_by_source


LOGGER = logging.getLogger(__name__)
DEFAULT_READINESS_WATCHER_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_READINESS_WATCHER_LIMIT = 100
READINESS_WATCHER_ACTOR = "workflow-trigger-readiness-watcher"


class WorkflowTriggerReadinessWatcherSupervisor:
    def __init__(
        self,
        cfg: RemoteRunnerConfig,
        *,
        poll_interval_seconds: float = DEFAULT_READINESS_WATCHER_POLL_INTERVAL_SECONDS,
        limit: int = DEFAULT_READINESS_WATCHER_LIMIT,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_POLL_INTERVAL_INVALID")
        if limit <= 0:
            raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_LIMIT_INVALID")
        self._cfg = cfg
        self._poll_interval_seconds = poll_interval_seconds
        self._limit = limit
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="h2ometa-workflow-trigger-readiness-watcher",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = run_workflow_trigger_readiness_watcher_once(self._cfg, limit=self._limit)
                if result["errors"]:
                    LOGGER.warning("Workflow trigger readiness watcher completed with errors: %s", result["errors"])
            except Exception:  # noqa: BLE001 - watcher must keep polling after transient storage/runtime errors.
                LOGGER.exception("Workflow trigger readiness watcher loop failed.")
            self._stop_event.wait(self._poll_interval_seconds)


def run_workflow_trigger_readiness_watcher_once(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = DEFAULT_READINESS_WATCHER_LIMIT,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_LIMIT_INVALID")
    checked = 0
    skipped = 0
    missing = 0
    ready = 0
    submitted = 0
    unchanged = 0
    observations: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for trigger in _enabled_readiness_triggers(cfg):
        if checked >= limit:
            skipped += 1
            continue
        checked += 1
        try:
            plan = _watch_plan(trigger)
            if plan is None:
                skipped += 1
                continue
            observation = _observe_watch_plan(plan)
            if observation["state"] == "missing":
                missing += 1
                observations.append(_record_observation(cfg, trigger=trigger, plan=plan, observation=observation))
                continue
            previous = fetch_readiness_observation(cfg, str(trigger["triggerId"]))
            if _already_dispatched(previous, observation):
                unchanged += 1
                observations.append(previous)
                continue
            response = submit_workflow_trigger_readiness_event_from_request(
                cfg,
                str(trigger["triggerId"]),
                _readiness_request(trigger, plan=plan, observation=observation),
            )
            ready += 1
            submitted += 0 if response["data"].get("replayed") else 1
            observations.append(
                _record_observation(
                    cfg,
                    trigger=trigger,
                    plan=plan,
                    observation=observation,
                    dispatch=response["data"],
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad watcher config must not block other triggers.
            errors.append(_trigger_error(trigger, exc))
            try:
                observations.append(_record_error(cfg, trigger=trigger, exc=exc))
            except Exception:  # noqa: BLE001 - error persistence is best effort for malformed legacy rows.
                LOGGER.exception("Failed to record workflow trigger readiness watcher error.")

    return {
        "schemaVersion": "workflow-trigger-readiness-watcher-tick.v1",
        "checked": checked,
        "skipped": skipped,
        "missing": missing,
        "ready": ready,
        "submitted": submitted,
        "unchanged": unchanged,
        "observations": observations,
        "errors": errors,
        "evaluatedAt": now_iso(),
    }


def start_workflow_trigger_readiness_watcher_supervisor(
    cfg: RemoteRunnerConfig,
    *,
    poll_interval_seconds: float = DEFAULT_READINESS_WATCHER_POLL_INTERVAL_SECONDS,
    limit: int = DEFAULT_READINESS_WATCHER_LIMIT,
) -> WorkflowTriggerReadinessWatcherSupervisor:
    supervisor = WorkflowTriggerReadinessWatcherSupervisor(
        cfg,
        poll_interval_seconds=poll_interval_seconds,
        limit=limit,
    )
    supervisor.start()
    return supervisor


def start_configured_workflow_trigger_readiness_watcher_supervisor() -> (
    WorkflowTriggerReadinessWatcherSupervisor | None
):
    cfg = load_remote_runner_config()
    if not cfg.token or not _readiness_watcher_enabled():
        return None
    return start_workflow_trigger_readiness_watcher_supervisor(
        cfg,
        poll_interval_seconds=_configured_poll_interval_seconds(),
        limit=_configured_limit(),
    )


def _enabled_readiness_triggers(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    triggers: list[dict[str, Any]] = []
    for source_type in sorted(READINESS_TRIGGER_SOURCES):
        triggers.extend(list_workflow_triggers_by_source(cfg, source_type, enabled_only=True)["items"])
    return sorted(triggers, key=lambda item: str(item.get("updatedAt") or ""))


def _watch_plan(trigger: dict[str, Any]) -> dict[str, Any] | None:
    source_type = str(trigger.get("sourceType") or "")
    resource_type = READINESS_RESOURCE_TYPES_BY_SOURCE.get(source_type)
    if resource_type is None:
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_SOURCE_MISMATCH: {source_type}")
    trigger_spec = trigger.get("triggerSpec") if isinstance(trigger.get("triggerSpec"), dict) else {}
    resource = trigger_spec.get("resource") if isinstance(trigger_spec.get("resource"), dict) else None
    if not isinstance(resource, dict):
        raise ValueError("WORKFLOW_TRIGGER_READINESS_RESOURCE_SPEC_REQUIRED")
    if str(resource.get("type") or "").strip() != resource_type:
        raise ValueError("WORKFLOW_TRIGGER_READINESS_TRIGGER_RESOURCE_TYPE_MISMATCH")
    watch = resource.get("watch") if isinstance(resource.get("watch"), dict) else {}
    if not _watch_enabled(watch):
        return None
    adapter = str(watch.get("adapter") or "").strip()
    if adapter != "local_path":
        raise ValueError(f"WORKFLOW_TRIGGER_READINESS_WATCHER_ADAPTER_UNSUPPORTED: {adapter or '<missing>'}")
    resource_id = _required_text(resource.get("id"), "WORKFLOW_TRIGGER_READINESS_RESOURCE_ID_REQUIRED")
    resource_uri = str(resource.get("uri") or "").strip()
    return {
        "adapter": adapter,
        "sourceType": source_type,
        "resourceType": resource_type,
        "resourceId": resource_id,
        "resourceUri": resource_uri,
        "path": _watch_path(watch, resource_uri),
        "labels": _safe_labels(watch.get("labels") if isinstance(watch.get("labels"), dict) else {}),
    }


def _observe_watch_plan(plan: dict[str, Any]) -> dict[str, Any]:
    path = Path(plan["path"]).expanduser()
    observed_at = now_iso()
    if not path.exists():
        return {
            "state": "missing",
            "version": "",
            "checksum": "",
            "hash": _stable_hash({"state": "missing", "pathHash": _stable_hash(str(path))}),
            "observedAt": observed_at,
            "safeDetails": {"pathHash": _stable_hash(str(path)), "exists": False},
        }
    stats = _path_stats(path)
    observation_hash = _stable_hash(
        {
            "state": "ready",
            "resourceType": plan["resourceType"],
            "resourceId": plan["resourceId"],
            "checksum": stats["checksum"],
            "sizeBytes": stats["sizeBytes"],
            "fileCount": stats["fileCount"],
        }
    )
    return {
        "state": "ready",
        "version": f"sha256:{observation_hash}",
        "checksum": f"sha256:{stats['checksum']}",
        "hash": observation_hash,
        "observedAt": observed_at,
        "safeDetails": {
            "pathHash": _stable_hash(str(path)),
            "kind": stats["kind"],
            "sizeBytes": stats["sizeBytes"],
            "fileCount": stats["fileCount"],
        },
    }


def _readiness_request(
    trigger: dict[str, Any],
    *,
    plan: dict[str, Any],
    observation: dict[str, Any],
) -> WorkflowTriggerReadinessEventRequest:
    event_id = f"watch:{trigger['triggerId']}:{observation['hash'][:16]}"
    return WorkflowTriggerReadinessEventRequest(
        source=READINESS_WATCHER_ACTOR,
        eventId=event_id,
        resourceType=plan["resourceType"],
        resourceId=plan["resourceId"],
        uri=plan["resourceUri"] or None,
        version=observation["version"],
        checksum=observation["checksum"],
        observedAt=observation["observedAt"],
        actor=READINESS_WATCHER_ACTOR,
        labels={"watcher": plan["adapter"], **plan["labels"]},
        payload={"watcher": {"adapter": plan["adapter"], **observation["safeDetails"]}},
    )


def _record_observation(
    cfg: RemoteRunnerConfig,
    *,
    trigger: dict[str, Any],
    plan: dict[str, Any],
    observation: dict[str, Any],
    dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = dispatch.get("event") if isinstance((dispatch or {}).get("event"), dict) else {}
    run = dispatch.get("run") if isinstance((dispatch or {}).get("run"), dict) else {}
    event_dispatch = event.get("dispatch") if isinstance(event.get("dispatch"), dict) else {}
    return upsert_readiness_observation(
        cfg,
        trigger_id=str(trigger["triggerId"]),
        source_type=plan["sourceType"],
        resource_type=plan["resourceType"],
        resource_id=plan["resourceId"],
        resource_uri=plan["resourceUri"],
        watcher_adapter=plan["adapter"],
        observation_hash=observation["hash"],
        observed_version=observation["version"],
        observed_checksum=observation["checksum"],
        observed_state=observation["state"],
        dispatch_state=str(event_dispatch.get("state") or ""),
        trigger_event_id=str(event.get("triggerEventId") or "") or None,
        run_id=str(run.get("runId") or event_dispatch.get("runId") or "") or None,
        observed_at=observation["observedAt"],
    )


def _record_error(cfg: RemoteRunnerConfig, *, trigger: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    source_type = str(trigger.get("sourceType") or "")
    resource_type = READINESS_RESOURCE_TYPES_BY_SOURCE.get(source_type, "")
    trigger_spec = trigger.get("triggerSpec") if isinstance(trigger.get("triggerSpec"), dict) else {}
    resource = trigger_spec.get("resource") if isinstance(trigger_spec.get("resource"), dict) else {}
    timestamp = now_iso()
    return upsert_readiness_observation(
        cfg,
        trigger_id=str(trigger.get("triggerId") or ""),
        source_type=source_type,
        resource_type=resource_type,
        resource_id=str(resource.get("id") or ""),
        resource_uri=str(resource.get("uri") or ""),
        watcher_adapter="",
        observation_hash="",
        observed_version="",
        observed_checksum="",
        observed_state="error",
        error={"errorType": exc.__class__.__name__, "message": str(exc)},
        observed_at=timestamp,
    )


def _already_dispatched(previous: dict[str, Any] | None, observation: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return (
        previous["observationHash"] == observation["hash"]
        and previous["observedState"] == "ready"
        and previous["dispatchState"] == "submitted"
        and bool(previous.get("triggerEventId"))
    )


def _path_stats(path: Path) -> dict[str, Any]:
    if path.is_file():
        size, checksum = _file_stats(path)
        return {"kind": "file", "sizeBytes": size, "fileCount": 1, "checksum": checksum}
    if path.is_dir():
        digest = hashlib.sha256()
        total_size = 0
        file_count = 0
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = child.relative_to(path).as_posix()
            size, checksum = _file_stats(child)
            digest.update(relative.encode("utf-8"))
            digest.update(str(size).encode("utf-8"))
            digest.update(checksum.encode("utf-8"))
            total_size += size
            file_count += 1
        return {"kind": "directory", "sizeBytes": total_size, "fileCount": file_count, "checksum": digest.hexdigest()}
    raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_PATH_UNSUPPORTED")


def _file_stats(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _watch_path(watch: dict[str, Any], resource_uri: str) -> str:
    raw_path = str(watch.get("path") or "").strip()
    if raw_path:
        return raw_path
    if resource_uri.startswith("file://"):
        return str(_path_from_file_uri(resource_uri))
    raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_PATH_REQUIRED")


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_FILE_URI_REQUIRED")
    path = unquote(parsed.path or "")
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)


def _watch_enabled(watch: dict[str, Any]) -> bool:
    value = str(watch.get("enabled") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _safe_labels(labels: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in labels.items()
        if str(key).strip() and str(value).strip() and not _is_secret_like(str(key))
    }


def _is_secret_like(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("secret", "token", "password", "authorization", "private_key"))


def _trigger_error(trigger: dict[str, Any], exc: BaseException) -> dict[str, str]:
    return {
        "triggerId": str(trigger.get("triggerId") or ""),
        "sourceType": str(trigger.get("sourceType") or ""),
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _readiness_watcher_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_TRIGGER_READINESS_WATCHER", "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _configured_poll_interval_seconds() -> float:
    raw = str(os.environ.get("H2OMETA_TRIGGER_READINESS_WATCHER_POLL_SECONDS", "") or "").strip()
    if not raw:
        return DEFAULT_READINESS_WATCHER_POLL_INTERVAL_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_POLL_INTERVAL_INVALID")
    return value


def _configured_limit() -> int:
    raw = str(os.environ.get("H2OMETA_TRIGGER_READINESS_WATCHER_LIMIT", "") or "").strip()
    if not raw:
        return DEFAULT_READINESS_WATCHER_LIMIT
    value = int(raw)
    if value <= 0:
        raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_LIMIT_INVALID")
    return value
