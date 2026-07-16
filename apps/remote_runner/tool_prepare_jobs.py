from __future__ import annotations

from .config import RemoteRunnerConfig
from .tool_prepare_attempt_mutations import (
    fail_tool_prepare_job,
    mark_tool_prepare_job_waiting_resource,
    record_tool_prepare_job_event,
)
from .tool_prepare_claims import ToolPrepareAttemptProof, ToolPrepareClaimLostError
from .tool_prepare_job_storage import (
    fetch_tool_prepare_job,
    tool_prepare_job_cancelled,
    tool_prepare_job_payload,
)
from .tool_prepare_publication import publish_validated_tool_for_attempt
from .tool_preparation import validate_registered_tool_for_publish
from .tools_errors import ToolPrepareWaitingResourceError, ToolRegistryError


def run_tool_prepare_job(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
) -> None:
    job_id = proof.job_id
    job = fetch_tool_prepare_job(cfg, job_id)
    if job is None:
        raise ToolPrepareClaimLostError("prepare job is missing")
    if job["status"] == "cancelled":
        return
    record_tool_prepare_job_event(
        cfg,
        proof,
        stage="validating_spec",
        message="Validating tool specification.",
    )
    if tool_prepare_job_cancelled(cfg, job_id):
        return

    try:
        payload = tool_prepare_job_payload(job)
        item = validate_registered_tool_for_publish(
            cfg,
            payload,
            event_callback=_job_event_recorder(cfg, proof),
        )
        if tool_prepare_job_cancelled(cfg, job_id):
            return
        record_tool_prepare_job_event(
            cfg,
            proof,
            stage="publishing",
            message="Publishing immutable tool revision.",
        )
        publish_validated_tool_for_attempt(
            cfg,
            proof=proof,
            validated_tool=item,
        )
    except ToolPrepareWaitingResourceError as exc:
        mark_tool_prepare_job_waiting_resource(
            cfg,
            proof,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    except ToolRegistryError as exc:
        fail_tool_prepare_job(cfg, proof, code=str(exc), message=str(exc))


def _job_event_recorder(cfg: RemoteRunnerConfig, proof: ToolPrepareAttemptProof):
    def _record(event: dict[str, object]) -> None:
        if tool_prepare_job_cancelled(cfg, proof.job_id):
            return
        details = event.get("details")
        record_tool_prepare_job_event(
            cfg,
            proof,
            stage=str(event.get("stage") or "running"),
            message=str(event.get("message") or "Prepare job updated."),
            level=str(event.get("level") or "info"),
            details=details if isinstance(details, dict) else {},
        )

    return _record
