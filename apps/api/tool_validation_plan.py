"""Shared tool validation plan contract for catalog queues and recommendations."""

from __future__ import annotations

from typing import Any


def workflow_ready_validation_plan() -> dict[str, Any]:
    return {
        "planVersion": "tool-validation-plan-v1",
        "requiredState": "WorkflowReady",
        "submit": {
            "method": "POST",
            "path": "/api/v1/tools/prepare-jobs",
            "payloadRef": "preparePayload",
        },
        "poll": {
            "method": "GET",
            "pathTemplate": "/api/v1/tools/prepare-jobs/{jobId}",
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
