import { invoke } from "@tauri-apps/api/core";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import {
  type AddedTool,
  type ToolSearchResponse,
  TOOL_SEARCH_PAGE_SIZE,
  type ToolsResponse,
  uniqueDependencies,
} from "./tools-page-model";

export async function fetchAddedTools(): Promise<AddedTool[]> {
  const response = await requestLocalApiJson<ToolsResponse>("GET", "/api/v1/tools", { cache: "no-store" });
  return uniqueDependencies(
    (response.data.items || []).map((item) => ({
      ...item,
      selectedVersion: item.version || "",
      selectedPackageSpec: item.packageSpec,
    }))
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
    { cache: "no-store", signal }
  );
  return response.data;
}

export async function addToolDependency(tool: AddedTool): Promise<void> {
  await requestLocalApiJson("POST", "/api/v1/tools", {
    body: {
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
    },
  });
}

export async function removeToolDependency(id: string): Promise<void> {
  await requestLocalApiJson("DELETE", `/api/v1/tools/${encodeURIComponent(id)}`);
}

export async function openToolSourceUrl(url: string): Promise<void> {
  try {
    await invoke("open_external_url", { url });
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}
