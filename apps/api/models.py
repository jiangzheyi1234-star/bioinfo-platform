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


class SubmitExecutionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    input_data_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sample_id: str = ""
    sample_name: str = ""
    sample_source: str = ""
    sample_metadata: dict[str, Any] = Field(default_factory=dict)
    triggered_by: str = "api"
    database_paths: dict[str, str] = Field(default_factory=dict)


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


class RunWorkbenchToolRequest(BaseModel):
    project_id: str = Field(min_length=1)
    task_id: str | None = None
    tool_id: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class RemoteEnvInstallRequest(BaseModel):
    target: Literal["miniforge", "tool_env"]
    tool_id: str | None = None


class DatabaseInstallRequest(BaseModel):
    mirror_index: int = Field(default=0, ge=0)
