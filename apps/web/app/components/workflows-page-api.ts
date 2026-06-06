import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCache, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import type { DatabaseItem, DatabasesResponse } from "./database-page-model";
import type { RuleOutputSpec } from "./generated-workflow-model";
import type { AddedTool, ToolsResponse } from "./tools-page-model";
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
  type WorkflowRunResponse,
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
  qualityTier?: string;
  profileId?: string;
  profileVersion?: number;
  toolNames?: string[];
  preferredWrapperPaths?: string[];
};

export type WorkflowToolRecommendationItem = {
  decision: "recommended" | "blocked" | "ambiguous" | string;
  candidate: WorkflowToolRecommendationCandidate;
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
    const response = await requestLocalApiJson<ToolsResponse>("GET", `/api/v1/tools${refreshQuery(options)}`, { cache: "no-store" });
    return response.data.items || [];
  }, {
    forceRefresh: options.forceRefresh,
  });
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
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  });
  if (query) params.set("q", query);
  if (outputPort.type) params.set("outputType", outputPort.type);
  if (outputPort.kind) params.set("outputKind", outputPort.kind);
  if (outputPort.mimeType) params.set("outputMimeType", outputPort.mimeType);
  if (outputPort.data) params.set("outputData", outputPort.data);
  if (outputPort.format) params.set("outputFormat", outputPort.format);
  const response = await requestLocalApiJson<{ data: WorkflowToolRecommendations }>(
    "GET",
    `/api/v1/tool-capabilities/candidate-recommendations?${params.toString()}`,
    { cache: "no-store" }
  );
  return response.data;
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
}: {
  server: WorkflowServer;
  files: File[];
  plan: WorkflowDesignPlan;
}): Promise<WorkflowRun> {
  if (!plan.valid) {
    const issue = plan.validationIssues[0];
    throw new Error(issue ? `${issue.code}: ${issue.message}` : "WORKFLOW_DESIGN_PLAN_INVALID");
  }
  const plannedRunSpec = requireWorkflowDesignPlanRunSpec(plan);
  const plannedInputs = requireWorkflowDesignPlannedInputs(plannedRunSpec);
  if (plannedInputs.length !== files.length) {
    throw new Error("WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH");
  }
  const uploads = await Promise.all(files.map((file) => uploadWorkflowFile(file, server.serverId)));
  const runSpec = {
    ...plannedRunSpec,
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
