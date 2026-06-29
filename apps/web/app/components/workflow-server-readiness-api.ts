"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { invalidateAsyncCache } from "@/app/lib/async-cache";

const WORKFLOW_SERVER_CACHE_KEY = "workflow:server";

export async function ensureWorkflowServerRunner(serverId: string): Promise<void> {
  const normalizedServerId = serverId.trim();
  if (!normalizedServerId) {
    throw new Error("serverId is required");
  }
  await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(normalizedServerId)}/ensure-runner`, {
    cache: "no-store",
    timeoutMs: 120_000,
  });
  invalidateAsyncCache(WORKFLOW_SERVER_CACHE_KEY);
}
