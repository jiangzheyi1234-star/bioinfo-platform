import { invoke } from "@tauri-apps/api/core";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cachedAsync, invalidateAsyncCachePrefix, peekAsyncCache } from "@/app/lib/async-cache";

import {
  type AddedTool,
  type RuleSpecTemplate,
  type ToolPrepareJob,
  type ToolPrepareJobResponse,
  type ToolSearchResponse,
  TOOL_SEARCH_PAGE_SIZE,
  type ToolsResponse,
  uniqueDependencies,
} from "./tools-page-model";

const ADDED_TOOLS_CACHE_KEY = "tools:added";
const ADDED_TOOLS_CACHE_TTL_MS = 30_000;
const TOOL_SEARCH_REQUEST_TIMEOUT_MS = 90_000;

export function invalidateWorkflowToolCaches() {
  invalidateAsyncCachePrefix("workflow:");
  invalidateAsyncCachePrefix("tools:");
}

function refreshQuery(options: { forceRefresh?: boolean }) {
  return options.forceRefresh ? "?refresh=true" : "";
}

function normalizeAddedTools(response: ToolsResponse): AddedTool[] {
  return uniqueDependencies(
    (response.data.items || []).map((item) => ({
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
      const response = await requestLocalApiJson<ToolsResponse>("GET", `/api/v1/tools${refreshQuery(options)}`, { cache: "no-store" });
      return normalizeAddedTools(response);
    },
    { forceRefresh: options.forceRefresh }
  );
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
