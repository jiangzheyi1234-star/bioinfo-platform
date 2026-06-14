"""Run-submission validation for WorkflowDesignDraft-derived runs."""

from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from core.contracts.workflow_design import workflow_design_to_generated_run_spec
from .workflow_design_storage import fetch_workflow_design_draft
from .workflow_revision_storage import fetch_workflow_revision


ALLOWED_WORKFLOW_DESIGN_RUN_SPEC_KEYS = {
    "projectId",
    "pipelineId",
    "inputs",
    "workflow",
    "resourceBindings",
    "execution",
    "workflowDesign",
    "workflowRevisionId",
}


def validate_workflow_design_run_spec(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> None:
    workflow_design = run_spec.get("workflowDesign")
    if not isinstance(workflow_design, dict):
        raise ValueError("WORKFLOW_DESIGN_RUN_SPEC_REQUIRED")
    draft_id = str(workflow_design.get("draftId") or "").strip()
    revision = workflow_design.get("revision")
    if not draft_id or not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("WORKFLOW_DESIGN_RUN_SPEC_REQUIRED")
    workflow_revision_id = str(run_spec.get("workflowRevisionId") or "").strip()
    if not workflow_revision_id:
        raise ValueError("WORKFLOW_REVISION_ID_REQUIRED")

    extra_keys = sorted(set(run_spec) - ALLOWED_WORKFLOW_DESIGN_RUN_SPEC_KEYS)
    if "pipelineVersion" in extra_keys:
        raise ValueError("WORKFLOW_DESIGN_RUN_SPEC_MISMATCH: pipelineVersion")
    if extra_keys:
        raise ValueError(f"WORKFLOW_DESIGN_RUN_SPEC_UNSUPPORTED_FIELD: {extra_keys[0]}")

    record = fetch_workflow_design_draft(cfg, draft_id)
    if record is None:
        raise ValueError("WORKFLOW_DESIGN_DRAFT_NOT_FOUND")
    if int(record["revision"]) != revision:
        raise ValueError("WORKFLOW_DESIGN_REVISION_MISMATCH")
    workflow_revision = fetch_workflow_revision(cfg, workflow_revision_id)
    if workflow_revision is None:
        raise ValueError("WORKFLOW_REVISION_NOT_FOUND")
    if workflow_revision.get("draftId") != draft_id or workflow_revision.get("draftRevision") != revision:
        raise ValueError("WORKFLOW_REVISION_DRAFT_MISMATCH")

    expected = workflow_design_to_generated_run_spec(
        record["draft"],
        draft_id=draft_id,
        revision=revision,
    )
    graph_snapshot = workflow_revision.get("graphSnapshot")
    snapshot_run_spec = graph_snapshot.get("runSpec") if isinstance(graph_snapshot, dict) else None
    if snapshot_run_spec != expected:
        raise ValueError("WORKFLOW_REVISION_RUN_SPEC_MISMATCH")
    for key in ("projectId", "pipelineId", "workflow", "resourceBindings", "workflowDesign"):
        if run_spec.get(key) != expected[key]:
            raise ValueError(f"WORKFLOW_DESIGN_RUN_SPEC_MISMATCH: {key}")
    _validate_uploaded_inputs(run_spec.get("inputs"), expected["inputs"])


def _validate_uploaded_inputs(raw_inputs: Any, expected_inputs: list[dict[str, str]]) -> None:
    if not isinstance(raw_inputs, list) or len(raw_inputs) != len(expected_inputs):
        raise ValueError("WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH")
    for index, (actual, expected) in enumerate(zip(raw_inputs, expected_inputs, strict=True)):
        if not isinstance(actual, dict):
            raise ValueError("WORKFLOW_DESIGN_RUN_INPUT_INVALID")
        extra_keys = set(actual) - {"role", "uploadId", "filename"}
        if extra_keys:
            raise ValueError(f"WORKFLOW_DESIGN_RUN_INPUT_UNSUPPORTED_FIELD: {sorted(extra_keys)[0]}")
        actual_role = str(actual.get("role") or "").strip()
        expected_role = str(expected.get("role") or "").strip()
        if actual_role != expected_role:
            raise ValueError(f"WORKFLOW_DESIGN_RUN_INPUT_ROLE_MISMATCH: {index}")
        actual_filename = str(actual.get("filename") or "").strip()
        expected_filename = str(expected.get("filename") or "").strip()
        if actual_filename != expected_filename:
            raise ValueError(f"WORKFLOW_DESIGN_RUN_INPUT_FILENAME_MISMATCH: {index}")
        upload_id = str(actual.get("uploadId") or "").strip()
        if not upload_id:
            raise ValueError(f"WORKFLOW_DESIGN_RUN_INPUT_UPLOAD_REQUIRED: {expected_role}")
