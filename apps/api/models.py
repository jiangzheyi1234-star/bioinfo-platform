"""Pydantic models for API contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter

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
    sampleDataPrepProof: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    workflowDesign: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None


class RunSubmitRequest(ApiRequest):
    serverId: str = Field(min_length=1)
    runId: str | None = None
    requestId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    runSpec: RunSpecRequest


class RunRetryRequest(ApiRequest):
    scope: Literal["run"] = "run"
    actor: str | None = None
    reason: str | None = None


class RunRuleRetryRequest(ApiRequest):
    confirmation: Literal["retry-failed-rules"]
    planHash: str = Field(min_length=64, max_length=64)
    actor: str | None = None
    reason: str | None = None


class RunRuleOutputInvalidationApplyRequest(ApiRequest):
    confirmation: Literal["apply-rule-output-invalidation"]
    planHash: str = Field(min_length=64, max_length=64)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestorePinPrepareRequest(ApiRequest):
    confirmation: Literal["prepare-rule-cache-restore-pins"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestorePinApplyRequest(ApiRequest):
    confirmation: Literal["apply-rule-cache-restore-pins"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreStagedFilePrepareRequest(ApiRequest):
    confirmation: Literal["prepare-rule-cache-restore-staged-files"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreStagedFileApplyRequest(ApiRequest):
    confirmation: Literal["apply-rule-cache-restore-staged-files"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreFinalOutputPrepareRequest(ApiRequest):
    confirmation: Literal["prepare-rule-cache-restore-final-outputs"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreFinalOutputApplyRequest(ApiRequest):
    confirmation: Literal["apply-rule-cache-restore-final-outputs"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreAdoptionPrepareRequest(ApiRequest):
    confirmation: Literal["prepare-rule-cache-restore-adoption"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunRuleCacheRestoreAdoptionApplyRequest(ApiRequest):
    confirmation: Literal["apply-rule-cache-restore-adoption"]
    planHash: str = Field(min_length=64, max_length=64)
    attemptId: str = Field(min_length=1)
    leaseGeneration: int = Field(ge=1)
    actor: str | None = None
    reason: str | None = None


class RunResumeRequest(ApiRequest):
    confirmation: Literal["resume-run"]
    planHash: str = Field(min_length=64, max_length=64)
    actor: str | None = None
    reason: str | None = None


class ResultPackageExportRequest(ApiRequest):
    serverId: str | None = None
    includeArtifacts: StrictBool
    actor: str | None = None


class ResultPackageRetireRequest(ApiRequest):
    serverId: str | None = None
    confirmation: Literal["retire-result-package-export"]
    actor: str | None = None
    reason: str | None = None


class ResultPackageByteGcPreviewRequest(ApiRequest):
    serverId: str | None = None
    retentionDays: int = Field(default=30, ge=0)
    maxDeleteBytes: int | None = Field(default=None, ge=1)
    scanLimit: int = Field(default=1000, ge=1, le=5000)
    actor: str | None = None
    reason: str | None = None


class ResultPackageByteGcRunRequest(ResultPackageByteGcPreviewRequest):
    confirmation: Literal["run-result-package-byte-gc"]
    planFingerprint: str = Field(min_length=1)


TriggerSourceType = Literal["manual", "cron", "webhook", "dataset", "file", "database_ready", "backfill"]
BackfillPartitionUnit = Literal["hour", "day"]
BackfillRunOrder = Literal["forward", "backward"]
BackfillReprocessBehavior = Literal["none", "failed", "completed"]
ReadinessResourceType = Literal["dataset", "file", "database"]
ReadinessState = Literal["ready"]


class WorkflowTriggerCreateRequest(ApiRequest):
    name: str = Field(min_length=1)
    sourceType: TriggerSourceType
    serverId: str = Field(min_length=1)
    runSpec: RunSpecRequest
    triggerSpec: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowTriggerEventRequest(ApiRequest):
    eventType: str = Field(default="manual", min_length=1)
    externalEventId: str | None = None
    idempotencyKey: str | None = Field(default=None, min_length=1)
    cursor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerInboxEventRequest(ApiRequest):
    eventType: str = Field(default="webhook", min_length=1)
    source: str = Field(min_length=1)
    eventId: str = Field(min_length=1)
    correlationId: str | None = None
    actor: str | None = None
    cursor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTriggerInboxReplayRequest(ApiRequest):
    confirmation: Literal["replay-dead-lettered-inbox-event"]
    actor: str | None = None
    reason: str | None = None


class WorkflowTriggerReadinessEventRequest(ApiRequest):
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


class WorkflowTriggerBackfillPreviewRequest(ApiRequest):
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


class WorkflowTriggerSchedulerRunOnceRequest(ApiRequest):
    serverId: str | None = None
    confirmation: Literal["run-scheduler-once"]
    limit: int = Field(default=100, ge=1, le=100)
    actor: str | None = None
    reason: str | None = None


class WorkflowBackfillCancelRequest(ApiRequest):
    serverId: str | None = None
    confirmation: Literal["cancel-backfill"]
    actor: str | None = None


class ArtifactGcPreviewRequest(ApiRequest):
    serverId: str | None = None
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
    planFingerprint: str = Field(min_length=1)


class ArtifactLifecycleControllerRunOnceRequest(ApiRequest):
    serverId: str | None = None
    confirmation: Literal["run-artifact-lifecycle-controller-once"]
    retentionDays: int = Field(default=30, ge=0)
    eligibleRunStatuses: list[str] = Field(
        default_factory=lambda: ["completed", "failed", "canceled", "cancelled"],
        min_length=1,
    )
    quotaBytes: int | None = Field(default=None, ge=0)
    maxDeleteBytesPerTick: int | None = Field(default=None, ge=1)
    actor: str | None = None
    reason: str | None = None


class ArtifactCacheLookupRequest(ApiRequest):
    serverId: str | None = None
    workflowRevisionId: str = Field(min_length=1)
    artifactKey: str = Field(min_length=1)
    stepId: str | None = None
    role: str = Field(default="output", min_length=1)
    inputs: list[dict[str, Any]] | dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    resourceBindings: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None


class ArtifactCachePinRetainRequest(ApiRequest):
    serverId: str | None = None
    ownerId: str | None = None
    reason: str = Field(default="operator-retain", min_length=1)
    expiresAt: str | None = None
    actor: str | None = None


class ArtifactCachePinReleaseRequest(ApiRequest):
    serverId: str | None = None
    confirmation: Literal["release-artifact-cache-policy-pin"]
    reason: str | None = None
    actor: str | None = None


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


class DatabaseManifestRequest(ApiRequest):
    serverId: str | None = None
    id: str | None = None
    name: str = Field(min_length=1)
    templateId: str = Field(min_length=1)
    type: str | None = None
    version: str | None = None
    path: str = Field(min_length=1)
    selectedEntryPath: str | None = None
    databaseLayer: str | None = None
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


class DatabasePackReadyScanRequest(ApiRequest):
    serverId: str | None = None
    packId: str = Field(min_length=1)
    readyPath: str | None = Field(default=None, min_length=1)
    fieldPaths: dict[str, str] | None = None


class WorkflowDesignRequest(ApiRequest):
    model_config = ConfigDict(extra="forbid", strict=True)

    def runtime_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_defaults=True, exclude_none=True, mode="json")


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
