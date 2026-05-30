from __future__ import annotations

from apps.api.run_submission_status import classify_run_submission_status
from apps.remote_runner.main import _run_preflight_status_code


def test_workflow_tool_not_ready_preflight_maps_to_conflict() -> None:
    assert _run_preflight_status_code("WORKFLOW_TOOL_NOT_READY: SnakemakeRenderable") == 409
    assert _run_preflight_status_code("TOOL_INPUT_REQUIRED: primary") == 422


def test_local_run_submission_classifies_workflow_tool_not_ready_as_conflict() -> None:
    assert classify_run_submission_status(detail="WORKFLOW_TOOL_NOT_READY: SmokeRunPassed", fallback=400) == 409
