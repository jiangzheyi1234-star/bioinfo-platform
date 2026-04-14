"""Workflow-first core domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    tool_id: str
    label: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    output_name: str = ""
    input_name: str = ""


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    name: str
    version: str = "0.1.0"
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    params_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    version: str = ""
    container_ref: str = ""
    conda_spec: str = ""
    test_command: str = ""


@dataclass(frozen=True)
class ServerProfile:
    profile_id: str
    server_id: str
    profile_kind: Literal["personal_docker", "personal_podman", "personal_conda", "hpc_slurm_apptainer", "hpc_slurm_conda", "hpc_pbs_apptainer", "hpc_pbs_conda", "hpc_sge_apptainer", "hpc_sge_conda"]
    executor: str
    packaging_mode: Literal["container", "conda"]
    container_runtime: str = ""
    work_dir: str = ""
    output_dir: str = ""
    cache_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LaunchSpec:
    project_id: str
    profile: ServerProfile
    params: dict[str, Any] = field(default_factory=dict)
    data_refs: list[str] = field(default_factory=list)
    resume: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = self.profile.to_dict()
        return payload


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    project_id: str
    task_id: str
    workflow_snapshot_id: str
    execution_id: str
    workflow_id: str
    profile_id: str
    status: Literal["draft", "pending", "running", "completed", "failed", "cancelled"]
    snapshot_hash: str
    created_at: float
    updated_at: float
    snapshot_payload_json: dict[str, Any] = field(default_factory=dict)
    bundle_id: str = ""
    message: str = ""
    result_path: str = ""
    error_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowSnapshotRecord:
    workflow_snapshot_id: str
    project_id: str
    task_id: str
    workflow_id: str
    name: str
    version: str
    workflow_definition_json: dict[str, Any] = field(default_factory=dict)
    params_schema_json: dict[str, Any] = field(default_factory=dict)
    workflow_hash: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowResultRecord:
    workflow_result_id: str
    project_id: str
    task_id: str
    workflow_run_id: str
    result_kind: str = "artifacts"
    summary_json: dict[str, Any] = field(default_factory=dict)
    result_path: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
