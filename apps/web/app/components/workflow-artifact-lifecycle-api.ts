"use client";

import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowArtifactGcPlan,
  WorkflowArtifactGcPreviewRequest,
  WorkflowArtifactLifecycleControllerTickList,
  WorkflowArtifactLifecycleUsage,
} from "./workflow-artifact-lifecycle-model";

type ArtifactLifecycleFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
  quotaBytes?: number;
  limit?: number;
};

const ARTIFACT_LIFECYCLE_USAGE_CACHE_KEY = "workflow:artifact-lifecycle-usage";
const ARTIFACT_LIFECYCLE_TICKS_CACHE_KEY = "workflow:artifact-lifecycle-controller-ticks";

export async function fetchArtifactLifecycleUsage(
  options: ArtifactLifecycleFetchOptions = {}
): Promise<WorkflowArtifactLifecycleUsage> {
  const quotaBytes = normalizeOptionalPositiveInteger(options.quotaBytes);
  const key = [
    ARTIFACT_LIFECYCLE_USAGE_CACHE_KEY,
    options.serverId || "default",
    quotaBytes ?? "none",
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    return requestLocalApiJson<WorkflowArtifactLifecycleUsage>(
      "GET",
      `/api/v1/artifacts/lifecycle/usage${artifactLifecycleQuery({ ...options, quotaBytes })}`,
      { cache: "no-store" }
    );
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchArtifactLifecycleControllerTicks(
  options: ArtifactLifecycleFetchOptions = {}
): Promise<WorkflowArtifactLifecycleControllerTickList> {
  const limit = Math.max(1, Math.min(options.limit || 20, 100));
  const key = [
    ARTIFACT_LIFECYCLE_TICKS_CACHE_KEY,
    options.serverId || "default",
    limit,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<WorkflowArtifactLifecycleControllerTickList>(
      "GET",
      `/api/v1/artifacts/lifecycle/controller/ticks${artifactLifecycleQuery({ ...options, limit })}`,
      { cache: "no-store" }
    );
    return { schemaVersion: response.schemaVersion, items: response.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function previewArtifactGc(
  request: WorkflowArtifactGcPreviewRequest
): Promise<WorkflowArtifactGcPlan> {
  const body: WorkflowArtifactGcPreviewRequest = {
    retentionDays: Math.max(0, Math.floor(request.retentionDays ?? 30)),
    eligibleRunStatuses: request.eligibleRunStatuses?.length
      ? request.eligibleRunStatuses
      : ["completed", "failed", "canceled", "cancelled"],
    reason: request.reason?.trim() || "web-ui-preview",
    actor: request.actor?.trim() || "web-ui",
  };
  if (request.serverId) body.serverId = request.serverId;
  const maxDeleteBytes = normalizeOptionalPositiveInteger(request.maxDeleteBytes);
  if (maxDeleteBytes !== undefined) body.maxDeleteBytes = maxDeleteBytes;

  return requestLocalApiJson<WorkflowArtifactGcPlan>(
    "POST",
    "/api/v1/artifacts/lifecycle/gc/preview",
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
}

function artifactLifecycleQuery(options: ArtifactLifecycleFetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  if (options.quotaBytes !== undefined) params.set("quotaBytes", String(options.quotaBytes));
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

function normalizeOptionalPositiveInteger(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  const normalized = Math.floor(value);
  return normalized > 0 ? normalized : undefined;
}
