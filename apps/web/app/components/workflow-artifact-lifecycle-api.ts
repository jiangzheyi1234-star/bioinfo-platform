"use client";

import { cachedAsync, invalidateAsyncCachePrefix } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowArtifactLifecycleControllerRunOnceRequest,
  WorkflowArtifactLifecycleControllerRunOnceResponse,
  WorkflowArtifactLifecycleControllerRunOnceResult,
  WorkflowArtifactGcPlan,
  WorkflowArtifactGcPreviewRequest,
  WorkflowArtifactGcRunRequest,
  WorkflowArtifactGcRunResult,
  WorkflowArtifactLifecycleControllerTickList,
  WorkflowArtifactLifecycleUsage,
  WorkflowResultPackageByteGcPlan,
  WorkflowResultPackageByteGcPreviewRequest,
  WorkflowResultPackageByteGcRunRequest,
  WorkflowResultPackageByteGcRunResult,
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
    const response = await requestLocalApiJson<{ data: WorkflowArtifactLifecycleUsage }>(
      "GET",
      `/api/v1/artifacts/lifecycle/usage${artifactLifecycleQuery({ ...options, quotaBytes })}`,
      { cache: "no-store" }
    );
    return response.data;
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
    const response = await requestLocalApiJson<{ data: WorkflowArtifactLifecycleControllerTickList }>(
      "GET",
      `/api/v1/artifacts/lifecycle/controller/ticks${artifactLifecycleQuery({ ...options, limit })}`,
      { cache: "no-store" }
    );
    return { schemaVersion: response.data.schemaVersion, items: response.data.items || [] };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function runArtifactLifecycleControllerOnce(
  request: WorkflowArtifactLifecycleControllerRunOnceRequest = {}
): Promise<WorkflowArtifactLifecycleControllerRunOnceResult> {
  const body: WorkflowArtifactLifecycleControllerRunOnceRequest & { confirmation: string } = {
    confirmation: "run-artifact-lifecycle-controller-once",
    actor: request.actor?.trim() || "web-ui",
  };
  if (request.serverId) body.serverId = request.serverId;

  const response = await requestLocalApiJson<WorkflowArtifactLifecycleControllerRunOnceResponse>(
    "POST",
    "/api/v1/artifacts/lifecycle/controller/run-once",
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  invalidateArtifactLifecycleCaches();
  return response.data;
}

export async function previewArtifactGc(
  request: WorkflowArtifactGcPreviewRequest
): Promise<WorkflowArtifactGcPlan> {
  const body: WorkflowArtifactGcPreviewRequest = {
    actor: request.actor?.trim() || "web-ui",
  };
  if (request.serverId) body.serverId = request.serverId;

  const response = await requestLocalApiJson<{ data: WorkflowArtifactGcPlan }>(
    "POST",
    "/api/v1/artifacts/lifecycle/gc/preview",
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  return response.data;
}

export async function runArtifactGc(
  request: WorkflowArtifactGcRunRequest
): Promise<WorkflowArtifactGcRunResult> {
  const response = await requestLocalApiJson<{ data: WorkflowArtifactGcRunResult }>(
    "POST",
    "/api/v1/artifacts/lifecycle/gc/run",
    {
      body: request,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  invalidateArtifactLifecycleCaches();
  return response.data;
}

export async function previewResultPackageByteGc(
  request: WorkflowResultPackageByteGcPreviewRequest
): Promise<WorkflowResultPackageByteGcPlan> {
  const body: WorkflowResultPackageByteGcPreviewRequest = {
    retentionDays: normalizeOptionalNonNegativeInteger(request.retentionDays) ?? 30,
    scanLimit: Math.min(normalizeOptionalPositiveInteger(request.scanLimit) ?? 1000, 5000),
    reason: request.reason?.trim() || "web-ui-result-package-byte-gc-preview",
    actor: request.actor?.trim() || "web-ui",
  };
  if (request.serverId) body.serverId = request.serverId;
  const maxDeleteBytes = normalizeOptionalPositiveInteger(request.maxDeleteBytes);
  if (maxDeleteBytes !== undefined) body.maxDeleteBytes = maxDeleteBytes;

  const response = await requestLocalApiJson<{ data: WorkflowResultPackageByteGcPlan }>(
    "POST",
    "/api/v1/result-package-exports/bytes/gc/preview",
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  return response.data;
}

export async function runResultPackageByteGc(
  request: WorkflowResultPackageByteGcRunRequest
): Promise<WorkflowResultPackageByteGcRunResult> {
  const response = await requestLocalApiJson<{ data: WorkflowResultPackageByteGcRunResult }>(
    "POST",
    "/api/v1/result-package-exports/bytes/gc/run",
    {
      body: request,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  invalidateAsyncCachePrefix("workflow:results");
  return response.data;
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

function invalidateArtifactLifecycleCaches() {
  invalidateAsyncCachePrefix(ARTIFACT_LIFECYCLE_USAGE_CACHE_KEY);
  invalidateAsyncCachePrefix(ARTIFACT_LIFECYCLE_TICKS_CACHE_KEY);
}

function normalizeOptionalPositiveInteger(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  const normalized = Math.floor(value);
  return normalized > 0 ? normalized : undefined;
}

function normalizeOptionalNonNegativeInteger(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  return Math.max(0, Math.floor(value));
}
