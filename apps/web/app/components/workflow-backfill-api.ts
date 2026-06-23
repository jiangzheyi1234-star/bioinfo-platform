"use client";

import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowBackfillLaunchDetail,
  WorkflowBackfillLaunchDetailResponse,
  WorkflowBackfillLaunchList,
  WorkflowBackfillLaunchListResponse,
} from "./workflow-backfill-model";

type WorkflowBackfillFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
  triggerId?: string;
  limit?: number;
};

const WORKFLOW_BACKFILL_LAUNCHES_CACHE_KEY = "workflow:backfill-launches";
const WORKFLOW_BACKFILL_LAUNCH_CACHE_KEY = "workflow:backfill-launch";

export async function fetchWorkflowBackfillLaunches(
  options: WorkflowBackfillFetchOptions = {}
): Promise<WorkflowBackfillLaunchList> {
  const limit = Math.max(1, Math.min(options.limit || 20, 100));
  const key = [
    WORKFLOW_BACKFILL_LAUNCHES_CACHE_KEY,
    options.serverId || "default",
    options.triggerId || "all",
    limit,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowBackfillLaunchListResponse>(
      "GET",
      `/api/v1/workflow-backfill-launches${backfillQuery({ ...options, limit })}`,
      { cache: "no-store" }
    );
    return { schemaVersion: response.data.schemaVersion, items: response.data.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchWorkflowBackfillLaunch(
  launchId: string,
  options: Omit<WorkflowBackfillFetchOptions, "triggerId" | "limit"> = {}
): Promise<WorkflowBackfillLaunchDetail> {
  const normalizedLaunchId = launchId.trim();
  if (!normalizedLaunchId) {
    throw new Error("WORKFLOW_BACKFILL_LAUNCH_ID_REQUIRED");
  }
  const key = [
    WORKFLOW_BACKFILL_LAUNCH_CACHE_KEY,
    options.serverId || "default",
    normalizedLaunchId,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowBackfillLaunchDetailResponse>(
      "GET",
      `/api/v1/workflow-backfill-launches/${encodeURIComponent(normalizedLaunchId)}${backfillQuery(options)}`,
      { cache: "no-store" }
    );
    return { ...response.data, partitions: response.data.partitions || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

function backfillQuery(options: WorkflowBackfillFetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  if (options.triggerId) params.set("triggerId", options.triggerId);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}
