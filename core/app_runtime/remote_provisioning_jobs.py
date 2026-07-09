from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from core.app_runtime import runtime_config
from core.app_runtime.errors import RuntimeServiceError

REMOTE_PROVISIONING_CONFIG_KEY = "remote_provisioning_jobs"
REMOTE_PROVISIONING_ACTIVE_STATUSES = ("queued", "running")
REMOTE_PROVISIONING_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
REMOTE_PROVISIONING_ACTIONS = ("ensure-runner", "start-runner", "upgrade-runner", "repair-runner")

_MAX_RETAINED_JOBS = 50
_jobs_lock = threading.RLock()


class RemoteProvisioningOperationsMixin:
    def create_remote_provisioning_job(
        self,
        server_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = _normalize_action((payload or {}).get("action"))
        normalized_server_id = str(server_id or "").strip()
        if not normalized_server_id:
            raise RuntimeServiceError(
                "Server id is required",
                status_code=400,
                detail={"reasonCode": "REMOTE_PROVISIONING_SERVER_REQUIRED"},
            )

        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != normalized_server_id:
                raise RuntimeServiceError(f"Server not found: {normalized_server_id}", status_code=404)
            if not bool(server.get("connected")):
                raise RuntimeServiceError(
                    "SSH is not connected",
                    status_code=409,
                    detail={
                        "reasonCode": "REMOTE_PROVISIONING_REQUIRES_SSH",
                        "serverId": normalized_server_id,
                        "nextAction": "CONNECT_SSH",
                    },
                )
            record = self._get_server_registry_entry(normalized_server_id)
            if action == "upgrade-runner" and not record.get("bootstrap_version"):
                raise RuntimeServiceError(
                    "Remote runner is not prepared; start it before upgrade.",
                    status_code=409,
                    detail={
                        "reasonCode": "RUNNER_UPGRADE_NOT_PREPARED",
                        "serverId": normalized_server_id,
                        "nextAction": "START_RUNNER_BEFORE_UPGRADE",
                    },
                )

        job = _create_remote_provisioning_job_record(
            server_id=normalized_server_id,
            action=action,
            display_target=str(server.get("displayTarget") or server.get("host") or ""),
        )
        with self._lock:
            self._save_server_registry_entry(
                normalized_server_id,
                {
                    "last_provisioning_job_id": job["jobId"],
                    "last_provisioning_action": action,
                    "last_provisioning_job_status": job["status"],
                    "last_provisioning_job_updated_at": job["updatedAt"],
                },
            )
        worker = threading.Thread(
            target=self._run_remote_provisioning_job,
            args=(job["jobId"],),
            daemon=True,
            name=f"h2ometa-remote-provisioning-{job['jobId'][:8]}",
        )
        with self._lock:
            threads = getattr(self, "_remote_provisioning_threads", None)
            if isinstance(threads, dict):
                threads[job["jobId"]] = worker
        worker.start()
        return {"data": job}

    def list_remote_provisioning_job_queue(
        self,
        *,
        status: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        return {
            "data": _list_remote_provisioning_job_queue(
                status=status,
                limit=limit,
                offset=offset,
            )
        }

    def get_remote_provisioning_job(self, job_id: str) -> dict[str, Any]:
        return {"data": _require_remote_provisioning_job(job_id)}

    def cancel_remote_provisioning_job(self, job_id: str) -> dict[str, Any]:
        return {"data": _cancel_remote_provisioning_job(job_id)}

    def _run_remote_provisioning_job(self, job_id: str) -> None:
        try:
            job = _start_remote_provisioning_job(job_id)
            if job is None:
                return
            action = str(job.get("action") or "ensure-runner")
            server_id = str(job.get("serverId") or "")
            result = self._execute_remote_provisioning_action(action=action, server_id=server_id)
            finished = _finish_remote_provisioning_job(
                job_id,
                status="succeeded",
                stage="ready",
                message=_success_message(action),
                result=_summarize_runner_result(result),
            )
            self._save_remote_provisioning_profile_state(finished)
        except RuntimeServiceError as exc:
            finished = _finish_remote_provisioning_job(
                job_id,
                status="failed",
                stage="failed",
                message=str(exc),
                error_code=_runtime_error_reason_code(exc) or "REMOTE_PROVISIONING_FAILED",
                result=None,
            )
            self._save_remote_provisioning_profile_state(finished)
        except Exception as exc:  # pragma: no cover - defensive boundary for background threads
            finished = _finish_remote_provisioning_job(
                job_id,
                status="failed",
                stage="failed",
                message=str(exc) or exc.__class__.__name__,
                error_code="REMOTE_PROVISIONING_UNEXPECTED_ERROR",
                result=None,
            )
            self._save_remote_provisioning_profile_state(finished)
        finally:
            with self._lock:
                threads = getattr(self, "_remote_provisioning_threads", None)
                if isinstance(threads, dict):
                    threads.pop(job_id, None)

    def _execute_remote_provisioning_action(self, *, action: str, server_id: str) -> dict[str, Any]:
        if action == "ensure-runner":
            return self.ensure_remote_runner_ready(server_id)
        if action == "start-runner":
            return self.start_remote_runner(server_id)
        if action == "upgrade-runner":
            return self.upgrade_remote_runner(server_id)
        if action == "repair-runner":
            return self.repair_remote_runner_diagnostics(server_id)
        raise RuntimeServiceError(
            f"Unsupported remote provisioning action: {action}",
            status_code=400,
            detail={"reasonCode": "REMOTE_PROVISIONING_UNSUPPORTED_ACTION", "action": action},
        )

    def _save_remote_provisioning_profile_state(self, job: dict[str, Any] | None) -> None:
        if not isinstance(job, dict):
            return
        server_id = str(job.get("serverId") or "").strip()
        if not server_id:
            return
        with self._lock:
            self._save_server_registry_entry(
                server_id,
                {
                    "last_provisioning_job_id": str(job.get("jobId") or ""),
                    "last_provisioning_action": str(job.get("action") or ""),
                    "last_provisioning_job_status": str(job.get("status") or ""),
                    "last_provisioning_job_updated_at": str(job.get("updatedAt") or ""),
                },
            )


def _normalize_action(value: Any) -> str:
    action = str(value or "ensure-runner").strip()
    if action in REMOTE_PROVISIONING_ACTIONS:
        return action
    raise RuntimeServiceError(
        f"Unsupported remote provisioning action: {action}",
        status_code=400,
        detail={
            "reasonCode": "REMOTE_PROVISIONING_UNSUPPORTED_ACTION",
            "action": action,
            "supportedActions": list(REMOTE_PROVISIONING_ACTIONS),
        },
    )


def _create_remote_provisioning_job_record(
    *,
    server_id: str,
    action: str,
    display_target: str = "",
) -> dict[str, Any]:
    now = _now_iso()
    job = {
        "jobId": f"remote-provisioning-{uuid.uuid4().hex}",
        "serverId": server_id,
        "displayTarget": display_target,
        "action": action,
        "status": "queued",
        "stage": "queued",
        "message": _queued_message(action),
        "createdAt": now,
        "updatedAt": now,
        "startedAt": None,
        "finishedAt": None,
        "cancelledAt": None,
        "errorCode": None,
        "result": None,
        "events": [
            _job_event(
                stage="queued",
                level="info",
                message=_queued_message(action),
                created_at=now,
            )
        ],
    }
    with _jobs_lock:
        jobs = _load_jobs()
        _save_jobs([job, *jobs])
    return job


def _list_remote_provisioning_job_queue(
    *,
    status: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_status = str(status or "").strip()
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    with _jobs_lock:
        all_jobs = _load_jobs()
    filtered = [job for job in all_jobs if not normalized_status or job.get("status") == normalized_status]
    status_counts = _status_counts(all_jobs)
    return {
        "items": filtered[safe_offset : safe_offset + safe_limit],
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "status": normalized_status,
        "statusCounts": status_counts,
        "activeCount": sum(status_counts.get(status, 0) for status in REMOTE_PROVISIONING_ACTIVE_STATUSES),
        "queuedCount": status_counts.get("queued", 0),
        "runningCount": status_counts.get("running", 0),
        "activeStatuses": list(REMOTE_PROVISIONING_ACTIVE_STATUSES),
        "terminalStatuses": list(REMOTE_PROVISIONING_TERMINAL_STATUSES),
    }


def _require_remote_provisioning_job(job_id: str) -> dict[str, Any]:
    normalized_job_id = str(job_id or "").strip()
    with _jobs_lock:
        for job in _load_jobs():
            if job.get("jobId") == normalized_job_id:
                return job
    raise RuntimeServiceError(
        f"Remote provisioning job not found: {normalized_job_id}",
        status_code=404,
        detail={"reasonCode": "REMOTE_PROVISIONING_JOB_NOT_FOUND", "jobId": normalized_job_id},
    )


def _cancel_remote_provisioning_job(job_id: str) -> dict[str, Any]:
    now = _now_iso()
    normalized_job_id = str(job_id or "").strip()
    with _jobs_lock:
        jobs = _load_jobs()
        for index, job in enumerate(jobs):
            if job.get("jobId") != normalized_job_id:
                continue
            status = str(job.get("status") or "")
            if status in REMOTE_PROVISIONING_TERMINAL_STATUSES:
                return job
            if status == "running":
                raise RuntimeServiceError(
                    "Running remote provisioning jobs cannot be cancelled safely.",
                    status_code=409,
                    detail={
                        "reasonCode": "REMOTE_PROVISIONING_RUNNING_CANCEL_UNSUPPORTED",
                        "jobId": normalized_job_id,
                    },
                )
            updated = {
                **job,
                "status": "cancelled",
                "stage": "cancelled",
                "message": "Remote provisioning job was cancelled before it started.",
                "updatedAt": now,
                "finishedAt": now,
                "cancelledAt": now,
                "events": [
                    *_safe_events(job),
                    _job_event(
                        stage="cancelled",
                        level="warning",
                        message="Remote provisioning job was cancelled before it started.",
                        created_at=now,
                    ),
                ],
            }
            jobs[index] = updated
            _save_jobs(jobs)
            return updated
    raise RuntimeServiceError(
        f"Remote provisioning job not found: {normalized_job_id}",
        status_code=404,
        detail={"reasonCode": "REMOTE_PROVISIONING_JOB_NOT_FOUND", "jobId": normalized_job_id},
    )


def _start_remote_provisioning_job(job_id: str) -> dict[str, Any] | None:
    now = _now_iso()
    with _jobs_lock:
        jobs = _load_jobs()
        for index, job in enumerate(jobs):
            if job.get("jobId") != job_id:
                continue
            if job.get("status") == "cancelled":
                return None
            if job.get("status") != "queued":
                return job
            updated = {
                **job,
                "status": "running",
                "stage": _running_stage(str(job.get("action") or "")),
                "message": _running_message(str(job.get("action") or "")),
                "updatedAt": now,
                "startedAt": now,
                "events": [
                    *_safe_events(job),
                    _job_event(
                        stage=_running_stage(str(job.get("action") or "")),
                        level="info",
                        message=_running_message(str(job.get("action") or "")),
                        created_at=now,
                    ),
                ],
            }
            jobs[index] = updated
            _save_jobs(jobs)
            return updated
    return None


def _finish_remote_provisioning_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    message: str,
    error_code: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    now = _now_iso()
    level = "success" if status == "succeeded" else "error"
    with _jobs_lock:
        jobs = _load_jobs()
        for index, job in enumerate(jobs):
            if job.get("jobId") != job_id:
                continue
            updated = {
                **job,
                "status": status,
                "stage": stage,
                "message": message,
                "updatedAt": now,
                "finishedAt": now,
                "errorCode": error_code,
                "result": result,
                "events": [
                    *_safe_events(job),
                    _job_event(stage=stage, level=level, message=message, created_at=now),
                ],
            }
            jobs[index] = updated
            _save_jobs(jobs)
            return updated
    return None


def _load_jobs() -> list[dict[str, Any]]:
    config = runtime_config.get_runtime_config()
    raw_jobs = config.get(REMOTE_PROVISIONING_CONFIG_KEY)
    if not isinstance(raw_jobs, list):
        return []
    jobs = [_sanitize_job(job) for job in raw_jobs if isinstance(job, dict)]
    return sorted(jobs, key=lambda job: str(job.get("updatedAt") or ""), reverse=True)


def _save_jobs(jobs: list[dict[str, Any]]) -> None:
    config = runtime_config.get_runtime_config()
    config[REMOTE_PROVISIONING_CONFIG_KEY] = jobs[:_MAX_RETAINED_JOBS]
    runtime_config.save_runtime_config(config)


def _sanitize_job(job: dict[str, Any]) -> dict[str, Any]:
    safe = dict(job)
    safe["events"] = _safe_events(safe)
    safe["result"] = safe.get("result") if isinstance(safe.get("result"), dict) else None
    return safe


def _safe_events(job: dict[str, Any]) -> list[dict[str, Any]]:
    events = job.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)][-25:]


def _job_event(
    *,
    stage: str,
    level: str,
    message: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "eventId": f"remote-provisioning-event-{uuid.uuid4().hex}",
        "stage": stage,
        "level": level,
        "message": message,
        "createdAt": created_at,
    }


def _status_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _summarize_runner_result(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return {}
    runner = data.get("runner") if isinstance(data.get("runner"), dict) else {}
    health = data.get("health") if isinstance(data.get("health"), dict) else {}
    ready = health.get("ready") if isinstance(health.get("ready"), dict) else {}
    return {
        "serverId": str(data.get("serverId") or ""),
        "lifecycleAction": str(data.get("lifecycleAction") or ""),
        "completedAt": str(data.get("completedAt") or ""),
        "runner": {
            "state": str(runner.get("state") or ""),
            "ready": bool(runner.get("ready")),
            "servicePort": runner.get("servicePort"),
            "tunnelPort": runner.get("tunnelPort"),
            "version": runner.get("version"),
        },
        "health": {
            "ready": bool(ready.get("ok")),
            "message": str(ready.get("message") or ""),
        },
    }


def _queued_message(action: str) -> str:
    return {
        "ensure-runner": "Remote runner provisioning is queued.",
        "start-runner": "Remote runner start is queued.",
        "upgrade-runner": "Remote runner upgrade is queued.",
        "repair-runner": "Remote runner diagnostics repair is queued.",
    }.get(action, "Remote provisioning job is queued.")


def _running_stage(action: str) -> str:
    return {
        "ensure-runner": "bootstrap",
        "start-runner": "start",
        "upgrade-runner": "upgrade",
        "repair-runner": "repair",
    }.get(action, "running")


def _running_message(action: str) -> str:
    return {
        "ensure-runner": "Installing or reusing the remote runner.",
        "start-runner": "Starting the remote runner service.",
        "upgrade-runner": "Upgrading the remote runner release.",
        "repair-runner": "Repairing remote runner diagnostics.",
    }.get(action, "Remote provisioning job is running.")


def _success_message(action: str) -> str:
    return {
        "ensure-runner": "Remote runner provisioning completed.",
        "start-runner": "Remote runner start completed.",
        "upgrade-runner": "Remote runner upgrade completed.",
        "repair-runner": "Remote runner diagnostics repair completed.",
    }.get(action, "Remote provisioning completed.")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _runtime_error_reason_code(error: RuntimeServiceError) -> str:
    detail = getattr(error, "detail", None)
    if isinstance(detail, dict):
        return str(detail.get("reasonCode") or "")
    return ""
