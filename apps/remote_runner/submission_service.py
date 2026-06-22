from __future__ import annotations

import time
from typing import Any

from .api_models import RunCreateRequest
from .config import RemoteRunnerConfig
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from .governance_audit import record_governance_audit_event
from .health_service import ensure_execution_admission_ready, ensure_submission_ready
from .pipeline import get_pipeline, validate_run_spec_for_pipeline
from .preflight import preflight_run_spec
from .route_utils import request_payload
from .storage import canonical_payload_hash, create_run_record


def create_run_from_request(
    cfg: RemoteRunnerConfig,
    request: RunCreateRequest,
    *,
    idempotency_key: str | None,
    x_request_id: str | None,
) -> dict[str, Any]:
    ensure_submission_ready(cfg)
    run_spec = request_payload(request.runSpec)
    pipeline_id = request.runSpec.pipelineId
    pipeline_version = request.runSpec.pipelineVersion
    request_id = str(request.requestId or x_request_id or f"req_{int(time.time() * 1000)}")
    server_id = str(request.serverId)
    idem_key = str(idempotency_key or f"idem_{request_id}")
    pipeline = get_pipeline(cfg, pipeline_id)
    validate_run_spec_for_pipeline(pipeline, run_spec)
    preflight_run_spec(cfg, pipeline, run_spec)
    ensure_execution_admission_ready(cfg)
    if (
        pipeline_id != GENERATED_TOOL_RUN_PIPELINE_ID
        and not str(pipeline_version or "").strip()
    ):
        run_spec["pipelineVersion"] = pipeline.version
    payload_hash = canonical_payload_hash({"serverId": server_id, "runSpec": run_spec})
    run_create = create_run_record(
        cfg,
        server_id=server_id,
        request_id=request_id,
        run_spec=run_spec,
        idempotency_key=idem_key,
        payload_hash=payload_hash,
    )
    run = run_create.run
    record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id=str(run["runId"]),
        details={
            "serverId": server_id,
            "requestId": run["requestId"],
            "pipelineId": pipeline_id,
            "pipelineVersion": str(run_spec.get("pipelineVersion") or ""),
            "projectId": str(run_spec.get("projectId") or ""),
            "runSpecVersion": str(run_spec.get("runSpecVersion") or ""),
            "workflowRevisionId": str(run_spec.get("workflowRevisionId") or ""),
            "idempotencyReplay": not run_create.created,
        },
    )
    return {
        "data": {
            "requestId": run["requestId"],
            "runId": run["runId"],
            "status": run["status"],
            "stage": run["stage"],
            "message": run["message"],
            "lastUpdatedAt": run["lastUpdatedAt"],
        },
        "location": f"/api/v1/runs/{run['runId']}",
        "retryAfter": 2,
        "requestId": run["requestId"],
    }
