"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    open_after_create: bool = True


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class UpdateSettingsRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


class SSHConnectionRequest(BaseModel):
    auth_mode: Literal["password_ref", "key_file", "ssh_config", "agent"] | None = None
    ssh_host_alias: str | None = None
    identity_ref: str | None = None
    remember_auth: bool | None = None
    auto_connect_on_startup: bool | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    password: str | None = None
    timeout_sec: int = Field(default=5, ge=1, le=60)


class SSHTerminalCreateRequest(BaseModel):
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=28, ge=12, le=80)


class RunSubmitRequest(BaseModel):
    serverId: str = Field(min_length=1)
    runId: str | None = None
    requestId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    pipelineId: str | None = None
    runSpec: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pipeline_binding(self) -> "RunSubmitRequest":
        pipeline_id = (self.pipelineId or "").strip()
        run_spec_pipeline_id = str(self.runSpec.get("pipelineId") or "").strip()
        if not pipeline_id and not run_spec_pipeline_id:
            raise ValueError("pipelineId is required")
        return self


class UploadSubmitRequest(BaseModel):
    serverId: str | None = None
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


class ToolManifestRequest(BaseModel):
    serverId: str | None = None
    id: str | None = None
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    sourceLabel: str | None = None
    version: str | None = None
    packageSpec: str | None = None
    summary: str | None = None
    targetPlatform: str | None = None
    targetPlatformSupported: bool = False
    platforms: list[str] = Field(default_factory=list)
    sourceUrl: str | None = None
    testCommand: str | None = None
    ruleTemplate: dict[str, Any] | None = None
    capabilities: list[dict[str, Any]] = Field(default_factory=list)


class DatabaseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serverId: str | None = None
    id: str | None = None
    name: str = Field(min_length=1)
    templateId: str = Field(min_length=1)
    type: str | None = None
    version: str | None = None
    path: str = Field(min_length=1)
    selectedEntryPath: str | None = None
    description: str | None = None
    source: str | None = None
    manifestPath: str | None = None
    sizeBytes: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    metadata: dict[str, Any] | None = None


class DatabaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    version: str | None = None
    description: str | None = None


class WorkflowDraftRequest(BaseModel):
    templateId: str = Field(min_length=1)
    name: str | None = None
    modules: list[dict[str, Any]] | None = None
