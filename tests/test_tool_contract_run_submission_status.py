from __future__ import annotations

from apps.api.route_errors import runtime_service_status_code
from apps.api.run_submission_status import classify_run_submission_status
from apps.remote_runner.errors import WorkflowToolNotReadyError
from apps.remote_runner.generated_workflow_plan import validate_tool_workflow_ready
from apps.remote_runner.preflight import RunPreflightError


def test_workflow_tool_not_ready_preflight_carries_conflict_status() -> None:
    tool = {"toolContract": {"workflowReady": False, "state": "SnakemakeRenderable"}}

    try:
        validate_tool_workflow_ready(tool)
    except WorkflowToolNotReadyError as exc:
        wrapped = RunPreflightError.from_value_error(exc)
    else:
        raise AssertionError("expected WorkflowToolNotReadyError")

    assert str(wrapped) == "WORKFLOW_TOOL_NOT_READY: SnakemakeRenderable"
    assert wrapped.status_code == 409
    assert RunPreflightError.from_value_error(ValueError("TOOL_INPUT_REQUIRED: primary")).status_code == 422


def test_local_run_submission_classifies_workflow_tool_not_ready_as_conflict() -> None:
    assert classify_run_submission_status(detail="WORKFLOW_TOOL_NOT_READY: SmokeRunPassed", fallback=400) == 409


def test_local_runtime_service_error_classifies_remote_readiness_as_service_unavailable() -> None:
    assert runtime_service_status_code("Remote workflow runtime is unavailable: snakemake missing") == 503
