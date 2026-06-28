import { apiBase, requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCache, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import type { DatabaseItem, DatabasesResponse } from "./database-page-model";
import type { RuleOutputSpec } from "./generated-workflow-model";
import { fetchCapabilityGraphSnapshot } from "./tools-page-api";
import type {
  AddedTool,
  CapabilityBundleSummary,
  RuleSpecDraft,
  RuleSpecTemplate,
  ToolProfileWrapperEvidence,
} from "./tools-page-model";
import type {
  WorkflowDesignCompileResult,
  WorkflowDesignDraft,
  WorkflowDesignDraftRecord,
  WorkflowDesignPlan,
} from "./workflow-design-draft-model";
import { buildPipelineRunSpec, type WorkflowArtifactRunInput } from "./workflow-pipeline-run-spec";
import {
  type WorkflowArtifactPreview,
  type WorkflowCatalogItem,
  type WorkflowCatalogResponse,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowRunDetailResponse,
  type WorkflowResultPackageExport,
  type WorkflowResultPackageExportListResponse,
  type WorkflowResultPackageExportResponse,
  type WorkflowResultSummary,
  type WorkflowRunResponse,
  type WorkflowRunRuleOutputInvalidationApplyResponse,
  type WorkflowRunRuleOutputInvalidationApplyResult,
  type WorkflowRunRetryResponse,
  type WorkflowRunRetryResult,
  type WorkflowServer,
  type WorkflowResourceBindings,
  type WorkflowServersResponse,
  type WorkflowUpload,
} from "./workflows-page-model";
import {
  RESULT_PACKAGE_RETIRE_CONFIRMATION,
  resultPackageCanDownload,
} from "./workflow-result-package-state";
import type {
  WorkflowRuleCacheRestoreRequest,
  WorkflowRuleCacheRestoreResponse,
  WorkflowRuleCacheRestoreResult,
} from "./workflow-rule-cache-restore-model";
import type {
  WorkflowRuleRetryRequest,
  WorkflowRuleRetryResponse,
  WorkflowRuleRetryResult,
} from "./workflow-rule-retry-model";
import type {
  WorkflowRunResumeRequest,
  WorkflowRunResumeResponse,
  WorkflowRunResumeResult,
} from "./workflow-run-resume-model";
import { workflowRecommendationsFromCapabilityGraph } from "./workflow-tool-recommendation-engine";

type FetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
};

export type WorkflowToolRecommendationCandidate = {
  candidateId?: string;
  candidateKind?: string;
  contractState?: string;
  qualityTier?: string;
  profileId?: string;
  profileVersion?: number;
  toolNames?: string[];
  preferredWrapperPaths?: string[];
  snakemakeWrappers?: ToolProfileWrapperEvidence[];
  snakemakeWrapperCount?: number;
  preparePayload?: WorkflowToolRecommendationPreparePayload;
  capabilityId?: string;
  capabilityBundleVersion?: string;
};

export type WorkflowToolRecommendationExecutionGate = {
  currentState?: string;
  requiredState?: string;
  canAddStep?: boolean;
  nextAction?: string;
  reason?: string;
  sourceOfTruth?: string;
  toolRevisionId?: string;
  toolId?: string;
  jobId?: string;
  capabilityId?: string;
};

export type WorkflowToolRecommendationLatestPrepareJob = {
  jobId?: string;
  toolId?: string;
  status?: string;
  stage?: string;
  message?: string;
  errorCode?: string;
  updatedAt?: string;
  resultState?: string;
  workflowReady?: boolean;
  productionEnabled?: boolean;
  validationResultId?: string;
  evidenceId?: string;
};

export type WorkflowToolRecommendationValidationPlan = {
  planVersion?: string;
  requiredState?: string;
  submit?: {
    method?: string;
    path?: string;
    payloadRef?: string;
  };
  poll?: {
    method?: string;
    pathTemplate?: string;
    jobIdField?: string;
  };
  terminalStatuses?: {
    success?: string[];
    waiting?: string[];
    failure?: string[];
  };
  stages?: Array<{
    id?: string;
    contractStatusKey?: string;
    evidence?: string;
  }>;
  successCriteria?: Array<Record<string, unknown>>;
  readinessBoundary?: string;
};

export type WorkflowToolRecommendationPreparePayload = {
  id?: string;
  name?: string;
  source?: string;
  sourceLabel?: string;
  version?: string;
  packageSpec?: string;
  targetPlatform?: string;
  targetPlatformSupported?: boolean;
  snakemakeWrappers?: ToolProfileWrapperEvidence[];
  snakemakeWrapperCount?: number;
  ruleTemplate?: RuleSpecTemplate;
  ruleSpecDraft?: RuleSpecDraft;
};

export type WorkflowToolRecommendationItem = {
  decision: "recommended" | "blocked" | "ambiguous" | string;
  candidate: WorkflowToolRecommendationCandidate;
  executionGate?: WorkflowToolRecommendationExecutionGate;
  latestPrepareJob?: WorkflowToolRecommendationLatestPrepareJob;
  validationPlan?: WorkflowToolRecommendationValidationPlan;
  capabilityBundle?: CapabilityBundleSummary;
  preparePayload?: WorkflowToolRecommendationPreparePayload;
  inputPort: {
    name: string;
    required?: boolean;
    type?: string;
    kind?: string;
    mimeType?: string;
    data?: string;
    format?: string;
    operation?: string;
    resource?: string;
  };
  matchedFields: string[];
  advisoryFields: string[];
  confidence: number;
  hardChecks: string[];
  advisoryChecks: string[];
  evidence: string[];
};

export type WorkflowToolRecommendations = {
  items: WorkflowToolRecommendationItem[];
  query: string;
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
};

const WORKFLOW_CATALOG_CACHE_KEY = "workflow:catalog";
const WORKFLOW_TOOLS_CACHE_KEY = "workflow:tools";
const WORKFLOW_DATABASES_CACHE_KEY = "workflow:databases";
const WORKFLOW_DESIGN_DRAFTS_CACHE_KEY = "workflow:design-drafts";
const WORKFLOW_SERVER_CACHE_KEY = "workflow:server";
const WORKFLOW_RUNS_CACHE_KEY = "workflow:runs";
const WORKFLOW_RESULTS_CACHE_KEY = "workflow:results";
const WORKFLOW_SAMPLE_DATA_TIMEOUT_MS = 180_000;

function refreshQuery(options: FetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function workflowDesignDraftsCacheKey(serverId?: string) {
  return `${WORKFLOW_DESIGN_DRAFTS_CACHE_KEY}:${serverId || "default"}`;
}

export async function fetchWorkflowCatalog(options: FetchOptions = {}): Promise<WorkflowCatalogItem[]> {
  return cachedAsync(WORKFLOW_CATALOG_CACHE_KEY, 30_000, async () => {
    const response = await requestLocalApiJson<WorkflowCatalogResponse>("GET", `/api/v1/workflow-catalog${refreshQuery(options)}`, {
      cache: "no-store",
    });
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export function getCachedWorkflowCatalog(): WorkflowCatalogItem[] | undefined {
  return peekAsyncCache<WorkflowCatalogItem[]>(WORKFLOW_CATALOG_CACHE_KEY);
}

export async function fetchWorkflowTools(options: FetchOptions = {}): Promise<AddedTool[]> {
  return cachedAsync(WORKFLOW_TOOLS_CACHE_KEY, 30_000, async () => {
    const snapshot = await fetchCapabilityGraphSnapshot({ query: "", page: 1, pageSize: 100 });
    return normalizeWorkflowTools(snapshot.agentSelectableTools || []);
  }, {
    forceRefresh: options.forceRefresh,
  });
}

function normalizeWorkflowTools(items: AddedTool[]): AddedTool[] {
  return items.map((item) => ({
    ...item,
    selectedVersion: item.selectedVersion || item.version || "",
    selectedPackageSpec: item.selectedPackageSpec || item.packageSpec,
  }));
}

export async function fetchWorkflowDatabases(options: FetchOptions = {}): Promise<DatabaseItem[]> {
  return cachedAsync(WORKFLOW_DATABASES_CACHE_KEY, 30_000, async () => {
    const response = await requestLocalApiJson<DatabasesResponse>("GET", `/api/v1/databases${refreshQuery(options)}`, { cache: "no-store" });
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchWorkflowToolRecommendations({
  outputPort,
  query = "",
  page = 1,
  pageSize = 5,
}: {
  outputPort: RuleOutputSpec;
  query?: string;
  page?: number;
  pageSize?: number;
}): Promise<WorkflowToolRecommendations> {
  const snapshot = await fetchCapabilityGraphSnapshot({ query, page: 1, pageSize: 100 });
  return workflowRecommendationsFromCapabilityGraph({
    outputPort,
    page,
    pageSize,
    query,
    profileNodes: snapshot.semanticGraph?.nodes || [],
    graphEdges: snapshot.semanticGraph?.edges || [],
  });
}

export async function fetchWorkflowDesignDrafts(options: FetchOptions = {}): Promise<WorkflowDesignDraftRecord[]> {
  return cachedAsync(workflowDesignDraftsCacheKey(options.serverId), 10_000, async () => {
    const response = await requestLocalApiJson<{ data: { items: WorkflowDesignDraftRecord[] } }>(
      "GET",
      `/api/v1/workflow-design-drafts${refreshQuery(options)}`,
      { cache: "no-store" }
    );
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function saveWorkflowDesignDraft({
  draft,
  record,
  serverId,
}: {
  draft: WorkflowDesignDraft;
  record?: WorkflowDesignDraftRecord | null;
  serverId?: string;
}): Promise<WorkflowDesignDraftRecord> {
  const body = { ...(serverId ? { serverId } : {}), draft };
  const response = record?.draftId
    ? await requestLocalApiJson<{ data: WorkflowDesignDraftRecord }>(
        "PATCH",
        `/api/v1/workflow-design-drafts/${encodeURIComponent(record.draftId)}`,
        { body: { ...body, expectedRevision: record.revision } }
      )
    : await requestLocalApiJson<{ data: WorkflowDesignDraftRecord }>(
        "POST",
        "/api/v1/workflow-design-drafts",
        { body }
      );
  invalidateAsyncCachePrefix(WORKFLOW_DESIGN_DRAFTS_CACHE_KEY);
  return response.data;
}

export async function planWorkflowDesignDraft({
  draftId,
  serverId,
}: {
  draftId: string;
  serverId?: string;
}): Promise<WorkflowDesignPlan> {
  const response = await requestLocalApiJson<{ data: WorkflowDesignPlan }>(
    "POST",
    `/api/v1/workflow-design-drafts/${encodeURIComponent(draftId)}/plan`,
    { body: { ...(serverId ? { serverId } : {}) }, cache: "no-store" }
  );
  return response.data;
}

export async function compileWorkflowDesignDraft({
  draftId,
  serverId,
}: {
  draftId: string;
  serverId?: string;
}): Promise<WorkflowDesignCompileResult> {
  const response = await requestLocalApiJson<{ data: WorkflowDesignCompileResult }>(
    "POST",
    `/api/v1/workflow-design-drafts/${encodeURIComponent(draftId)}/compile`,
    { body: { ...(serverId ? { serverId } : {}) }, cache: "no-store" }
  );
  return response.data;
}

export async function fetchWorkflowServer(options: FetchOptions = {}): Promise<WorkflowServer> {
  return cachedAsync(WORKFLOW_SERVER_CACHE_KEY, 15_000, async () => {
    const response = await requestLocalApiJson<WorkflowServersResponse>("GET", `/api/v1/servers${refreshQuery(options)}`, { cache: "no-store" });
    const items = response.data.items || [];
    const selected = items.find((item) => item.connected && item.ready && item.serverId) || items.find((item) => item.serverId);
    if (!selected?.serverId) {
      throw new Error("serverId is required");
    }
    return selected;
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export function getCachedWorkflowServer(): WorkflowServer | undefined {
  return peekAsyncCache<WorkflowServer>(WORKFLOW_SERVER_CACHE_KEY);
}

export async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary);
}

export async function uploadWorkflowFile(file: File, serverId?: string): Promise<WorkflowUpload> {
  const response = await requestLocalApiJson<{ data: WorkflowUpload }>("POST", "/api/v1/uploads", {
    body: {
      ...(serverId ? { serverId } : {}),
      filename: file.name,
      contentBase64: await fileToBase64(file),
      mimeType: file.type || "application/octet-stream",
    },
  });
  return response.data;
}

export async function submitWorkflowDesignRun({
  server,
  files,
  plan,
  workflowRevisionId,
}: {
  server: WorkflowServer;
  files: File[];
  plan: WorkflowDesignPlan;
  workflowRevisionId: string;
}): Promise<WorkflowRun> {
  if (!plan.valid) {
    const issue = plan.validationIssues[0];
    throw new Error(issue ? `${issue.code}: ${issue.message}` : "WORKFLOW_DESIGN_PLAN_INVALID");
  }
  const normalizedWorkflowRevisionId = workflowRevisionId.trim();
  if (!normalizedWorkflowRevisionId) {
    throw new Error("WORKFLOW_REVISION_ID_REQUIRED");
  }
  const plannedRunSpec = requireWorkflowDesignPlanRunSpec(plan);
  const plannedInputs = requireWorkflowDesignPlannedInputs(plannedRunSpec);
  if (plannedInputs.length !== files.length) {
    throw new Error("WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH");
  }
  const uploads = await Promise.all(files.map((file) => uploadWorkflowFile(file, server.serverId)));
  const runSpec = {
    ...plannedRunSpec,
    workflowRevisionId: normalizedWorkflowRevisionId,
    inputs: uploads.map((upload, index) => ({
      uploadId: upload.uploadId,
      filename: plannedInputs[index].filename,
      role: plannedInputs[index].role,
    })),
  };
  const requestId = `req_workflow_design_${Date.now()}`;
  const response = await requestLocalApiJson<WorkflowRunResponse>("POST", "/api/v1/runs", {
    body: {
      serverId: server.serverId,
      requestId,
      idempotencyKey: requestId,
      runSpec,
    },
  });
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

function requireWorkflowDesignPlanRunSpec(plan: WorkflowDesignPlan): Record<string, unknown> {
  const runSpec = plan.runSpec;
  const workflowDesign = runSpec.workflowDesign;
  if (!workflowDesign || typeof workflowDesign !== "object" || Array.isArray(workflowDesign)) {
    throw new Error("WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED: workflowDesign");
  }
  const metadata = workflowDesign as Record<string, unknown>;
  if (typeof metadata.draftId !== "string" || metadata.draftId.trim().length === 0) {
    throw new Error("WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED: workflowDesign.draftId");
  }
  if (!Number.isInteger(metadata.revision) || Number(metadata.revision) < 1) {
    throw new Error("WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED: workflowDesign.revision");
  }
  return runSpec;
}

function requireWorkflowDesignPlannedInputs(runSpec: Record<string, unknown>): Array<{ role: string; filename: string }> {
  const inputs = runSpec.inputs;
  if (!Array.isArray(inputs)) {
    throw new Error("WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED: inputs");
  }
  return inputs.map((input, index) => {
    if (!input || typeof input !== "object" || Array.isArray(input)) {
      throw new Error(`WORKFLOW_DESIGN_PLAN_RUN_INPUT_INVALID: ${index}`);
    }
    const record = input as { role?: unknown; filename?: unknown };
    const roleValue = record.role;
    if (typeof roleValue !== "string" || roleValue.trim().length === 0) {
      throw new Error(`WORKFLOW_DESIGN_PLAN_RUN_INPUT_ROLE_REQUIRED: ${index}`);
    }
    const filenameValue = record.filename;
    if (typeof filenameValue !== "string" || filenameValue.trim().length === 0) {
      throw new Error(`WORKFLOW_DESIGN_PLAN_RUN_INPUT_FILENAME_REQUIRED: ${index}`);
    }
    const role = roleValue.trim();
    const filename = filenameValue.trim();
    return { role, filename };
  });
}

export async function submitPipelineWorkflowRun({
  server,
  projectId,
  pipelineId,
  artifactInputs,
  files,
  sampleUploads,
  params,
  resourceBindings,
}: {
  server: WorkflowServer;
  projectId: string;
  pipelineId: string;
  artifactInputs?: WorkflowArtifactRunInput[];
  files: File[];
  sampleUploads?: WorkflowUpload[];
  params?: Record<string, unknown>;
  resourceBindings?: WorkflowResourceBindings;
}): Promise<WorkflowRun> {
  const selectedArtifactInputs = artifactInputs || [];
  const selectedSampleUploads = sampleUploads || [];
  const sourceCount = [files.length, selectedSampleUploads.length, selectedArtifactInputs.length].filter(
    (count) => count > 0
  ).length;
  if (sourceCount !== 1) {
    throw new Error(sourceCount > 1 ? "PIPELINE_INPUT_SOURCE_AMBIGUOUS" : "PIPELINE_INPUT_SOURCE_REQUIRED");
  }
  const uploads = selectedArtifactInputs.length > 0
    ? []
    : selectedSampleUploads.length > 0
      ? selectedSampleUploads
      : await Promise.all(files.map((file) => uploadWorkflowFile(file, server.serverId)));
  const runSpec = buildPipelineRunSpec({
    projectId,
    pipelineId,
    artifactInputs: selectedArtifactInputs,
    uploads,
    params: params || {},
    resourceBindings,
  });
  const requestId = `req_workflow_ui_${Date.now()}`;
  const response = await requestLocalApiJson<WorkflowRunResponse>("POST", "/api/v1/runs", {
    body: {
      serverId: server.serverId,
      requestId,
      idempotencyKey: requestId,
      runSpec,
    },
  });
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

export async function uploadWorkflowSampleData(pipelineId: string): Promise<WorkflowUpload[]> {
  const response = await requestLocalApiJson<{ data: { items: WorkflowUpload[] } }>(
    "POST",
    `/api/v1/workflow-sample-data/${encodeURIComponent(pipelineId)}/uploads`,
    { body: {}, timeoutMs: WORKFLOW_SAMPLE_DATA_TIMEOUT_MS }
  );
  return response.data.items || [];
}

export async function fetchWorkflowRunDetail(runId: string): Promise<WorkflowRunDetail> {
  const response = await requestLocalApiJson<WorkflowRunDetailResponse>("GET", `/api/v1/runs/${runId}/detail`, {
    cache: "no-store",
  });
  return response.data;
}

export async function retryWorkflowRun(runId: string, reason = "operator_requested"): Promise<WorkflowRunRetryResult> {
  const response = await requestLocalApiJson<WorkflowRunRetryResponse>(
    "POST",
    `/api/v1/runs/${encodeURIComponent(runId)}/retry`,
    {
      body: {
        scope: "run",
        actor: "workflow-ui",
        reason,
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

export async function applyWorkflowRuleOutputInvalidation(
  runId: string,
  planHash: string
): Promise<WorkflowRunRuleOutputInvalidationApplyResult> {
  const response = await requestLocalApiJson<WorkflowRunRuleOutputInvalidationApplyResponse>(
    "POST",
    `/api/v1/runs/${encodeURIComponent(runId)}/rules/output-invalidation/apply`,
    {
      body: {
        confirmation: "apply-rule-output-invalidation",
        planHash,
        actor: "workflow-ui",
        reason: "operator_confirmed_output_invalidation",
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

export async function retryWorkflowRunRules(
  runId: string,
  request: WorkflowRuleRetryRequest
): Promise<WorkflowRuleRetryResult> {
  const response = await requestLocalApiJson<WorkflowRuleRetryResponse>(
    "POST",
    `/api/v1/runs/${encodeURIComponent(runId)}/rules/retry`,
    {
      body: {
        confirmation: "retry-failed-rules",
        planHash: request.planHash,
        actor: "workflow-ui",
        reason: "operator_confirmed_rule_retry",
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

export async function resumeWorkflowRun(
  runId: string,
  request: WorkflowRunResumeRequest
): Promise<WorkflowRunResumeResult> {
  const response = await requestLocalApiJson<WorkflowRunResumeResponse>(
    "POST",
    `/api/v1/runs/${encodeURIComponent(runId)}/resume`,
    {
      body: {
        confirmation: "resume-run",
        planHash: request.planHash,
        actor: "workflow-ui",
        reason: "operator_confirmed_run_resume",
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

const RULE_CACHE_RESTORE_ENDPOINTS: Record<string, string> = {
  "pins:prepare": "pins/prepare",
  "pins:apply": "pins/apply",
  "staged-files:prepare": "staged-files/prepare",
  "staged-files:apply": "staged-files/apply",
  "final-outputs:prepare": "final-outputs/prepare",
  "final-outputs:apply": "final-outputs/apply",
  "adoption:prepare": "adoption/prepare",
  "adoption:apply": "adoption/apply",
};

const RULE_CACHE_RESTORE_CONFIRMATIONS: Record<string, string> = {
  "pins:prepare": "prepare-rule-cache-restore-pins",
  "pins:apply": "apply-rule-cache-restore-pins",
  "staged-files:prepare": "prepare-rule-cache-restore-staged-files",
  "staged-files:apply": "apply-rule-cache-restore-staged-files",
  "final-outputs:prepare": "prepare-rule-cache-restore-final-outputs",
  "final-outputs:apply": "apply-rule-cache-restore-final-outputs",
  "adoption:prepare": "prepare-rule-cache-restore-adoption",
  "adoption:apply": "apply-rule-cache-restore-adoption",
};

export async function runWorkflowRuleCacheRestoreAction(
  runId: string,
  request: WorkflowRuleCacheRestoreRequest
): Promise<WorkflowRuleCacheRestoreResult> {
  const key = `${request.stage}:${request.action}`;
  const endpoint = RULE_CACHE_RESTORE_ENDPOINTS[key];
  const confirmation = RULE_CACHE_RESTORE_CONFIRMATIONS[key];
  if (!endpoint || !confirmation) {
    throw new Error(`Unsupported rule cache restore action: ${key}`);
  }
  const response = await requestLocalApiJson<WorkflowRuleCacheRestoreResponse>(
    "POST",
    `/api/v1/runs/${encodeURIComponent(runId)}/rules/cache-restore/${endpoint}`,
    {
      body: {
        confirmation,
        planHash: request.planHash,
        attemptId: request.attemptId,
        leaseGeneration: request.leaseGeneration,
        actor: "workflow-ui",
        reason: `operator_confirmed_rule_cache_restore_${request.stage}_${request.action}`,
      },
      cache: "no-store",
    }
  );
  invalidateAsyncCache(WORKFLOW_RUNS_CACHE_KEY);
  invalidateAsyncCache(WORKFLOW_RESULTS_CACHE_KEY);
  return response.data;
}

export async function fetchRunsList(options: FetchOptions = {}): Promise<WorkflowRun[]> {
  return cachedAsync(WORKFLOW_RUNS_CACHE_KEY, 10_000, async () => {
    const response = await requestLocalApiJson<{ data: { items: WorkflowRun[] } }>("GET", `/api/v1/runs${refreshQuery(options)}`, {
      cache: "no-store",
    });
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchWorkflowResultsList(options: FetchOptions = {}): Promise<WorkflowResultSummary[]> {
  return cachedAsync(WORKFLOW_RESULTS_CACHE_KEY, 10_000, async () => {
    const response = await requestLocalApiJson<{ data: { items: WorkflowResultSummary[] } }>(
      "GET",
      `/api/v1/results${refreshQuery(options)}`,
      { cache: "no-store" }
    );
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchArtifactPreview(resultId: string, artifactId: string): Promise<WorkflowArtifactPreview> {
  const response = await requestLocalApiJson<{ data: WorkflowArtifactPreview }>(
    "GET",
    `/api/v1/results/${resultId}/preview?artifact_id=${encodeURIComponent(artifactId)}`,
    { cache: "no-store" }
  );
  return response.data;
}

export async function exportWorkflowResultPackage(
  resultId: string,
  includeArtifacts: boolean
): Promise<WorkflowResultPackageExport> {
  const response = await requestLocalApiJson<WorkflowResultPackageExportResponse>(
    "POST",
    `/api/v1/results/${encodeURIComponent(resultId)}/export`,
    {
      body: {
        actor: "workflow-ui",
        includeArtifacts,
      },
      cache: "no-store",
    }
  );
  return response.data;
}

export async function fetchWorkflowResultPackageExports(resultId: string): Promise<WorkflowResultPackageExport[]> {
  const response = await requestLocalApiJson<WorkflowResultPackageExportListResponse>(
    "GET",
    `/api/v1/results/${encodeURIComponent(resultId)}/exports`,
    { cache: "no-store" }
  );
  return response.data.items || [];
}

export async function retireWorkflowResultPackage(
  resultId: string,
  packageExportId: string
): Promise<WorkflowResultPackageExport> {
  const response = await requestLocalApiJson<WorkflowResultPackageExportResponse>(
    "POST",
    `/api/v1/results/${encodeURIComponent(resultId)}/exports/${encodeURIComponent(packageExportId)}/retire`,
    {
      body: {
        actor: "workflow-ui",
        confirmation: RESULT_PACKAGE_RETIRE_CONFIRMATION,
        reason: "operator_retired",
      },
      cache: "no-store",
    }
  );
  return response.data;
}

export function workflowResultPackageDownloadHref(item: WorkflowResultPackageExport): string {
  if (!resultPackageCanDownload(item)) {
    return "";
  }
  const href = item.download?.href?.trim() || "";
  if (!href.startsWith("/api/v1/") || href.includes("://") || href.startsWith("//")) {
    return "";
  }
  return `${apiBase()}${href}`;
}
