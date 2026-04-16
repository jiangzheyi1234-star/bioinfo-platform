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


class SSHTerminalCreateRequest(BaseModel):
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=28, ge=12, le=80)


class DatabaseInstallRequest(BaseModel):
    mirror_index: int = Field(default=0, ge=0)
