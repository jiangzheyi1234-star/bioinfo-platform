"""Shared tool validation plan contract for catalog queues and recommendations."""

from __future__ import annotations

from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, render_remote_endpoint_path
from core.contracts.tool_remote_endpoints import (
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
)


def tool_prepare_job_submit_path() -> str:
    return REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].path_template


def tool_prepare_job_poll_path_template() -> str:
    template = REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_READ].path_template
    if "{job_id}" not in template:
        raise ValueError("TOOL_PREPARE_JOB_READ_PATH_PARAM_UNEXPECTED")
    return template.replace("{job_id}", "{jobId}")


def tool_prepare_job_poll_path(job_id: str) -> str:
    return render_remote_endpoint_path(TOOL_PREPARE_JOB_READ, {"job_id": job_id})


def tool_prepare_job_queue_path() -> str:
    return REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].path_template


def tool_prepare_job_queue_method() -> str:
    return REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].method


def workflow_ready_validation_plan() -> dict[str, Any]:
    return {
        "planVersion": "tool-validation-plan-v1",
        "requiredState": "WorkflowReady",
        "submit": {
            "method": REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].method,
            "path": tool_prepare_job_submit_path(),
            "payloadRef": "preparePayload",
        },
        "poll": {
            "method": REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_READ].method,
            "pathTemplate": tool_prepare_job_poll_path_template(),
            "jobIdField": "jobId",
        },
        "terminalStatuses": {
            "success": ["succeeded"],
            "waiting": ["waiting_resource"],
            "failure": ["failed", "cancelled"],
        },
        "stages": [
            {
                "id": "profile_schema_validation",
                "evidence": "Tool manifest and profile schema accepted by the remote runner.",
            },
            {
                "id": "static_rulespec_validation",
                "evidence": "RuleSpec is complete and Snakemake-renderable before execution.",
            },
            {
                "id": "dry_run",
                "contractStatusKey": "dryRun",
                "evidence": "Snakemake dry-run passes for the generated smoke workflow.",
            },
            {
                "id": "smoke_run",
                "contractStatusKey": "smokeRun",
                "evidence": "Snakemake smoke run completes with profile fixtures/resources.",
            },
            {
                "id": "output_validation",
                "contractStatusKey": "outputValidation",
                "evidence": "Declared outputs exist and satisfy the rule output schema.",
            },
            {
                "id": "published",
                "evidence": "Immutable tool revision is saved only after WorkflowReady validation.",
            },
        ],
        "successCriteria": [
            {"contractStatusKey": "dryRun", "status": "passed"},
            {"contractStatusKey": "smokeRun", "status": "passed"},
            {"contractStatusKey": "outputValidation", "status": "passed"},
            {"toolContractField": "workflowReady", "value": True},
        ],
        "readinessBoundary": "Candidate remains queued until the prepare job succeeds and returns toolContract.workflowReady=true.",
    }
