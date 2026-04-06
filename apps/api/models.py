"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    open_after_create: bool = True


class CreateSampleRequest(BaseModel):
    name: str = Field(min_length=1)
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitExecutionRequest(BaseModel):
    project_id: str = Field(min_length=1)
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


class RunWorkbenchToolRequest(BaseModel):
    project_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
