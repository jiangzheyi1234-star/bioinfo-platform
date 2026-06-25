"""Pydantic request models for the remote runner API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from core.contracts.workflow_design import WorkflowDesignDraftV1


class RemoteRunnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadCreateRequest(RemoteRunnerRequest):
    filename: str = Field(min_length=1)
    contentBase64: str = Field(min_length=1)
    mimeType: str = "application/octet-stream"


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


class RunCreateRequest(RemoteRunnerRequest):
    serverId: str = Field(min_length=1)
    requestId: str | None = None
    runSpec: RunSpecRequest


class RunRetryRequest(RemoteRunnerRequest):
    scope: Literal["run"] = "run"
    actor: str | None = None
    reason: str | None = None


class RunRuleRetryRequest(RemoteRunnerRequest):
    confirmation: Literal["retry-failed-rules"]
    planHash: str = Field(min_length=64, max_length=64)
    actor: str | None = None
    reason: str | None = None


class RunResumeRequest(RemoteRunnerRequest):
    confirmation: Literal["resume-run"]
    planHash: str = Field(min_length=64, max_length=64)
    actor: str | None = None
    reason: str | None = None


class ResultPackageExportRequest(RemoteRunnerRequest):
    includeArtifacts: StrictBool
    actor: str | None = None


class ResultPackageRetireRequest(RemoteRunnerRequest):
    confirmation: Literal["retire-result-package-export"]
    actor: str | None = None
    reason: str | None = None


class ResultPackageByteDeleteRequest(RemoteRunnerRequest):
    confirmation: Literal["delete-result-package-export-bytes"]
    actor: str | None = None
    reason: str | None = None


TriggerSourceType = Literal["manual", "cron", "webhook", "dataset", "file", "database_ready", "backfill"]
BackfillPartitionUnit = Literal["hour", "day"]
BackfillRunOrder = Literal["forward", "backward"]
BackfillReprocessBehavior = Literal["none", "failed", "completed"]
ReadinessResourceType = Literal["dataset", "file", "database"]
ReadinessState = Literal["ready"]


class WorkflowTriggerCreateRequest(RemoteRunnerRequest):
    name: str = Field(min_length=1)
    sourceType: TriggerSourceType
    serverId: str = Field(min_length=1)
    runSpec: RunSpecRequest
    triggerSpec: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowTriggerEventRequest(RemoteRunnerRequest):
    eventType: str = Field(default="manual", min_length=1)
    externalEventId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    cursor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerInboxEventRequest(RemoteRunnerRequest):
    eventType: str = Field(default="webhook", min_length=1)
    source: str = Field(min_length=1)
    eventId: str = Field(min_length=1)
    correlationId: str | None = None
    actor: str | None = None
    cursor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerInboxReplayRequest(RemoteRunnerRequest):
    confirmation: Literal["replay-dead-lettered-inbox-event"]
    actor: str | None = None
    reason: str | None = None


class WorkflowTriggerReadinessEventRequest(RemoteRunnerRequest):
    source: str = Field(min_length=1)
    eventId: str = Field(min_length=1)
    resourceType: ReadinessResourceType
    resourceId: str = Field(min_length=1)
    state: ReadinessState = "ready"
    uri: str | None = None
    version: str | None = None
    checksum: str | None = None
    observedAt: str | None = None
    cursor: str | None = None
    actor: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerBackfillPreviewRequest(RemoteRunnerRequest):
    rangeStart: str = Field(min_length=1)
    rangeEnd: str = Field(min_length=1)
    partitionUnit: BackfillPartitionUnit = "day"
    timezone: str = Field(default="UTC", min_length=1)
    maxPartitions: int = Field(default=100, ge=1, le=1000)
    concurrencyLimit: int = Field(default=1, ge=1, le=100)
    runOrder: BackfillRunOrder = "forward"
    reprocessBehavior: BackfillReprocessBehavior = "none"
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerBackfillLaunchRequest(WorkflowTriggerBackfillPreviewRequest):
    previewId: str = Field(min_length=1)
    confirmation: Literal["launch-backfill"]
    actor: str | None = None


class WorkflowBackfillCancelRequest(RemoteRunnerRequest):
    confirmation: Literal["cancel-backfill"]
    actor: str | None = None


class ArtifactGcPreviewRequest(RemoteRunnerRequest):
    retentionDays: int = Field(default=30, ge=0)
    eligibleRunStatuses: list[str] = Field(
        default_factory=lambda: ["completed", "failed", "canceled", "cancelled"],
        min_length=1,
    )
    maxDeleteBytes: int | None = Field(default=None, ge=1)
    reason: str = Field(default="retention_expired", min_length=1)
    actor: str | None = None


class ArtifactGcRunRequest(ArtifactGcPreviewRequest):
    confirmation: str = Field(min_length=1)


class ArtifactCacheLookupRequest(RemoteRunnerRequest):
    workflowRevisionId: str = Field(min_length=1)
    artifactKey: str = Field(min_length=1)
    stepId: str | None = None
    role: str = Field(default="output", min_length=1)
    inputs: list[dict[str, Any]] | dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    resourceBindings: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None


class ArtifactCachePinRetainRequest(RemoteRunnerRequest):
    ownerId: str | None = None
    reason: str = Field(default="operator-retain", min_length=1)
    expiresAt: str | None = None
    actor: str | None = None


class ArtifactCachePinReleaseRequest(RemoteRunnerRequest):
    confirmation: Literal["release-artifact-cache-policy-pin"]
    reason: str | None = None
    actor: str | None = None


class ToolManifestRequest(RemoteRunnerRequest):
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


class ToolRuleTemplateRequest(RemoteRunnerRequest):
    ruleTemplate: dict[str, Any] = Field(default_factory=dict)


class ToolProductionEvidenceRequest(RemoteRunnerRequest):
    runId: str | None = None
    message: str | None = None
    logPath: str | None = None
    evidenceType: str | None = None
    targetPlatform: str | None = None
    environmentLock: dict[str, Any] | None = None
    inputScope: dict[str, Any] | None = None
    artifactDigest: str | None = None
    policyVersion: str | None = None
    databaseId: str | None = None
    templateId: str | None = None
    role: str | None = None
    artifactName: str | None = None
    packId: str | None = None
    packChecksum: str | None = None


class DatabaseManifestRequest(RemoteRunnerRequest):
    id: str | None = None
    name: str = Field(min_length=1)
    templateId: str = Field(min_length=1)
    type: str | None = None
    version: str | None = None
    path: str = Field(min_length=1)
    databaseLayer: str | None = None
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
