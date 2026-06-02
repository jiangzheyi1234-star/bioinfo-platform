from __future__ import annotations

from .config import RemoteRunnerConfig
from .storage import upsert_tool
from .tool_prepare_job_storage import (
    complete_tool_prepare_job,
    fail_tool_prepare_job,
    fetch_tool_prepare_job,
    mark_tool_prepare_job_waiting_resource,
    record_tool_prepare_job_event,
    tool_prepare_job_cancelled,
    tool_prepare_job_payload,
)
from .tool_preparation import validate_registered_tool_for_publish
from .tool_revisions import publish_tool_revision
from .tools_errors import ToolPrepareWaitingResourceError, ToolRegistryError


def run_tool_prepare_job(cfg: RemoteRunnerConfig, job_id: str) -> None:
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None or job["status"] == "cancelled":
        return
    job = record_tool_prepare_job_event(cfg, job_id, stage="validating_spec", message="Validating tool specification.")
    if job["status"] == "cancelled":
        return

    try:
        payload = tool_prepare_job_payload(job)
        item = validate_registered_tool_for_publish(cfg, payload, event_callback=_job_event_recorder(cfg, job_id))
        if tool_prepare_job_cancelled(cfg, job_id):
            return
        record_tool_prepare_job_event(cfg, job_id, stage="publishing", message="Publishing immutable tool revision.")
        published = publish_tool_revision(cfg, item)
        published["status"] = "published"
        published["message"] = str(item.get("message") or "Tool revision published.")
        saved = upsert_tool(cfg, published)
        complete_tool_prepare_job(cfg, job_id, saved)
    except ToolPrepareWaitingResourceError as exc:
        mark_tool_prepare_job_waiting_resource(cfg, job_id, code=exc.code, message=exc.message, details=exc.details)
    except ToolRegistryError as exc:
        fail_tool_prepare_job(cfg, job_id, code=str(exc), message=str(exc))
    except Exception as exc:
        fail_tool_prepare_job(cfg, job_id, code="TOOL_PREPARE_JOB_FAILED", message=str(exc) or "Prepare job failed.")


def _job_event_recorder(cfg: RemoteRunnerConfig, job_id: str):
    def _record(event: dict[str, object]) -> None:
        if tool_prepare_job_cancelled(cfg, job_id):
            return
        details = event.get("details")
        record_tool_prepare_job_event(
            cfg,
            job_id,
            stage=str(event.get("stage") or "running"),
            message=str(event.get("message") or "Prepare job updated."),
            level=str(event.get("level") or "info"),
            details=details if isinstance(details, dict) else {},
        )

    return _record
