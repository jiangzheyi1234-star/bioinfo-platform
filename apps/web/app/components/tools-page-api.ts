import { invoke } from "@tauri-apps/api/core";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import {
  type AddedTool,
  type CapabilityGraphSnapshot,
  type CapabilityGraphSnapshotResponse,
  type RuleSpecTemplate,
  type SnakemakeWrapperCatalogResponse,
  type ToolProfileCatalogResponse,
  type ToolPrepareJob,
  type ToolPrepareJobResponse,
  type ToolSearchResponse,
  type ToolValidationQueuePrepareResponse,
  TOOL_SEARCH_PAGE_SIZE,
  uniqueDependencies,
} from "./tools-page-model";

const ADDED_TOOLS_CACHE_KEY = "tools:added";
const ADDED_TOOLS_CACHE_TTL_MS = 30_000;
const TOOL_SEARCH_REQUEST_TIMEOUT_MS = 90_000;

export function invalidateWorkflowToolCaches() {
  invalidateAsyncCachePrefix("workflow:");
  invalidateAsyncCachePrefix("tools:");
}

function normalizeAddedToolItems(items: AddedTool[]): AddedTool[] {
  return uniqueDependencies(
    items.map((item) => ({
      ...item,
      selectedVersion: item.version || "",
      selectedPackageSpec: item.packageSpec,
    }))
  );
}

export function getCachedAddedTools(): AddedTool[] | undefined {
  return peekAsyncCache<AddedTool[]>(ADDED_TOOLS_CACHE_KEY);
}

export async function fetchAddedTools(options: { forceRefresh?: boolean } = {}): Promise<AddedTool[]> {
  return cachedAsync(
    ADDED_TOOLS_CACHE_KEY,
    ADDED_TOOLS_CACHE_TTL_MS,
    async () => {
      const snapshot = await fetchCapabilityGraphSnapshot({ query: "", page: 1, pageSize: 100 });
      return normalizeAddedToolItems(snapshot.registeredTools || []);
    },
    { forceRefresh: options.forceRefresh }
  );
}

export async function fetchCapabilityGraphSnapshot({
  agentSelectableOnly = false,
  page,
  pageSize = 50,
  query,
  signal,
}: {
  agentSelectableOnly?: boolean;
  page: number;
  pageSize?: number;
  query: string;
  signal?: AbortSignal;
}): Promise<CapabilityGraphSnapshot> {
  const params = new URLSearchParams({
    q: query,
    page: String(page),
    pageSize: String(pageSize),
    targetPlatform: "linux-64",
  });
  if (agentSelectableOnly) params.set("agentSelectableOnly", "true");
  const response = await requestLocalApiJson<CapabilityGraphSnapshotResponse>(
    "GET",
    `/api/v1/tool-capabilities/capability-graph?${params.toString()}`,
    { cache: "no-store", signal, timeoutMs: TOOL_SEARCH_REQUEST_TIMEOUT_MS }
  );
  return response.data;
}

export async function searchToolCapabilities({
  query,
  page,
  signal,
}: {
  query: string;
  page: number;
  signal: AbortSignal;
}): Promise<ToolSearchResponse["data"]> {
  const response = await requestLocalApiJson<ToolSearchResponse>(
    "GET",
    `/api/v1/tool-capabilities/search?q=${encodeURIComponent(query)}&page=${page}&pageSize=${TOOL_SEARCH_PAGE_SIZE}&targetPlatform=linux-64`,
    { cache: "no-store", signal, timeoutMs: TOOL_SEARCH_REQUEST_TIMEOUT_MS }
  );
  return response.data;
}

export async function fetchSnakemakeWrapperCatalog(): Promise<SnakemakeWrapperCatalogResponse["data"]> {
  const response = await requestLocalApiJson<SnakemakeWrapperCatalogResponse>(
    "GET",
    "/api/v1/tool-capabilities/snakemake-wrappers?page=1&pageSize=1",
    { cache: "no-store" }
  );
  return response.data;
}

export async function fetchToolProfileCatalog(): Promise<ToolProfileCatalogResponse["data"]> {
  const response = await requestLocalApiJson<ToolProfileCatalogResponse>(
    "GET",
    "/api/v1/tool-capabilities/tool-profiles?page=1&pageSize=50",
    { cache: "no-store" }
  );
  return response.data;
}

export async function addToolDependency(tool: AddedTool): Promise<void> {
  await requestLocalApiJson("POST", "/api/v1/tools", {
    body: toolManifestBody(tool),
  });
  invalidateWorkflowToolCaches();
}

export async function createToolPrepareJob(tool: AddedTool): Promise<ToolPrepareJob> {
  const response = await requestLocalApiJson<ToolPrepareJobResponse>("POST", "/api/v1/tools/prepare-jobs", {
    body: toolManifestBody(tool),
  });
  return response.data;
}

export async function prepareToolValidationQueue(maxItems: number): Promise<ToolValidationQueuePrepareResponse["data"]> {
  const response = await requestLocalApiJson<ToolValidationQueuePrepareResponse>(
    "POST",
    `/api/v1/tool-capabilities/validation-queue/prepare?targetPlatform=linux-64&maxItems=${maxItems}`,
    { body: {} }
  );
  return response.data;
}

export type ToolProductionEvidencePayload = {
  runId: string;
  evidenceType: string;
  message: string;
  artifactName?: string;
  logPath?: string;
  targetPlatform?: string;
  environmentLock?: Record<string, unknown>;
  inputScope?: Record<string, unknown>;
  artifactDigest?: string;
  policyVersion?: string;
  databaseId?: string;
  templateId?: string;
  role?: string;
  packId?: string;
  packChecksum?: string;
};

export async function submitToolProductionEvidence(toolId: string, payload: ToolProductionEvidencePayload): Promise<AddedTool> {
  const response = await requestLocalApiJson<{ data: AddedTool }>(
    "POST",
    `/api/v1/tools/${encodeURIComponent(toolId)}/production`,
    { body: payload }
  );
  invalidateWorkflowToolCaches();
  return response.data;
}

export async function fetchToolPrepareJob(jobId: string): Promise<ToolPrepareJob> {
  const response = await requestLocalApiJson<ToolPrepareJobResponse>("GET", `/api/v1/tools/prepare-jobs/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
  });
  return response.data;
}

export async function cancelToolPrepareJob(jobId: string): Promise<ToolPrepareJob> {
  const response = await requestLocalApiJson<ToolPrepareJobResponse>("POST", `/api/v1/tools/prepare-jobs/${encodeURIComponent(jobId)}/cancel`, {
    body: {},
  });
  return response.data;
}

export async function updateToolRuleTemplate(id: string, ruleTemplate: RuleSpecTemplate): Promise<void> {
  await requestLocalApiJson("PATCH", `/api/v1/tools/${encodeURIComponent(id)}/rule-template`, {
    body: { ruleTemplate },
  });
  invalidateWorkflowToolCaches();
}

function toolManifestBody(tool: AddedTool) {
  return {
    id: tool.id,
    name: tool.name,
    source: tool.source,
    sourceLabel: tool.sourceLabel,
    version: tool.selectedVersion,
    packageSpec: tool.selectedPackageSpec,
    summary: tool.summary,
    targetPlatform: tool.targetPlatform,
    targetPlatformSupported: tool.targetPlatformSupported,
    platforms: tool.platforms || [],
    sourceUrl: tool.sourceUrl,
    testCommand: tool.testCommand || "",
    ruleTemplate: tool.ruleTemplate,
    ruleSpecDraft: tool.ruleSpecDraft,
    capabilities: tool.capabilities || [],
    snakemakeWrappers: tool.snakemakeWrappers || [],
    snakemakeWrapperCount: tool.snakemakeWrapperCount || 0,
  };
}

export async function removeToolDependency(id: string): Promise<void> {
  await requestLocalApiJson("DELETE", `/api/v1/tools/${encodeURIComponent(id)}`);
  invalidateWorkflowToolCaches();
}

export async function openToolSourceUrl(url: string): Promise<void> {
  try {
    await invoke("open_external_url", { url });
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}
