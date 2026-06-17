"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from core.contracts.workflow_design import WorkflowDesignDraftV1


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


class TerminalInputMessage(ApiRequest):
    type: Literal["input"]
    data: str = Field(min_length=1)


class TerminalResizeMessage(ApiRequest):
    type: Literal["resize"]
    cols: int = Field(default=120, ge=40, le=240)
    rows: int = Field(default=28, ge=12, le=80)


class TerminalPingMessage(ApiRequest):
    type: Literal["ping"]


class TerminalSessionSnapshot(ApiRequest):
    session_id: str = Field(min_length=1)
    cursor: int = Field(ge=0)
    output: str
    connected: bool
    input_enabled: bool
    closed: bool
    message: str
    created_at: float
    closed_at: float | None

    @property
    def state_key(self) -> tuple[bool, bool, str]:
        return self.connected, self.input_enabled, self.message


TerminalClientMessage: TypeAlias = Annotated[
    TerminalInputMessage | TerminalResizeMessage | TerminalPingMessage,
    Field(discriminator="type"),
]
TERMINAL_CLIENT_MESSAGE_ADAPTER = TypeAdapter(TerminalClientMessage)


class RunSpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipelineId: str = Field(min_length=1)
    projectId: str | None = None
    pipelineVersion: str | None = None
    runId: str | None = None
    runSpecVersion: str | None = None
    workflowRevisionId: str | None = None
    inputs: list[dict[str, Any]] | None = None
    params: dict[str, Any] | None = None
    resourceBindings: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    workflowDesign: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None


class RunSubmitRequest(ApiRequest):
    serverId: str = Field(min_length=1)
    runId: str | None = None
    requestId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    runSpec: RunSpecRequest


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
    profileId: str | None = None
    profileVersion: int | None = None
    packId: str | None = None
    packageName: str | None = None
    validationTarget: str | None = None
    latestVersion: str | None = None
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

    def runtime_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


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
