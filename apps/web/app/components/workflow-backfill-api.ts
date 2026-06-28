"use client";

import { cachedAsync, invalidateAsyncCachePrefix } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import { invalidateWorkflowRunResultCaches } from "./workflows-page-api";
import type {
  WorkflowBackfillCancelResponse,
  WorkflowBackfillLaunchDetail,
  WorkflowBackfillLaunchDetailResponse,
  WorkflowBackfillLaunchList,
  WorkflowBackfillLaunchListResponse,
  WorkflowBackfillLaunchResponse,
  WorkflowBackfillPreview,
  WorkflowBackfillPreviewRequest,
  WorkflowBackfillPreviewResponse,
} from "./workflow-backfill-model";

type WorkflowBackfillFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
  triggerId?: string;
  limit?: number;
};

const WORKFLOW_BACKFILL_LAUNCHES_CACHE_KEY = "workflow:backfill-launches";
const WORKFLOW_BACKFILL_LAUNCH_CACHE_KEY = "workflow:backfill-launch";

export function invalidateWorkflowBackfillLaunchCaches() {
  invalidateAsyncCachePrefix(WORKFLOW_BACKFILL_LAUNCHES_CACHE_KEY);
  invalidateAsyncCachePrefix(WORKFLOW_BACKFILL_LAUNCH_CACHE_KEY);
}

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

export async function cancelWorkflowBackfillLaunch(
  launchId: string,
  options: Omit<WorkflowBackfillFetchOptions, "triggerId" | "limit"> = {}
): Promise<WorkflowBackfillCancelResponse["data"]> {
  const normalizedLaunchId = launchId.trim();
  if (!normalizedLaunchId) {
    throw new Error("WORKFLOW_BACKFILL_LAUNCH_ID_REQUIRED");
  }
  const response = await requestLocalApiJson<WorkflowBackfillCancelResponse>(
    "POST",
    `/api/v1/workflow-backfill-launches/${encodeURIComponent(normalizedLaunchId)}/cancel${backfillQuery(options)}`,
    {
      body: { confirmation: "cancel-backfill" },
      cache: "no-store",
    }
  );
  invalidateWorkflowBackfillLaunchCaches();
  invalidateWorkflowRunResultCaches();
  return response.data;
}

export async function previewWorkflowTriggerBackfill(
  triggerId: string,
  payload: WorkflowBackfillPreviewRequest,
  options: Pick<WorkflowBackfillFetchOptions, "serverId"> = {}
): Promise<WorkflowBackfillPreview> {
  const normalizedTriggerId = triggerId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  const response = await requestLocalApiJson<WorkflowBackfillPreviewResponse>(
    "POST",
    `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/backfill/preview${backfillQuery(options)}`,
    {
      body: payload,
      cache: "no-store",
    }
  );
  return { ...response.data, partitions: response.data.partitions || [] };
}

export async function launchWorkflowTriggerBackfill(
  triggerId: string,
  payload: WorkflowBackfillPreviewRequest & { previewId: string; confirmation: "launch-backfill"; actor?: string },
  options: Pick<WorkflowBackfillFetchOptions, "serverId"> = {}
): Promise<WorkflowBackfillLaunchDetail> {
  const normalizedTriggerId = triggerId.trim();
  if (!normalizedTriggerId) {
    throw new Error("WORKFLOW_TRIGGER_ID_REQUIRED");
  }
  const response = await requestLocalApiJson<WorkflowBackfillLaunchResponse>(
    "POST",
    `/api/v1/workflow-triggers/${encodeURIComponent(normalizedTriggerId)}/backfill/launch${backfillQuery(options)}`,
    {
      body: payload,
      cache: "no-store",
    }
  );
  invalidateWorkflowBackfillLaunchCaches();
  invalidateWorkflowRunResultCaches();
  return { ...response.data, partitions: response.data.partitions || [] };
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
