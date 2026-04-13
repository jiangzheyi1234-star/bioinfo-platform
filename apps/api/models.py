"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    open_after_create: bool = True


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""


class UpdateTaskRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: str | None = None
    summary: str | None = None


class CreateSampleRequest(BaseModel):
    name: str = Field(min_length=1)
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSettingsRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


class SSHConnectionRequest(BaseModel):
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    password: str | None = None
    use_key: bool | None = None
    key_file: str | None = None
    timeout_sec: int = Field(default=5, ge=1, le=60)


class RemoteEnvInstallRequest(BaseModel):
    target: Literal["miniforge", "tool_env"]
    tool_id: str | None = None


class DatabaseInstallRequest(BaseModel):
    mirror_index: int = Field(default=0, ge=0)


class WorkflowNodeRequest(BaseModel):
    node_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeRequest(BaseModel):
    edge_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    output_name: str = ""
    input_name: str = ""


class WorkflowSpecRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    nodes: list[WorkflowNodeRequest] = Field(default_factory=list)
    edges: list[WorkflowEdgeRequest] = Field(default_factory=list)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class ServerProfileRequest(BaseModel):
    profile_id: str = Field(min_length=1)
    server_id: str = Field(min_length=1)
    profile_kind: Literal[
        "personal_docker",
        "personal_podman",
        "personal_conda",
        "hpc_slurm_apptainer",
        "hpc_slurm_conda",
        "hpc_pbs_apptainer",
        "hpc_pbs_conda",
        "hpc_sge_apptainer",
        "hpc_sge_conda",
    ]
    executor: str = Field(min_length=1)
    packaging_mode: Literal["container", "conda"]
    container_runtime: str = ""
    work_dir: str = ""
    output_dir: str = ""
    cache_dir: str = ""


class LaunchSpecRequest(BaseModel):
    profile: ServerProfileRequest
    params: dict[str, Any] = Field(default_factory=dict)
    data_refs: list[str] = Field(default_factory=list)
    resume: bool = True


class CompileWorkflowRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workflow: WorkflowSpecRequest
    launch: LaunchSpecRequest


class CreateRunRequest(BaseModel):
    project_id: str = Field(min_length=1)
    workflow: WorkflowSpecRequest
    launch: LaunchSpecRequest
