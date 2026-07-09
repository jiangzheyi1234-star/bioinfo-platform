"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { invalidateAsyncCache } from "@/app/lib/async-cache";

const WORKFLOW_SERVER_CACHE_KEY = "workflow:server";

export async function ensureWorkflowServerRunner(serverId: string): Promise<void> {
  await postWorkflowServerRunnerAction(serverId, "ensure-runner");
}

export async function startWorkflowServerRunner(serverId: string): Promise<void> {
  await postWorkflowServerRunnerAction(serverId, "runner/start");
}

export async function repairWorkflowServerRunnerDiagnostics(serverId: string): Promise<void> {
  await postWorkflowServerRunnerAction(serverId, "runner/diagnostics/repair", 180_000);
}

async function postWorkflowServerRunnerAction(
  serverId: string,
  actionPath: "ensure-runner" | "runner/start" | "runner/diagnostics/repair",
  timeoutMs = 120_000
): Promise<void> {
  const normalizedServerId = serverId.trim();
  if (!normalizedServerId) {
    throw new Error("serverId is required");
  }
  await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(normalizedServerId)}/${actionPath}`, {
    cache: "no-store",
    timeoutMs,
  });
  invalidateAsyncCache(WORKFLOW_SERVER_CACHE_KEY);
}
