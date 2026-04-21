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


class UpdateSettingsRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


class SSHConnectionRequest(BaseModel):
    auth_mode: Literal["password_ref", "key_file", "ssh_config", "agent"] | None = None
    ssh_host_alias: str | None = None
    identity_ref: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    password: str | None = None
    timeout_sec: int = Field(default=5, ge=1, le=60)


class SSHTerminalCreateRequest(BaseModel):
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=28, ge=12, le=80)


class RunSubmitRequest(BaseModel):
    runId: str | None = None
    requestId: str | None = None
    pipelineId: str | None = None
    runSpec: dict[str, Any] = Field(default_factory=dict)


class UploadSubmitRequest(BaseModel):
    serverId: str | None = None
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"
