"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator

from apps.remote_runner.workflow_design_contract import WorkflowDesignDraftV1


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SSHConnectionRequest(ApiRequest):
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


class SSHTerminalCreateRequest(ApiRequest):
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=28, ge=12, le=80)


class RunSubmitRequest(ApiRequest):
    serverId: str = Field(min_length=1)
    runId: str | None = None
    requestId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    runSpec: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_payload_shape(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "pipelineId" in data:
                raise ValueError(
                    "UNSUPPORTED_LEGACY_PAYLOAD: top-level pipelineId is not supported; use runSpec.pipelineId"
                )
            run_spec = data.get("runSpec")
            if isinstance(run_spec, dict) and "serverId" in run_spec:
                raise ValueError(
                    "UNSUPPORTED_LEGACY_PAYLOAD: runSpec.serverId is not supported; use top-level serverId"
                )
        return data

    @model_validator(mode="after")
    def validate_pipeline_binding(self) -> "RunSubmitRequest":
        run_spec_pipeline_id = str(self.runSpec.get("pipelineId") or "").strip()
        if not run_spec_pipeline_id:
            raise ValueError("pipelineId is required")
        return self


class UploadSubmitRequest(ApiRequest):
    serverId: str | None = None
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


class ToolManifestRequest(ApiRequest):
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
    ruleSpecDraft: dict[str, Any] | None = None
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    snakemakeWrappers: list[dict[str, Any]] = Field(default_factory=list)
    snakemakeWrapperCount: int = 0


class ToolRuleTemplateRequest(ApiRequest):
    serverId: str | None = None
    ruleTemplate: dict[str, Any] = Field(default_factory=dict)


class ToolProductionEvidenceRequest(ApiRequest):
    serverId: str | None = None
    runId: str | None = None
    message: str | None = None
    logPath: str | None = None
    evidenceType: str | None = None
    databaseId: str | None = None
    templateId: str | None = None
    role: str | None = None
    artifactName: str | None = None


class DatabaseManifestRequest(ApiRequest):
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


class DatabaseUpdateRequest(ApiRequest):
    name: str | None = Field(default=None, min_length=1)
    version: str | None = None
    description: str | None = None


class WorkflowDesignRequest(ApiRequest):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowDesignDraftCreateRequest(WorkflowDesignRequest):
    serverId: str | None = None
    draft: WorkflowDesignDraftV1


class WorkflowDesignDraftUpdateRequest(WorkflowDesignRequest):
    serverId: str | None = None
    draft: WorkflowDesignDraftV1
    expectedRevision: int | None = Field(default=None, ge=1)


class WorkflowDesignDraftForkRequest(WorkflowDesignRequest):
    serverId: str | None = None
    name: str | None = Field(default=None, min_length=1)


class WorkflowDesignDraftPlanRequest(WorkflowDesignRequest):
    serverId: str | None = None


class WorkflowDesignDraftCompileRequest(WorkflowDesignRequest):
    serverId: str | None = None
