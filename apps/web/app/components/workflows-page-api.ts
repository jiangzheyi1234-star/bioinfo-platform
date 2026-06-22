import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCache, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import type { DatabaseItem, DatabasesResponse } from "./database-page-model";
import type { RuleOutputSpec } from "./generated-workflow-model";
import { portCompatibilityDecision } from "./generated-workflow-port-contract";
import { fetchCapabilityGraphSnapshot } from "./tools-page-api";
import type {
  AddedTool,
  CapabilityBundleSummary,
  CapabilityGraphSemanticNode,
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
import {
  buildPipelineRunSpec,
  type WorkflowArtifactPreview,
  type WorkflowCatalogItem,
  type WorkflowCatalogResponse,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowRunDetailResponse,
  type WorkflowResultPackageExport,
  type WorkflowResultPackageExportResponse,
  type WorkflowRunResponse,
  type WorkflowRunRetryResponse,
  type WorkflowRunRetryResult,
  type WorkflowServer,
  type WorkflowResourceBindings,
  type WorkflowServersResponse,
  type WorkflowUpload,
} from "./workflows-page-model";

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
  };
  matchedFields: string[];
  confidence: number;
  hardChecks: string[];
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

function workflowRecommendationsFromCapabilityGraph({
  graphEdges,
  outputPort,
  page,
  pageSize,
  profileNodes,
  query,
}: {
  graphEdges: Array<{ from: string; to: string; kind: string }>;
  outputPort: RuleOutputSpec;
  page: number;
  pageSize: number;
  profileNodes: CapabilityGraphSemanticNode[];
  query: string;
}): WorkflowToolRecommendations {
  const normalizedQuery = query.trim().toLowerCase();
  const boundedPage = Math.max(1, page || 1);
  const boundedPageSize = Math.max(1, Math.min(pageSize || 5, 100));
  const inputPortsByProfileNode = capabilityInputPortsByProfileNode(profileNodes, graphEdges);
  const items = profileNodes
    .filter(
      (node) =>
        node.kind === "ToolProfile" &&
        node.agentSelectable === true &&
        node.toolRevisionId &&
        node.capabilityBundle?.capabilityId
    )
    .filter((node) => !normalizedQuery || capabilityNodeText(node).includes(normalizedQuery))
    .flatMap((node) =>
      (inputPortsByProfileNode.get(node.id) || []).flatMap((inputPort) => {
        const matchedFields = matchedCapabilityFields(inputPort, outputPort);
        if (matchedFields.length === 0) return [];
        const hardChecks = portCompatibilityDecision(capabilityPortSpec(inputPort), outputPort).hardChecks;
        return [capabilityGraphRecommendation(node, inputPort, matchedFields, hardChecks, node.capabilityBundle)];
      })
    )
    .sort((left, right) => right.confidence - left.confidence || recommendationName(left).localeCompare(recommendationName(right)));
  const offset = (boundedPage - 1) * boundedPageSize;
  return {
    items: items.slice(offset, offset + boundedPageSize),
    query: normalizedQuery,
    total: items.length,
    page: boundedPage,
    pageSize: boundedPageSize,
    hasMore: offset + boundedPageSize < items.length,
  };
}

function capabilityInputPortsByProfileNode(
  nodes: CapabilityGraphSemanticNode[],
  edges: Array<{ from: string; to: string; kind: string }>
) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const result = new Map<string, CapabilityGraphSemanticNode[]>();
  edges
    .filter((edge) => edge.kind === "consumes")
    .forEach((edge) => {
      const port = byId.get(edge.to);
      if (!port || port.kind !== "InputPort") return;
      result.set(edge.from, [...(result.get(edge.from) || []), port]);
    });
  return result;
}

function matchedCapabilityFields(inputPort: CapabilityGraphSemanticNode, outputPort: RuleOutputSpec): string[] {
  const decision = portCompatibilityDecision(capabilityPortSpec(inputPort), outputPort);
  if (!decision.compatible) return [];
  return decision.matchedFields.filter((field) => field !== "type");
}

function capabilityPortSpec(inputPort: CapabilityGraphSemanticNode) {
  return {
    type: String(inputPort.type || ""),
    kind: String(inputPort.kindLabel || ""),
    mimeType: String(inputPort.mimeType || ""),
    data: String(inputPort.data || ""),
    format: String(inputPort.format || ""),
    resource: String(inputPort.resource || ""),
  };
}

function capabilityGraphRecommendation(
  profileNode: CapabilityGraphSemanticNode,
  inputPort: CapabilityGraphSemanticNode,
  matchedFields: string[],
  hardChecks: string[],
  capabilityBundle?: CapabilityBundleSummary
): WorkflowToolRecommendationItem {
  const profileId = String(profileNode.profileId || "").trim();
  const toolRevisionId = String(capabilityBundle?.toolRevisionId || profileNode.toolRevisionId || "").trim();
  const capabilityId = String(capabilityBundle?.capabilityId || profileNode.capabilityId || "").trim();
  return {
    decision: "recommended",
    candidate: {
      candidateId: profileNode.id,
      candidateKind: "capability-bundle",
      profileId,
      capabilityId,
      capabilityBundleVersion: capabilityBundle?.capabilityBundleVersion,
      toolNames: [profileId].filter(Boolean),
    },
    executionGate: {
      currentState: "WorkflowReady",
      requiredState: "WorkflowReady",
      canAddStep: true,
      nextAction: "add-step",
      reason: "WORKFLOW_TOOL_READY",
      sourceOfTruth: "capability-bundle-v1",
      toolRevisionId,
      capabilityId,
    },
    capabilityBundle,
    inputPort: {
      name: String(inputPort.name || ""),
      required: inputPort.required,
      type: String(inputPort.type || ""),
      kind: String(inputPort.kindLabel || inputPort.kind || ""),
      data: String(inputPort.data || ""),
      format: String(inputPort.format || ""),
    },
    matchedFields,
    confidence: Math.min(1, 0.45 + matchedFields.length * 0.15),
    hardChecks: ["capability-bundle-v1 agentSelectable=true", ...hardChecks],
    evidence: [
      `capabilityId ${capabilityId}`,
      `toolRevisionId ${toolRevisionId}`,
      `validation ${capabilityBundle?.validationEvidence?.status || "unknown"}`,
    ],
  };
}

function capabilityNodeText(node: CapabilityGraphSemanticNode): string {
  return [node.profileId, node.packId, node.operation, node.workflowStage, node.toolRevisionId].join(" ").toLowerCase();
}

function recommendationName(item: WorkflowToolRecommendationItem): string {
  return item.candidate.profileId || item.candidate.candidateId || "";
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
  files,
  sampleUploads,
  params,
  resourceBindings,
}: {
  server: WorkflowServer;
  projectId: string;
  pipelineId: string;
  files: File[];
  sampleUploads?: WorkflowUpload[];
  params?: Record<string, unknown>;
  resourceBindings?: WorkflowResourceBindings;
}): Promise<WorkflowRun> {
  const uploads = sampleUploads && sampleUploads.length > 0
    ? sampleUploads
    : await Promise.all(files.map((file) => uploadWorkflowFile(file, server.serverId)));
  const runSpec = buildPipelineRunSpec({
    projectId,
    pipelineId,
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
