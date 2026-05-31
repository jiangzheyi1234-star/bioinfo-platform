"""Pydantic request models for the remote runner API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .workflow_design_contract import WorkflowDesignDraftV1


class RemoteRunnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadCreateRequest(RemoteRunnerRequest):
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


class RunCreateRequest(RemoteRunnerRequest):
    serverId: str = Field(min_length=1)
    requestId: str | None = None
    runSpec: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_run_spec_server_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            run_spec = data.get("runSpec")
            if isinstance(run_spec, dict) and "serverId" in run_spec:
                raise ValueError(
                    "UNSUPPORTED_LEGACY_PAYLOAD: runSpec.serverId is not supported; use top-level serverId"
                )
        return data


class ToolManifestRequest(RemoteRunnerRequest):
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


class ToolRuleTemplateRequest(RemoteRunnerRequest):
    ruleTemplate: dict[str, Any] = Field(default_factory=dict)


class ToolProductionEvidenceRequest(RemoteRunnerRequest):
    runId: str | None = None
    message: str | None = None
    logPath: str | None = None
    evidenceType: str | None = None
    databaseId: str | None = None
    templateId: str | None = None
    role: str | None = None
    artifactName: str | None = None


class DatabaseManifestRequest(RemoteRunnerRequest):
    id: str | None = None
    name: str = Field(min_length=1)
    templateId: str = Field(min_length=1)
    type: str | None = None
    version: str | None = None
    path: str = Field(min_length=1)
    description: str | None = None
    source: str | None = None
    manifestPath: str | None = None
    sizeBytes: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    metadata: dict[str, Any] | None = None


class DatabaseUpdateRequest(RemoteRunnerRequest):
    name: str | None = Field(default=None, min_length=1)
    version: str | None = None
    description: str | None = None


class WorkflowDesignRequest(RemoteRunnerRequest):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowDesignDraftCreateRequest(WorkflowDesignRequest):
    draft: WorkflowDesignDraftV1


class WorkflowDesignDraftUpdateRequest(WorkflowDesignRequest):
    draft: WorkflowDesignDraftV1
    expectedRevision: int | None = Field(default=None, ge=1)


class WorkflowDesignDraftForkRequest(WorkflowDesignRequest):
    name: str | None = Field(default=None, min_length=1)


class WorkflowDesignDraftPlanRequest(WorkflowDesignRequest):
    pass


class WorkflowDesignDraftCompileRequest(WorkflowDesignRequest):
    pass
