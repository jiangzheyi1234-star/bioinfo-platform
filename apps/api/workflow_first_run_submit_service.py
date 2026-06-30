"""First Successful Run canonical submission orchestration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from apps.api.models import ApiRequest, RunSubmitRequest
from apps.api.submission_service import ResponseWithHeaders, submit_run_from_request
from apps.api.workflow_first_run_finalize_service import first_run_next_action
from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from apps.api.workflow_sample_data_service import (
    MOVING_PICTURES_FILES,
    MOVING_PICTURES_PIPELINE_ID,
    WorkflowSampleDataPrepareRequest,
    prepare_workflow_sample_data_uploads,
)


FIRST_RUN_SUBMISSION_SCHEMA_VERSION = "h2ometa.first-run.submit.v1"
FIRST_RUN_PROJECT_ID = "first-run-pilot"


class WorkflowFirstRunSubmitRequest(ApiRequest):
    serverId: str = Field(min_length=1)
    confirmation: Literal["submit-first-run"]
    idempotencyKey: str | None = Field(default=None, min_length=1)
    actor: str | None = None


class WorkflowFirstRunSubmitBlockedError(ValueError):
    pass


async def submit_first_run_from_request(
    request: WorkflowFirstRunSubmitRequest,
    response: ResponseWithHeaders,
) -> dict[str, Any]:
    server_id = str(request.serverId or "").strip()
    status = (await build_first_run_status_from_request(server_id=server_id, refresh=True))["data"]
    blocker = _submission_blocker(status)
    if blocker:
        return _blocked(
            blocker["code"],
            blocker["detail"],
            first_run_status=status,
            next_action=blocker.get("nextAction"),
        )

    sample_payload = await prepare_workflow_sample_data_uploads(
        MOVING_PICTURES_PIPELINE_ID,
        WorkflowSampleDataPrepareRequest(serverId=server_id),
    )
    sample_data = _require_sample_data(sample_payload)
    try:
        run_spec = _canonical_first_run_spec(sample_data)
    except WorkflowFirstRunSubmitBlockedError as exc:
        return _blocked(str(exc).split(":", 1)[0], str(exc), first_run_status=status, sample_data=sample_data)

    submission = await submit_run_from_request(
        RunSubmitRequest(
            serverId=server_id,
            idempotencyKey=request.idempotencyKey,
            requestId=request.idempotencyKey,
            runSpec=run_spec,
        )
    )
    submitted_run = _unwrap_data(submission.payload)
    if not str(submitted_run.get("runId") or "").strip():
        return _blocked(
            "FIRST_RUN_SUBMISSION_RUN_ID_REQUIRED",
            "First-run submission response must include runId.",
            first_run_status=status,
            sample_data=sample_data,
        )
    response.headers.update(submission.headers)
    return {
        "data": {
            "schemaVersion": FIRST_RUN_SUBMISSION_SCHEMA_VERSION,
            "status": "submitted",
            "serverId": server_id,
            "actor": request.actor or "first-run-ui",
            "submittedRun": submitted_run,
            "sampleData": sample_data,
            "runSpec": _safe_run_spec(run_spec),
            "nextAction": {
                "code": "REFRESH_RUN",
                "detail": "首跑已提交，等待 runner 返回运行状态、报告和结果包证据。",
                "label": "查看运行状态",
                "target": "/workflows/first-run#run-report",
            },
        }
    }


def _submission_blocker(status: dict[str, Any]) -> dict[str, Any] | None:
    evidence = status.get("evidence") if isinstance(status.get("evidence"), dict) else {}
    ready = (
        (evidence.get("server") or {}).get("ready") is True
        and (evidence.get("execution") or {}).get("ready") is True
        and (evidence.get("workflow") or {}).get("ready") is True
    )
    if not ready:
        action = status.get("nextAction") if isinstance(status.get("nextAction"), dict) else {}
        return {
            "code": str(action.get("blockedCode") or action.get("code") or "FIRST_RUN_NOT_READY"),
            "detail": str(action.get("detail") or "First-run readiness has not passed."),
            "nextAction": action,
        }
    sample_cache = evidence.get("sampleCache") if isinstance(evidence.get("sampleCache"), dict) else {}
    if sample_cache.get("status") == "blocked":
        code = str((sample_cache.get("blockerCodes") or ["FIRST_RUN_SAMPLE_DATA_BLOCKED"])[0])
        return {
            "code": code,
            "detail": "官方样例数据缓存不可用，请先修复样例数据缓存。",
            "nextAction": status.get("nextAction") if isinstance(status.get("nextAction"), dict) else {},
        }
    stage = str(status.get("stage") or "")
    if stage not in {"prepare_sample_data", "submit_run"}:
        action = status.get("nextAction") if isinstance(status.get("nextAction"), dict) else {}
        return {
            "code": str(action.get("blockedCode") or action.get("code") or "FIRST_RUN_SUBMIT_NOT_AVAILABLE"),
            "detail": str(action.get("detail") or f"First-run stage {stage or 'unknown'} cannot submit a new run."),
            "nextAction": action,
        }
    return None


def _require_sample_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    prep_proof = data.get("prepProof") if isinstance(data.get("prepProof"), dict) else {}
    return {
        "pipelineId": data.get("pipelineId") or MOVING_PICTURES_PIPELINE_ID,
        "source": data.get("source"),
        "items": [item for item in items if isinstance(item, dict)],
        "prepProof": prep_proof,
    }


def _canonical_first_run_spec(sample_data: dict[str, Any]) -> dict[str, Any]:
    uploads = sample_data.get("items") if isinstance(sample_data.get("items"), list) else []
    expected_roles = [item.role for item in MOVING_PICTURES_FILES]
    by_role = {str(item.get("role") or ""): item for item in uploads if isinstance(item, dict)}
    if sorted(by_role) != sorted(expected_roles) or len(by_role) != len(uploads):
        raise WorkflowFirstRunSubmitBlockedError("FIRST_RUN_SAMPLE_INPUTS_REQUIRED: official sample roles must be exact")
    inputs = []
    for expected in MOVING_PICTURES_FILES:
        upload = by_role.get(expected.role) or {}
        if str(upload.get("filename") or "") != expected.filename or not str(upload.get("uploadId") or "").strip():
            raise WorkflowFirstRunSubmitBlockedError(f"FIRST_RUN_SAMPLE_INPUTS_REQUIRED: {expected.role} upload is invalid")
        if str(upload.get("integrityStatus") or "") != "passed":
            raise WorkflowFirstRunSubmitBlockedError(
                f"FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH: {expected.role} checksum evidence is required"
            )
        inputs.append(
            {
                "uploadId": str(upload["uploadId"]),
                "filename": expected.filename,
                "role": expected.role,
            }
        )
    prep_proof = sample_data.get("prepProof") if isinstance(sample_data.get("prepProof"), dict) else {}
    if not prep_proof:
        raise WorkflowFirstRunSubmitBlockedError("FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED: sample prep proof is required")
    return {
        "projectId": FIRST_RUN_PROJECT_ID,
        "pipelineId": MOVING_PICTURES_PIPELINE_ID,
        "inputs": inputs,
        "params": {},
        "sampleDataPrepProof": prep_proof,
    }


def _safe_run_spec(run_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "projectId": run_spec.get("projectId"),
        "pipelineId": run_spec.get("pipelineId"),
        "inputs": run_spec.get("inputs") if isinstance(run_spec.get("inputs"), list) else [],
        "sampleDataPrepProof": run_spec.get("sampleDataPrepProof") if isinstance(run_spec.get("sampleDataPrepProof"), dict) else {},
    }


def _blocked(
    code: str,
    detail: str,
    *,
    first_run_status: dict[str, Any],
    next_action: dict[str, Any] | None = None,
    sample_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": FIRST_RUN_SUBMISSION_SCHEMA_VERSION,
        "status": "blocked",
        "serverId": first_run_status.get("serverId"),
        "nextAction": next_action or first_run_next_action(code, detail),
        "firstRunStatus": first_run_status,
    }
    if sample_data:
        data["sampleData"] = sample_data
    return {"data": data}


def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    return data or payload
