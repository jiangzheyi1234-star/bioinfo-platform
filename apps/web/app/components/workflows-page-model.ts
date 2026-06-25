import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import { displayRuleTemplateForTool, hasRuleAction, ruleSpecReadinessForTool } from "./tool-rule-readiness";

export type WorkflowCatalogItem = {
  id: string;
  kind: "template" | "pipeline" | string;
  name: string;
  version: string;
  category: string;
  description: string;
  engine: string;
  status: string;
  runnable: boolean;
  source: string;
  inputSchema?: Record<string, unknown>;
  paramsSchema?: Record<string, unknown>;
  outputSchema?: {
    artifacts?: Array<{ kind?: string; mimeType?: string; name?: string }>;
  };
  uiSchema?: Record<string, unknown>;
  resources?: Record<string, WorkflowResourceSpec>;
  tags?: string[];
  moduleCount?: number | null;
  inputCount?: number | null;
  outputCount?: number | null;
};

export type WorkflowResourceSpec = {
  type?: string;
  required?: boolean;
  description?: string;
  configKey?: string;
  acceptedTemplates?: string[];
  acceptedCapabilities?: string[];
};

export type WorkflowCatalogResponse = {
  data: {
    items: WorkflowCatalogItem[];
    serverReady?: boolean;
    pipelineError?: string;
  };
};

export type WorkflowServer = {
  serverId: string;
  label?: string;
  connected?: boolean;
  ready?: boolean;
  reasonCode?: string;
  message?: string;
  health?: {
    startup?: WorkflowHealthCheck;
    live?: WorkflowHealthCheck;
    ready?: WorkflowHealthCheck;
    workflowRuntime?: WorkflowRuntimeHealth;
    pipelineRegistry?: WorkflowPipelineRegistryHealth;
  };
  runner?: {
    ready?: boolean;
    message?: string;
    reasonCode?: string;
    bootstrapMetadata?: {
      workflow_profile?: {
        path?: string;
        config?: string;
        written?: boolean;
      };
      canary?: {
        ok?: boolean;
        status?: string;
        message?: string;
        submission?: {
          runId?: string;
        };
        run?: {
          runId?: string;
        };
        result?: {
          resultId?: string;
          artifactCount?: number;
        };
        preview?: unknown;
      };
    };
  };
};

export type WorkflowServersResponse = {
  data: {
    items: WorkflowServer[];
  };
};

export type WorkflowRuntimeHealth = {
  ok?: boolean;
  message?: string;
  provider?: string;
  source?: string;
  version?: string;
  snakemakeVersion?: string;
  workflowProfileConfigured?: boolean;
  workflowProfileOk?: boolean;
  workflowProfileMessage?: string;
  workflowProfileDir?: string;
  workflowProfileName?: string;
  workflowProfilePath?: string;
};

export type WorkflowPipelineRegistryHealth = {
  ok?: boolean;
  message?: string;
  count?: number;
};

export type WorkflowHealthCheck = {
  ok?: boolean;
  message?: string;
};

export type WorkflowUpload = {
  uploadId: string;
  filename: string;
  sizeBytes?: number;
  role?: string;
  sourceUrl?: string;
};

export type WorkflowRunTrigger = {
  triggerId?: string;
  triggerEventId?: string;
  source?: string;
  cursor?: string;
};

export type WorkflowRun = {
  runId: string;
  status: string;
  stage: string;
  message?: string;
  requestId?: string;
  pipelineId?: string;
  workflowRevisionId?: string;
  startedAt?: string;
  finishedAt?: string;
  submittedAt?: string;
  createdAt?: string;
  updatedAt?: string;
  trigger?: WorkflowRunTrigger | null;
  runSpec?: {
    pipelineId?: string;
    workflowRevisionId?: string;
    workflowDesign?: { draftId?: string; revision?: number };
    inputs?: Array<{
      artifactBlobId?: string;
      artifactId?: string;
      filename?: string;
      materializationId?: string;
      role?: string;
      sourceArtifactId?: string;
      uploadId?: string;
      upstreamRunId?: string;
    }>;
    params?: Record<string, unknown>;
    resourceBindings?: Record<string, string | { databaseId?: string; id?: string; templateId?: string }>;
  };
};

export type JsonSchemaProperty = {
  type?: string;
  enum?: unknown[];
  description?: string;
  default?: unknown;
  title?: string;
  minimum?: number;
  maximum?: number;
};

export type JsonSchema = {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
};

export type WorkflowRunEvent = {
  eventId?: string;
  runId?: string;
  eventType?: string;
  commandId?: string;
  status?: string;
  stage?: string;
  message?: string;
  createdAt?: string;
};

export type WorkflowLogLines = {
  lines?: string[];
  nextCursor?: string;
};

export type WorkflowRunRuleEvent = {
  ruleEventId?: string;
  runId?: string;
  runRuleId?: string;
  ruleName?: string;
  stepId?: string;
  eventType?: string;
  status?: string;
  attemptId?: string;
  leaseGeneration?: number;
  attemptNumber?: number;
  message?: string;
  createdAt?: string;
  details?: Record<string, unknown>;
};

export type WorkflowRunRule = {
  runRuleId?: string;
  runId?: string;
  ruleName: string;
  stepId?: string;
  runtimeStatusKey?: string;
  status: string;
  attemptId?: string;
  leaseGeneration?: number;
  attemptNumber?: number;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number | null;
  message?: string;
  inputCount?: number;
  outputCount?: number;
  logReferenceCount?: number;
  wildcards?: Record<string, unknown>;
  logContext?: WorkflowRunRuleLogContext;
  updatedAt?: string;
  events?: WorkflowRunRuleEvent[];
};

export type WorkflowRunRules = {
  schemaVersion?: string;
  runId?: string;
  redactionPolicy?: {
    artifactPathsExposed?: boolean;
    storageUrisExposed?: boolean;
    commandSummaryExposed?: boolean;
    ruleInputsExposed?: boolean;
    ruleOutputsExposed?: boolean;
    ruleLogPathsExposed?: boolean;
    eventDetailsSanitized?: boolean;
  };
  items?: WorkflowRunRule[];
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

export type WorkflowArtifact = {
  artifactId: string;
  kind: string;
  mimeType: string;
  sizeBytes: number;
  sha256?: string;
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

export type WorkflowArtifactDirectoryPreviewEntry = {
  path?: string;
  kind?: "file" | "directory" | string;
  sizeBytes?: number;
  sha256?: string;
};

export type WorkflowResultDetail = {
  resultId?: string;
  runId?: string;
  artifacts?: WorkflowArtifact[];
  artifactCount?: number;
  inputArtifacts?: WorkflowInputArtifact[];
  inputArtifactCount?: number;
};

export type WorkflowResultSummary = {
  resultId?: string;
  runId: string;
  title?: string;
  pipelineId?: string;
  artifactCount?: number;
  inputArtifactCount?: number;
  producedAt?: string;
};

export type WorkflowResultPackageDownload = {
  href?: string;
  filename?: string;
};

export type WorkflowResultPackageExport = {
  packageExportId?: string;
  resultId?: string;
  runId?: string;
  workflowRevisionId?: string;
  lifecycleState?: string;
  packageBytesState?: string;
  packageBytesDeletedAt?: string;
  packageBytesGcReason?: string;
  packageFileDeleted?: boolean;
  includeArtifacts?: boolean;
  artifactPayloadMode?: string;
  download?: WorkflowResultPackageDownload;
  sizeBytes?: number;
  sha256?: string;
  manifestSha256?: string;
  evidenceId?: string;
  artifactIds?: string[];
  createdAt?: string;
};

export type WorkflowResultPackageExportResponse = {
  data: WorkflowResultPackageExport;
};

export type WorkflowResultPackageExportListResponse = {
  data: {
    schemaVersion?: string;
    resultId?: string;
    lifecycleState?: string;
    items?: WorkflowResultPackageExport[];
  };
};

export type WorkflowArtifactPreview = {
  artifact?: WorkflowArtifact;
  preview?: {
    kind?: string;
    content?: string;
    columns?: string[];
    rows?: string[][];
    entries?: WorkflowArtifactDirectoryPreviewEntry[];
    fileCount?: number;
    directoryCount?: number;
    logicalSizeBytes?: number;
    logicalSha256?: string;
    packageProfile?: string;
    schemaVersion?: string;
    truncated?: boolean;
  };
};

export type WorkflowRunDetail = {
  run: WorkflowRun;
  events: WorkflowRunEvent[];
  logs: {
    stdout?: WorkflowLogLines;
    stderr?: WorkflowLogLines;
  };
  results?: WorkflowResultDetail;
  rules?: WorkflowRunRules;
  executionContext?: WorkflowRunExecutionContext;
  failureLocator?: WorkflowRunFailureLocator;
  previews?: WorkflowArtifactPreview[];
};

export type WorkflowRunDetailResponse = {
  data: WorkflowRunDetail;
};

export type WorkflowRunResponse = {
  data: WorkflowRun;
  location?: string;
  retryAfter?: number;
  requestId?: string;
};

export type WorkflowRunRetryResult = {
  runId: string;
  status: string;
  stage: string;
  commandId: string;
  jobId: string;
  attemptCount: number;
  maxAttempts: number;
  remainingAttempts: number;
  availableAt: string;
  retryRequestedAt: string;
};

export type WorkflowRunRetryResponse = {
  data: WorkflowRunRetryResult;
};

export type WorkflowResourceBinding = {
  databaseId: string;
};

export type WorkflowResourceBindings = Record<string, WorkflowResourceBinding>;

export function generatedToolResourceEntries(tools: Pick<AddedTool, "ruleTemplate" | "ruleSpecDraft">[]) {
  const entries: [string, WorkflowResourceSpec][] = [];
  const seen = new Set<string>();
  for (const tool of tools) {
    const resources = (readToolRuleTemplate(tool) as { resources?: unknown }).resources;
    if (!resources || typeof resources !== "object" || Array.isArray(resources)) continue;
    for (const [key, value] of Object.entries(resources as Record<string, unknown>)) {
      if (seen.has(key) || !value || typeof value !== "object" || Array.isArray(value)) continue;
      const spec = value as WorkflowResourceSpec;
      if ((spec.type || "database") !== "database") continue;
      seen.add(key);
      entries.push([key, spec]);
    }
  }
  return entries;
}

export function runnableCatalogItems(items: WorkflowCatalogItem[]) {
  return items.filter((item) => item.runnable);
}

export function outputArtifactNames(item: WorkflowCatalogItem) {
  const artifacts = item.outputSchema?.artifacts || [];
  return artifacts.map((artifact) => artifact.name || artifact.kind || "artifact").filter(Boolean).join(", ");
}

export function selectableTools(tools: AddedTool[]) {
  return tools
    .map((tool, index) => ({ tool, index, score: ruleReadyToolScore(tool) }))
    .filter((entry) => ruleSpecReadinessForTool(entry.tool).workflowReady)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map((entry) => entry.tool);
}

function ruleReadyToolScore(tool: AddedTool) {
  const template = readToolRuleTemplate(tool);
  let score = 0;
  if (toolHasRuleAction(template)) score += 4;
  if (Array.isArray(template.inputs) && template.inputs.length > 0) score += 2;
  if (Array.isArray(template.outputs) && template.outputs.length > 0) score += 2;
  if (Array.isArray(tool.capabilities) && tool.capabilities.length > 0) score += 1;
  return score;
}

function readToolRuleTemplate(tool: Pick<AddedTool, "ruleTemplate" | "ruleSpecDraft">): Record<string, unknown> {
  return displayRuleTemplateForTool(tool as AddedTool);
}

function toolHasRuleAction(template: Record<string, unknown>) {
  return hasRuleAction(template);
}

export function selectableDatabases(databases: DatabaseItem[]) {
  return databases.filter((database) => database.status === "available");
}

export function workflowResourceEntries(item: WorkflowCatalogItem | null) {
  const resources = item?.resources || {};
  return Object.entries(resources).filter(([, spec]) => (spec.type || "database") === "database");
}

export function databaseMatchesWorkflowResource(database: DatabaseItem, spec: WorkflowResourceSpec) {
  if (database.status !== "available") return false;
  const metadata = database.metadata || {};
  if (spec.acceptedTemplates?.length && !spec.acceptedTemplates.includes(String(metadata.templateId || ""))) {
    return false;
  }
  if (spec.acceptedCapabilities?.length) {
    const rawCapabilities = (metadata as { capabilities?: unknown }).capabilities;
    const capabilities = Array.isArray(rawCapabilities) ? rawCapabilities.map(String) : [];
    return spec.acceptedCapabilities.some((capability) => capabilities.includes(capability));
  }
  return true;
}

export function buildWorkflowResourceBindings(
  selectedResourceDatabaseIds: Record<string, string>,
  item: WorkflowCatalogItem | null,
  databases: DatabaseItem[]
): WorkflowResourceBindings {
  const availableIds = new Set(databases.filter((database) => database.status === "available").map((database) => database.id));
  return Object.fromEntries(
    workflowResourceEntries(item)
      .map(([key, spec]) => [key, spec, selectedResourceDatabaseIds[key]] as const)
      .filter(([, spec, databaseId]) => {
        if (!databaseId || !availableIds.has(databaseId)) return false;
        const database = databases.find((item) => item.id === databaseId);
        return Boolean(database && databaseMatchesWorkflowResource(database, spec));
      })
      .map(([key, , databaseId]) => [key, { databaseId }])
  );
}

export function workflowErrorMessage(err: unknown, fallback: string) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/WORKFLOW_TOOL_NOT_READY/.test(message)) {
    return "所选工具还未通过合同验证，请先在工具页完成 dry-run、smoke run 和输出验证。";
  }
  if (/not ready|not prepared|not connected|unreachable|Remote end closed/i.test(message)) {
    return "远程服务暂不可用，请先连接 SSH 并启动远程服务。";
  }
  if (/serverId|required/i.test(message)) {
    return "没有可用的远程服务器，请先完成 SSH 连接和远程服务准备。";
  }
  return message || fallback;
}
