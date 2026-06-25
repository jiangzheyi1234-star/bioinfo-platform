import type { WorkflowRunRuleEvent, WorkflowRunSourceLocation } from "./workflows-page-model";

export type WorkflowArtifact = {
  artifactId: string;
  kind: string;
  mimeType: string;
  sizeBytes: number;
  sha256?: string;
};

export type WorkflowRunExecutionJob = {
  jobId?: string;
  runId?: string;
  state?: string;
  queueName?: string;
  priority?: number;
  availableAt?: string;
  waitReason?: Record<string, unknown>;
  attemptCount?: number;
  maxAttempts?: number;
  retryPolicy?: Record<string, unknown>;
  timeoutPolicy?: Record<string, unknown>;
  deadLetteredAt?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type WorkflowRunExecutionAttempt = {
  attemptId?: string;
  runId?: string;
  jobId?: string;
  leaseGeneration?: number;
  attemptNumber?: number;
  state?: string;
  workerId?: string;
  sessionId?: string;
  slotId?: string;
  cancelRequestedAt?: string | null;
  killedAt?: string | null;
  outputAdoptionState?: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number | null;
  fencedReason?: string | null;
  createdAt?: string;
  updatedAt?: string;
};

export type WorkflowRunExecutionLease = {
  runId?: string;
  attemptId?: string;
  leaseGeneration?: number;
  workerId?: string;
  sessionId?: string;
  slotId?: string;
  heartbeatAt?: string;
  expiresAt?: string;
  state?: string;
  updatedAt?: string;
};

export type WorkflowRunRetryEligibility = {
  eligible?: boolean;
  eligibleNow?: boolean;
  remainingAttempts?: number;
  nextAttemptAt?: string | null;
  reasonCode?: string;
};

export type WorkflowRunRuleRetryPlanRuleRef = {
  runRuleId?: string;
  ruleName?: string;
  stepId?: string;
  runtimeStatusKey?: string;
  status?: string;
  attemptId?: string;
  leaseGeneration?: number;
  attemptNumber?: number;
};

export type WorkflowRunRuleSelectedAttempt = {
  attemptId?: string;
  attemptNumber?: number;
  leaseGeneration?: number;
  status?: string;
};

export type WorkflowRunRuleAttemptSelection = WorkflowRunRuleRetryPlanRuleRef & {
  schemaVersion?: string;
  strategy?: string;
  selected?: boolean;
  reasonCode?: string;
};

export type WorkflowRunRuleAdoptionBoundary = {
  cacheAdoptionAllowed?: boolean;
  artifactAdoptionAllowed?: boolean;
  upstreamArtifactsPreserved?: boolean;
  downstreamArtifactsInvalidated?: boolean;
  adoptedArtifacts?: unknown[];
  adoptedCacheEntries?: unknown[];
  blockedReasonCodes?: string[];
};

export type WorkflowRunRuleRetryPlanItem = WorkflowRunRuleRetryPlanRuleRef & {
  eligible?: boolean;
  eligibleNow?: boolean;
  reasonCode?: string;
  selectionReasonCode?: string;
  selectedAttempt?: WorkflowRunRuleSelectedAttempt;
  invalidatesOwnOutputs?: boolean;
  attemptSelection?: WorkflowRunRuleAttemptSelection;
  adoptionBoundary?: WorkflowRunRuleAdoptionBoundary;
  downstreamInvalidation?: {
    ruleCount?: number;
    rules?: WorkflowRunRuleRetryPlanRuleRef[];
  };
  rerunScope?: {
    ruleCount?: number;
    rules?: WorkflowRunRuleRetryPlanRuleRef[];
  };
};

export type WorkflowRunAdoptionBoundary = {
  schemaVersion?: string;
  kind?: string;
  enabled?: boolean;
  adoptedArtifacts?: unknown[];
  adoptedCacheEntries?: unknown[];
  reasonCode?: string;
  message?: string;
  requires?: string[];
};

export type WorkflowRunRuleRetryPlan = {
  schemaVersion?: string;
  runId?: string;
  workflowRevisionId?: string | null;
  supported?: boolean;
  eligible?: boolean;
  eligibleNow?: boolean;
  executionEnabled?: boolean;
  executionReasonCode?: string;
  selectionMode?: string;
  ruleCount?: number;
  failedRuleCount?: number;
  selectedAttemptCount?: number;
  invalidationPlanAvailable?: boolean;
  cacheAdoptionBoundary?: WorkflowRunAdoptionBoundary;
  artifactAdoptionBoundary?: WorkflowRunAdoptionBoundary;
  preservedRules?: WorkflowRunRuleRetryPlanRuleRef[];
  invalidatedRules?: WorkflowRunRuleRetryPlanRuleRef[];
  adoptedArtifacts?: unknown[];
  adoptedCacheEntries?: unknown[];
  blockedReasonCodes?: string[];
  reasonCode?: string;
  message?: string;
  rules?: WorkflowRunRuleRetryPlanItem[];
};

export type WorkflowRunRuleRetrySnakemakeOptions = {
  schemaVersion?: string;
  rerunIncomplete?: boolean;
  forcerunRules?: string[];
  argsPreview?: string[];
  unsafeFlagsProhibited?: string[];
};

export type WorkflowRunRuleCacheRestorePlan = {
  schemaVersion?: string;
  planHash?: string;
  reasonCode?: string;
  outputCount?: number;
  cacheHitCount?: number;
  cacheMissCount?: number;
  blockedReasonCodes?: string[];
  redactionPolicy?: {
    cacheKeysExposed?: boolean;
    cacheKeyFingerprintsExposed?: boolean;
    keyPayloadsExposed?: boolean;
    storageUrisExposed?: boolean;
    pathsExposed?: boolean;
  };
  stagedFilePolicy?: {
    reasonCode?: string;
    previewAvailable?: boolean;
    blockedReasonCodes?: string[];
    overwriteAllowed?: boolean;
    deleteUnknownOutputs?: boolean;
    pinCreationAllowed?: boolean;
    pathExposed?: boolean;
    storageUriExposed?: boolean;
    cacheKeyExposed?: boolean;
    unknownOutputHandling?: string;
    unknownOutputScanAvailable?: boolean;
    managedTargetCount?: number;
    targetCount?: number;
    selectedOutputCount?: number;
    downstreamOutputCount?: number;
    cacheHitTargetCount?: number;
    cacheMissTargetCount?: number;
    unmappedTargetCount?: number;
    unknownOutputCount?: number;
    restorePinnedCount?: number;
  };
  rules?: Array<
    WorkflowRunRuleRetryPlanRuleRef & {
      outputs?: Array<{
        artifactKey?: string | null;
        stepId?: string;
        cacheKeyPresent?: boolean;
        cacheKeyFingerprint?: string;
        cacheHit?: boolean;
        cacheReason?: string;
        blockedReasonCodes?: string[];
        restoreTarget?: {
          pathExposed?: boolean;
          reasonCode?: string;
        };
      }>;
    }
  >;
};

export type WorkflowRunRuleOutputInvalidationPlan = {
  schemaVersion?: string;
  runId?: string;
  workflowRevisionId?: string | null;
  planHash?: string;
  supported?: boolean;
  eligible?: boolean;
  eligibleNow?: boolean;
  invalidationEnabled?: boolean;
  sideEffectFree?: boolean;
  pathExposed?: boolean;
  storageReferenceExposed?: boolean;
  reasonCode?: string;
  message?: string;
  previewAvailable?: boolean;
  blockedReasonCodes?: string[];
  mutationPolicy?: {
    tombstoneOutputEdges?: boolean;
    tombstoneLineageEdges?: boolean;
    deleteArtifactPayloads?: boolean;
    checksumAuditRequired?: boolean;
    requiredGovernanceEvidence?: string[];
  };
  outputEdgeSummary?: {
    outputEdgeCount?: number;
    invalidatedOutputEdgeCount?: number;
    selectedOutputEdgeCount?: number;
    downstreamOutputEdgeCount?: number;
    preservedOutputEdgeCount?: number;
    unmatchedOutputEdgeCount?: number;
    invalidatedLineageEdgeCount?: number;
    payloadDeletionAllowed?: boolean;
    lineageMutationAllowed?: boolean;
    preservedLineageEdgeCount?: number;
    alreadyInvalidatedOutputEdgeCount?: number;
    alreadyInvalidatedLineageEdgeCount?: number;
  };
  outputInvalidationState?: {
    schemaVersion?: string;
    state?: string;
    appliedOutputEdgeCount?: number;
    appliedLineageEdgeCount?: number;
    evidenceEventCount?: number;
    latestAppliedAt?: string | null;
  };
  rules?: Array<
    WorkflowRunRuleRetryPlanRuleRef & {
      invalidationRole?: string;
      outputEdgeCount?: number;
      lineageEdgeCount?: number;
      outputs?: Array<{
        portName?: string;
        stepId?: string;
        lineageEdgeCount?: number;
        wouldDeletePayload?: boolean;
      }>;
    }
  >;
};

export type WorkflowRunRuleOutputInvalidationApplyResult = {
  schemaVersion?: string;
  runId?: string;
  planHash?: string;
  status?: string;
  evidenceId?: string;
  invalidatedOutputEdgeCount?: number;
  invalidatedLineageEdgeCount?: number;
  payloadDeleted?: boolean;
  appliedAt?: string;
};

export type WorkflowRunRuleRetryExecutionPlan = {
  schemaVersion?: string;
  planHash?: string;
  sourcePlanSchemaVersion?: string;
  runId?: string;
  workflowRevisionId?: string | null;
  supported?: boolean;
  eligible?: boolean;
  eligibleNow?: boolean;
  executionEnabled?: boolean;
  executionReasonCode?: string;
  commandPreviewAvailable?: boolean;
  attemptSelection?: Record<string, unknown>;
  cacheAdoptionBoundary?: WorkflowRunAdoptionBoundary;
  artifactAdoptionBoundary?: WorkflowRunAdoptionBoundary;
  sourceReasonCode?: string;
  sourceBlockedReasonCodes?: string[];
  blockedReasonCodes?: string[];
  requiresBeforeExecution?: string[];
  selectedRules?: Array<WorkflowRunRuleRetryPlanRuleRef & { selectedAttempt?: WorkflowRunRuleSelectedAttempt }>;
  rerunScope?: {
    ruleCount?: number;
    rules?: WorkflowRunRuleRetryPlanRuleRef[];
  };
  snakemakeOptions?: WorkflowRunRuleRetrySnakemakeOptions;
  cacheRestorePlan?: WorkflowRunRuleCacheRestorePlan;
  reasonCode?: string;
  message?: string;
};

export type WorkflowRunResumeSnakemakeOptions = {
  schemaVersion?: string;
  rerunIncomplete?: boolean;
  argsPreview?: string[];
  unsafeFlagsProhibited?: string[];
};

export type WorkflowRunResumePlan = {
  schemaVersion?: string;
  planHash?: string;
  runId?: string;
  workflowRevisionId?: string | null;
  strategy?: string;
  supported?: boolean;
  eligible?: boolean;
  eligibleNow?: boolean;
  executionEnabled?: boolean;
  executionReasonCode?: string;
  commandPreviewAvailable?: boolean;
  runStatus?: string;
  jobState?: string | null;
  attemptCount?: number;
  latestAttempt?: WorkflowRunRuleSelectedAttempt & {
    state?: string;
    exitCode?: number | null;
    finishedAt?: string | null;
  } | null;
  workdirEvidence?: {
    available?: boolean;
    workDirReusable?: boolean;
    pathExposed?: boolean;
    reasonCode?: string;
  };
  incompleteOutputAudit?: {
    schemaVersion?: string;
    available?: boolean;
    pathExposed?: boolean;
    configAvailable?: boolean;
    expectedOutputCount?: number;
    checkedOutputCount?: number;
    existingOutputCount?: number;
    missingOutputCount?: number;
    unsafeOutputCount?: number;
    uncheckedOutputCount?: number;
    unverifiedOutputCount?: number;
    outputs?: Array<{
      key?: string;
      state?: string;
      pathExposed?: boolean;
      reasonCode?: string;
      sizeBytes?: number;
      directory?: boolean;
    }>;
    reasonCode?: string;
  };
  artifactAdoptionBoundary?: WorkflowRunAdoptionBoundary;
  blockedReasonCodes?: string[];
  requiresBeforeExecution?: string[];
  snakemakeOptions?: WorkflowRunResumeSnakemakeOptions;
  reasonCode?: string;
  message?: string;
};

export type WorkflowRunFailureLocator = {
  schemaVersion?: string;
  runId?: string;
  status?: string;
  stage?: string;
  workflowRevisionId?: string;
  available?: boolean;
  reasonCode?: "RUN_NOT_FAILED" | "RUN_FAILED_NO_RULE" | "FAILED_RULE" | string;
  message?: string;
  failedRule?: WorkflowRunRuleRetryPlanRuleRef & {
    startedAt?: string;
    finishedAt?: string;
    exitCode?: number | null;
    message?: string;
    inputCount?: number;
    outputCount?: number;
    logReferenceCount?: number;
    wildcards?: Record<string, unknown>;
    sourceLocation?: WorkflowRunSourceLocation | null;
    latestFailureEvent?: WorkflowRunRuleEvent | null;
  };
  runEvent?: WorkflowRunRuleEvent | null;
  logContext?: {
    stdoutLineCount?: number;
    stderrLineCount?: number;
    stderrTail?: string[];
  };
  ruleLogContext?: WorkflowRunRuleLogContext;
  artifactContext?: {
    artifactCount?: number;
    relatedArtifactCount?: number;
    relatedArtifacts?: WorkflowArtifact[];
    lineageEdgeCount?: number;
    lineageEdges?: unknown[];
  };
  redactionPolicy?: {
    artifactPathsExposed?: boolean;
    storageUrisExposed?: boolean;
    commandSummaryExposed?: boolean;
    eventDetailsSanitized?: boolean;
    sourceLocationsSanitized?: boolean;
    runSpecExposed?: boolean;
  };
};

export type WorkflowRunRuleLogContext = {
  schemaVersion?: string;
  status?: "available" | "unavailable" | string;
  reasonCode?:
    | "PREVIEW_AVAILABLE"
    | "NO_FAILED_RULE"
    | "NO_RULE_LOGS"
    | "PATH_REFERENCE_ONLY"
    | "MATCHED_ARTIFACT_NOT_PREVIEWABLE"
    | "RESULT_ID_MISSING"
    | "PREVIEW_UNAVAILABLE"
    | string;
  message?: string;
  logReferenceCount?: number;
  matchedArtifactCount?: number;
  matchedArtifacts?: WorkflowArtifact[];
  selectedArtifact?: WorkflowArtifact;
  previewKind?: string;
  lineCount?: number;
  tail?: string[];
  truncated?: boolean;
};

export type WorkflowRunExecutionContext = {
  schemaVersion?: string;
  runId?: string;
  generatedAt?: string;
  run?: {
    status?: string;
    stage?: string;
    stateVersion?: number;
    message?: string;
    startedAt?: string;
    finishedAt?: string;
    lastUpdatedAt?: string;
  };
  job?: WorkflowRunExecutionJob | null;
  attempts?: WorkflowRunExecutionAttempt[];
  currentLease?: WorkflowRunExecutionLease | null;
  activeLease?: WorkflowRunExecutionLease | null;
  retryPolicy?: Record<string, unknown> | null;
  timeoutPolicy?: Record<string, unknown> | null;
  retryEligibility?: WorkflowRunRetryEligibility;
  ruleRetryPlan?: WorkflowRunRuleRetryPlan;
  ruleCacheRestorePlan?: WorkflowRunRuleCacheRestorePlan;
  ruleOutputInvalidationPlan?: WorkflowRunRuleOutputInvalidationPlan;
  ruleRetryExecutionPlan?: WorkflowRunRuleRetryExecutionPlan;
  resumeSupported?: boolean;
  resumeEligibility?: {
    eligible?: boolean;
    eligibleNow?: boolean;
    reasonCode?: string;
    message?: string;
  };
  resumePlan?: WorkflowRunResumePlan;
};

export type WorkflowInputArtifactPort = {
  artifactId?: string;
  filename?: string;
  inputIndex?: number | null;
  inputName?: string;
  inputRole?: string;
  lineageEdgeId?: string;
  portName?: string;
  runArtifactEdgeId?: string;
  sourceId?: string;
  sourceMaterializationId?: string;
  sourceStorageBackend?: string;
  sourceType?: string;
  upstreamRunId?: string;
  uploadId?: string;
};

export type WorkflowInputArtifact = {
  artifactBlobId: string;
  mimeType?: string;
  ports?: WorkflowInputArtifactPort[];
  sha256?: string;
  sizeBytes?: number | null;
};
