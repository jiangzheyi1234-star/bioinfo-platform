from __future__ import annotations

import time
from typing import Any, Protocol


class RemoteRunnerHealthClient(Protocol):
    def get_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        ...


def build_runner_health(client: RemoteRunnerHealthClient) -> dict[str, Any]:
    startup = client.get_json("/health/startup", accepted_statuses={200, 503})
    live = client.get_json("/health/live")
    ready = client.get_json("/health/ready", accepted_statuses={200, 503})
    workflow = (
        ready.get("workflowRuntime")
        if isinstance(ready.get("workflowRuntime"), dict)
        else {}
    )
    pipeline_registry = (
        ready.get("pipelineRegistry")
        if isinstance(ready.get("pipelineRegistry"), dict)
        else {}
    )
    ready_ok = ready.get("status") == "ok"
    workflow_ok = workflow.get("ok")
    pipeline_ok = pipeline_registry.get("ok")
    workflow_message = str(workflow.get("message") or "")
    pipeline_message = str(pipeline_registry.get("message") or "")
    normalized_workflow_ok = bool(workflow_ok) if workflow_ok is not None else ready_ok
    normalized_pipeline_ok = (
        bool(pipeline_ok) if pipeline_ok is not None else ready_ok
    )
    ready_message = "Remote runner control plane is ready."
    reason_code = ""
    if not ready_ok:
        detail_parts: list[str] = []
        if not normalized_workflow_ok:
            detail_parts.append(
                f"workflow runtime: {workflow_message or 'Workflow runtime is not ready.'}"
            )
            reason_code = "WORKFLOW_RUNTIME_NOT_READY"
        if not normalized_pipeline_ok:
            detail_parts.append(
                f"pipeline registry: {pipeline_message or 'Pipeline registry is not ready.'}"
            )
            if not reason_code:
                reason_code = "PIPELINE_REGISTRY_NOT_READY"
        if detail_parts:
            ready_message = "; ".join(detail_parts)
        else:
            ready_message = "Remote runner control plane is not ready."
            reason_code = "RUNNER_NOT_READY"
    return {
        "startup": {
            "ok": startup.get("status") == "ok",
            "message": (
                "Remote runner startup checks passed."
                if startup.get("status") == "ok"
                else "Remote runner startup checks failed."
            ),
        },
        "live": {
            "ok": live.get("status") == "ok",
            "message": (
                "Remote runner process is alive."
                if live.get("status") == "ok"
                else "Remote runner process is not healthy."
            ),
        },
        "ready": {
            "ok": ready_ok,
            "message": ready_message,
        },
        "workflowRuntime": {
            "ok": normalized_workflow_ok,
            "message": workflow_message
            or ("Workflow runtime is ready." if ready_ok else "Workflow runtime is not ready."),
            "provider": str(workflow.get("provider") or ""),
            "source": str(workflow.get("source") or ""),
            "version": str(workflow.get("version") or ""),
            "snakemakeCommand": str(workflow.get("snakemakeCommand") or ""),
            "snakemakeVersion": str(workflow.get("snakemakeVersion") or ""),
            "workflowProfileConfigured": bool(workflow.get("workflowProfileConfigured")),
            "workflowProfileOk": bool(workflow.get("workflowProfileOk")),
            "workflowProfileMessage": str(workflow.get("workflowProfileMessage") or ""),
            "workflowProfileDir": str(workflow.get("workflowProfileDir") or ""),
            "workflowProfileName": str(workflow.get("workflowProfileName") or ""),
            "workflowProfilePath": str(workflow.get("workflowProfilePath") or ""),
        },
        "pipelineRegistry": {
            "ok": normalized_pipeline_ok,
            "message": pipeline_message
            or (
                "Pipeline registry is ready."
                if ready_ok
                else "Pipeline registry is not ready."
            ),
            "count": int(pipeline_registry.get("count") or 0),
            "items": (
                pipeline_registry.get("items")
                if isinstance(pipeline_registry.get("items"), list)
                else []
            ),
        },
        "reasonCode": reason_code,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
