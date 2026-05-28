import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCache, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import type { DatabaseItem, DatabasesResponse } from "./database-page-model";
import type { AddedTool, ToolsResponse } from "./tools-page-model";
import {
  buildGeneratedRunSpec,
  buildPipelineRunSpec,
  workflowDatabaseRole,
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
  type WorkflowTemplateSummary,
  type WorkflowTemplatesResponse,
  type WorkflowUpload,
} from "./workflows-page-model";

type FetchOptions = {
  forceRefresh?: boolean;
};

const WORKFLOW_CATALOG_CACHE_KEY = "workflow:catalog";
const WORKFLOW_TOOLS_CACHE_KEY = "workflow:tools";
const WORKFLOW_DATABASES_CACHE_KEY = "workflow:databases";
const WORKFLOW_SERVER_CACHE_KEY = "workflow:server";
const WORKFLOW_RUNS_CACHE_KEY = "workflow:runs";

function refreshQuery(options: FetchOptions) {
  return options.forceRefresh ? "?refresh=true" : "";
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

export async function fetchWorkflowTemplates(): Promise<WorkflowTemplateSummary[]> {
  const response = await requestLocalApiJson<WorkflowTemplatesResponse>(
    "GET",
    "/api/v1/workflow-templates",
    { cache: "no-store" }
  );
  return response.data.items || [];
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

export async function uploadWorkflowFile(file: File): Promise<WorkflowUpload> {
  const response = await requestLocalApiJson<{ data: WorkflowUpload }>("POST", "/api/v1/uploads", {
    body: {
      filename: file.name,
      contentBase64: await fileToBase64(file),
      mimeType: file.type || "application/octet-stream",
    },
  });
  return response.data;
}

export async function submitGeneratedWorkflowRun({
  server,
  projectId,
  files,
  tools,
  databases,
}: {
  server: WorkflowServer;
  projectId: string;
  files: File[];
  tools: AddedTool[];
  databases: DatabaseItem[];
}): Promise<WorkflowRun> {
  const uploads = await Promise.all(files.map((file) => uploadWorkflowFile(file)));
  const runSpec = buildGeneratedRunSpec({
    projectId,
    uploads,
    toolIds: tools.map((tool) => tool.id),
    databases: databases.map((database, index) => ({
      id: database.id,
      role: workflowDatabaseRole(database, index),
    })),
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
    : await Promise.all(files.map((file) => uploadWorkflowFile(file)));
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
    { body: {} }
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

export function invalidateWorkflowWorkspaceCache() {
  invalidateAsyncCachePrefix("workflow:");
}
