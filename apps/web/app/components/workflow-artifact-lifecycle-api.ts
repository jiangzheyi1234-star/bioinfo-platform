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
  const quotaBytes = normalizeOptionalNonNegativeInteger(options.quotaBytes);
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
  const retentionDays = normalizeOptionalNonNegativeInteger(request.retentionDays);
  if (retentionDays !== undefined) body.retentionDays = retentionDays;
  const eligibleRunStatuses = normalizeRunStatuses(request.eligibleRunStatuses);
  if (eligibleRunStatuses.length) body.eligibleRunStatuses = eligibleRunStatuses;
  const quotaBytes = normalizeOptionalNonNegativeInteger(request.quotaBytes);
  if (quotaBytes !== undefined) body.quotaBytes = quotaBytes;
  const maxDeleteBytesPerTick = normalizeOptionalPositiveInteger(request.maxDeleteBytesPerTick);
  if (maxDeleteBytesPerTick !== undefined) body.maxDeleteBytesPerTick = maxDeleteBytesPerTick;
  if (request.reason?.trim()) body.reason = request.reason.trim();

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
  const body = buildArtifactGcRequestBody(request);

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

function buildArtifactGcRequestBody(request: WorkflowArtifactGcPreviewRequest) {
  const body: WorkflowArtifactGcPreviewRequest = {
    actor: request.actor?.trim() || "web-ui",
  };
  if (request.serverId) body.serverId = request.serverId;
  if (request.policyId?.trim()) body.policyId = request.policyId.trim();
  if (request.policyFingerprint?.trim()) body.policyFingerprint = request.policyFingerprint.trim();
  if (request.policyVersion !== undefined) {
    const policyVersion = normalizeOptionalNonNegativeInteger(request.policyVersion);
    if (policyVersion !== undefined) body.policyVersion = policyVersion;
  }
  if (request.persisted !== undefined) body.persisted = request.persisted;
  const retentionDays = normalizeOptionalNonNegativeInteger(request.retentionDays);
  if (retentionDays !== undefined) body.retentionDays = retentionDays;
  const eligibleRunStatuses = normalizeRunStatuses(request.eligibleRunStatuses);
  if (eligibleRunStatuses.length) body.eligibleRunStatuses = eligibleRunStatuses;
  const quotaBytes = normalizeOptionalNonNegativeInteger(request.quotaBytes);
  if (quotaBytes !== undefined) body.quotaBytes = quotaBytes;
  const maxDeleteBytes = normalizeOptionalPositiveInteger(request.maxDeleteBytes);
  if (maxDeleteBytes !== undefined) body.maxDeleteBytes = maxDeleteBytes;
  const maxDeleteBytesPerTick = normalizeOptionalPositiveInteger(request.maxDeleteBytesPerTick);
  if (maxDeleteBytesPerTick !== undefined) body.maxDeleteBytesPerTick = maxDeleteBytesPerTick;
  if (request.reason?.trim()) body.reason = request.reason.trim();
  return body;
}

function invalidateArtifactLifecycleCaches() {
  invalidateAsyncCachePrefix(ARTIFACT_LIFECYCLE_USAGE_CACHE_KEY);
  invalidateAsyncCachePrefix(ARTIFACT_LIFECYCLE_TICKS_CACHE_KEY);
}

function normalizeRunStatuses(value?: string[]) {
  return Array.from(
    new Set(
      (value || [])
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function normalizeOptionalPositiveInteger(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  const normalized = Math.floor(value);
  return normalized > 0 ? normalized : undefined;
}

function normalizeOptionalNonNegativeInteger(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return undefined;
  }
  return Math.max(0, Math.floor(value));
}
