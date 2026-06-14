from __future__ import annotations

import logging
from typing import Any

from .resource_pool import ResourceRequest


LOGGER = logging.getLogger("apps.remote_runner.run_execution_storage")


def log_admission_wait(
    *,
    wait_reason: dict[str, Any],
    job: Any,
    queue_name: str,
    worker_id: str,
    session_id: str,
    slot_id: str,
    request: ResourceRequest,
) -> None:
    LOGGER.info(
        "run job admission wait",
        extra={
            "event": "execution.admission.wait",
            "decision": "wait",
            "reasonCode": wait_reason.get("code"),
            "runId": job["run_id"],
            "jobId": job["job_id"],
            "queueName": queue_name,
            "workerId": worker_id,
            "sessionId": session_id,
            "slotId": slot_id,
            "resourceRequest": _resource_request_to_dict(request),
        },
    )


def log_claim_accepted(
    *,
    job: Any,
    attempt_id: str,
    lease_generation: int,
    queue_name: str,
    worker_id: str,
    session_id: str,
    slot_id: str,
    request: ResourceRequest,
) -> None:
    LOGGER.info(
        "run job claimed",
        extra={
            "event": "execution.claim.accepted",
            "decision": "claim",
            "reasonCode": "",
            "runId": job["run_id"],
            "jobId": job["job_id"],
            "attemptId": attempt_id,
            "leaseGeneration": lease_generation,
            "queueName": queue_name,
            "workerId": worker_id,
            "sessionId": session_id,
            "slotId": slot_id,
            "resourceRequest": _resource_request_to_dict(request),
        },
    )


def _resource_request_to_dict(request: ResourceRequest) -> dict[str, int]:
    return {
        "cpu": int(request.cpu),
        "memoryMb": int(request.memory_mb),
        "diskMb": int(request.disk_mb),
        "gpu": int(request.gpu),
    }
