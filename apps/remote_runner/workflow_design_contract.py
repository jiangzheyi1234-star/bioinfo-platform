"""WorkflowDesignDraft v1 contract and conversion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from .generated_workflow_graph import GENERATED_WORKFLOW_RULE_CONTRACT_VERSION

WORKFLOW_DESIGN_DRAFT_CONTRACT_VERSION = "workflow-design-draft-v1"
WORKFLOW_DESIGN_ENGINE = "snakemake"
WORKFLOW_DESIGN_EDGE_AUDIT_KEYS = frozenset({"source", "decision", "confidence", "reason", "hardChecks", "evidence"})

WorkflowDesignScalar = str | int | float | bool
WorkflowDesignParamValue = str | int | float | bool


class WorkflowDesignModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False, strict=True)


class WorkflowDesignMetadata(WorkflowDesignModel):
    name: str = Field(min_length=1)
    description: str = ""
    projectId: str = Field(default="proj_workflow_design", min_length=1)
    tags: list[str] = Field(default_factory=list)


class WorkflowDesignInput(WorkflowDesignModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    filename: str | None = None
    mimeType: str = "application/octet-stream"
    metadata: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)


class WorkflowDesignPortRef(WorkflowDesignModel):
    nodeId: str = Field(min_length=1)
    port: str = Field(min_length=1)


class WorkflowDesignInputBindingFromInput(WorkflowDesignModel):
    fromInput: str = Field(min_length=1)


WorkflowDesignInputBinding = WorkflowDesignInputBindingFromInput


class WorkflowDesignRuntime(WorkflowDesignModel):
    threads: int | None = Field(default=None, ge=1)
    resources: dict[str, WorkflowDesignParamValue] = Field(default_factory=dict)
    schedulerResources: dict[str, WorkflowDesignParamValue] = Field(default_factory=dict)
    log: str | dict[str, str] | None = None


class WorkflowDesignNodeOutput(WorkflowDesignModel):
    expose: bool = False
    alias: str | None = None
    metadata: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)


class WorkflowDesignNode(WorkflowDesignModel):
    id: str = Field(min_length=1)
    toolRevisionId: str = Field(min_length=1)
    inputs: dict[str, WorkflowDesignInputBinding] = Field(default_factory=dict)
    params: dict[str, WorkflowDesignParamValue] = Field(default_factory=dict)
    runtime: WorkflowDesignRuntime = Field(default_factory=WorkflowDesignRuntime)
    resources: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)
    outputs: dict[str, WorkflowDesignNodeOutput] = Field(default_factory=dict)
    metadata: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)
    provenance: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)


class WorkflowDesignEdge(WorkflowDesignModel):
    id: str | None = None
    from_: WorkflowDesignPortRef = Field(alias="from")
    to: WorkflowDesignPortRef
    audit: dict[str, WorkflowDesignScalar] | None = None

    @model_validator(mode="after")
    def validate_audit_keys(self) -> "WorkflowDesignEdge":
        if self.audit:
            unknown_key = next((key for key in self.audit if key not in WORKFLOW_DESIGN_EDGE_AUDIT_KEYS), None)
            if unknown_key is not None:
                raise ValueError(f"WORKFLOW_DESIGN_EDGE_AUDIT_UNKNOWN_KEY: {unknown_key}")
        return self


class WorkflowDesignOutput(WorkflowDesignModel):
    from_: WorkflowDesignPortRef = Field(alias="from")
    as_: str = Field(alias="as", min_length=1)
    metadata: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)


class WorkflowDesignResources(WorkflowDesignModel):
    bindings: dict[str, dict[str, str]] = Field(default_factory=dict)
    metadata: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)


class WorkflowDesignDraftV1(WorkflowDesignModel):
    contractVersion: Literal["workflow-design-draft-v1"]
    engine: Literal["snakemake"]
    metadata: WorkflowDesignMetadata
    inputs: list[WorkflowDesignInput] = Field(default_factory=list)
    nodes: list[WorkflowDesignNode] = Field(default_factory=list)
    edges: list[WorkflowDesignEdge] = Field(default_factory=list)
    resources: WorkflowDesignResources = Field(default_factory=WorkflowDesignResources)
    outputs: list[WorkflowDesignOutput] = Field(default_factory=list)
    provenance: dict[str, WorkflowDesignScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_design_keys(self) -> "WorkflowDesignDraftV1":
        _ensure_unique(
            (item.id for item in self.inputs),
            "WORKFLOW_DESIGN_INPUT_ID_DUPLICATE",
        )
        _ensure_unique(
            (item.role for item in self.inputs),
            "WORKFLOW_DESIGN_INPUT_ROLE_DUPLICATE",
        )
        _ensure_unique(
            (node.id for node in self.nodes),
            "WORKFLOW_DESIGN_NODE_ID_DUPLICATE",
        )
        _ensure_unique(
            (_safe_step_id(node.id) for node in self.nodes),
            "WORKFLOW_DESIGN_NODE_ID_NORMALIZED_DUPLICATE",
        )
        _ensure_unique(
            (output.as_ for output in self.outputs),
            "WORKFLOW_DESIGN_OUTPUT_ALIAS_DUPLICATE",
        )
        _ensure_unique(
            (_safe_output_alias(output.as_) for output in self.outputs),
            "WORKFLOW_DESIGN_OUTPUT_ALIAS_NORMALIZED_DUPLICATE",
        )
        return self


def normalize_workflow_design_draft(draft: WorkflowDesignDraftV1 | dict[str, Any]) -> dict[str, Any]:
    return WorkflowDesignDraftV1.model_validate(draft).model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )


def workflow_design_resolved_inputs(draft: WorkflowDesignDraftV1) -> list[dict[str, str]]:
    return [
        {
            "role": item.role,
            "path": item.path,
            "filename": item.filename or Path(item.path).name,
            "mimeType": item.mimeType,
        }
        for item in draft.inputs
    ]


def workflow_design_to_generated_run_spec(
    draft: WorkflowDesignDraftV1 | dict[str, Any],
    *,
    draft_id: str | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    draft = WorkflowDesignDraftV1.model_validate(draft)
    normalized_node_ids = {node.id: _safe_step_id(node.id) for node in draft.nodes}
    workflow: dict[str, Any] = {
        "contractVersion": GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
        "nodes": [
            {
                "id": normalized_node_ids[node.id],
                "toolRevisionId": node.toolRevisionId,
                "inputs": _normalized_node_inputs(node, normalized_node_ids),
                "params": dict(node.params),
                "runtime": node.runtime.model_dump(exclude_none=True, mode="json"),
            }
            for node in draft.nodes
        ],
        "edges": [
            {
                "from": {
                    "nodeId": normalized_node_ids.get(edge.from_.nodeId, _safe_step_id(edge.from_.nodeId)),
                    "port": edge.from_.port,
                },
                "to": {
                    "nodeId": normalized_node_ids.get(edge.to.nodeId, _safe_step_id(edge.to.nodeId)),
                    "port": edge.to.port,
                },
            }
            for edge in draft.edges
        ],
        "outputs": [
            {
                "from": {
                    "nodeId": normalized_node_ids.get(output.from_.nodeId, _safe_step_id(output.from_.nodeId)),
                    "port": output.from_.port,
                },
                "as": output.as_,
            }
            for output in draft.outputs
        ],
    }
    return {
        "projectId": draft.metadata.projectId,
        "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
        "inputs": [
            {
                "role": item.role,
                "filename": item.filename or Path(item.path).name,
            }
            for item in draft.inputs
        ],
        "workflow": workflow,
        "resourceBindings": draft.resources.bindings,
        "workflowDesign": _workflow_design_run_metadata(draft, draft_id=draft_id, revision=revision),
    }


def workflow_design_graph(draft: WorkflowDesignDraftV1) -> dict[str, Any]:
    return normalize_workflow_design_draft(draft)


def _normalized_node_inputs(
    node: WorkflowDesignNode,
    normalized_node_ids: dict[str, str],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for input_name, binding in node.inputs.items():
        value = binding.model_dump(by_alias=True, exclude_none=True, mode="json")
        normalized[input_name] = value
    return normalized


def _safe_step_id(value: str) -> str:
    import re

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return normalized or "step"


def _safe_output_alias(value: str) -> str:
    import re

    alias = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "output"
    if alias in {"count", "index", "sort"}:
        return f"tool_{alias}"
    if alias[0].isdigit():
        return f"tool_{alias}"
    return alias


def _ensure_unique(values: Any, code: str) -> None:
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip()
        if key in seen:
            raise ValueError(f"{code}: {key}")
        seen.add(key)


def _workflow_design_run_metadata(
    draft: WorkflowDesignDraftV1,
    *,
    draft_id: str | None,
    revision: int | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "contractVersion": draft.contractVersion,
        "name": draft.metadata.name,
    }
    if draft_id:
        metadata["draftId"] = draft_id
    if revision is not None:
        metadata["revision"] = revision
    return metadata
