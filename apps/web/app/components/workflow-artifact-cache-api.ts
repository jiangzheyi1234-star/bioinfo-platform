"use client";

import { cachedAsync, invalidateAsyncCachePrefix } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowArtifactCacheEntryList,
  WorkflowArtifactCachePinList,
  WorkflowArtifactCachePinReleaseRequest,
  WorkflowArtifactCachePinRetainRequest,
} from "./workflow-artifact-cache-model";

type ArtifactCacheFetchOptions = {
  forceRefresh?: boolean;
  serverId?: string;
  limit?: number;
  state?: string;
};

const ARTIFACT_CACHE_ENTRIES_CACHE = "workflow:artifact-cache-entries";
const ARTIFACT_CACHE_PINS_CACHE = "workflow:artifact-cache-pins";

export async function fetchArtifactCacheEntries(
  options: ArtifactCacheFetchOptions = {}
): Promise<WorkflowArtifactCacheEntryList> {
  const limit = normalizeLimit(options.limit);
  const key = [
    ARTIFACT_CACHE_ENTRIES_CACHE,
    options.serverId || "default",
    limit,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<{ data: WorkflowArtifactCacheEntryList }>(
      "GET",
      `/api/v1/artifacts/cache/entries${artifactCacheQuery({ ...options, limit })}`,
      { cache: "no-store" }
    );
    return {
      schemaVersion: response.data.schemaVersion,
      redactionPolicy: response.data.redactionPolicy,
      items: response.data.items || [],
    };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function fetchArtifactCachePins(
  options: ArtifactCacheFetchOptions = {}
): Promise<WorkflowArtifactCachePinList> {
  const limit = normalizeLimit(options.limit);
  const key = [
    ARTIFACT_CACHE_PINS_CACHE,
    options.serverId || "default",
    options.state || "all",
    limit,
  ].join(":");
  return cachedAsync(key, 10_000, async () => {
    const response = await requestLocalApiJson<{ data: WorkflowArtifactCachePinList }>(
      "GET",
      `/api/v1/artifacts/cache/pins${artifactCacheQuery({ ...options, limit })}`,
      { cache: "no-store" }
    );
    return {
      schemaVersion: response.data.schemaVersion,
      redactionPolicy: response.data.redactionPolicy,
      items: response.data.items || [],
    };
  }, {
    forceRefresh: options.forceRefresh,
  });
}

export async function retainArtifactCacheEntry(
  cacheEntryId: string,
  request: WorkflowArtifactCachePinRetainRequest = {}
) {
  const body: WorkflowArtifactCachePinRetainRequest = {
    actor: request.actor?.trim() || "web-ui",
    reason: request.reason?.trim() || "web-ui-retain",
  };
  if (request.serverId) body.serverId = request.serverId;
  if (request.ownerId?.trim()) body.ownerId = request.ownerId.trim();
  if (request.expiresAt?.trim()) body.expiresAt = request.expiresAt.trim();
  await requestLocalApiJson<{ data: unknown }>(
    "POST",
    `/api/v1/artifacts/cache/entries/${encodeURIComponent(cacheEntryId)}/retain`,
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  invalidateArtifactCache();
}

export async function releaseArtifactCachePolicyPin(
  cachePinId: string,
  request: WorkflowArtifactCachePinReleaseRequest
) {
  const body: WorkflowArtifactCachePinReleaseRequest = {
    actor: request.actor?.trim() || "web-ui",
    confirmation: request.confirmation.trim(),
  };
  if (request.serverId) body.serverId = request.serverId;
  if (request.reason?.trim()) body.reason = request.reason.trim();
  await requestLocalApiJson<{ data: unknown }>(
    "POST",
    `/api/v1/artifacts/cache/pins/${encodeURIComponent(cachePinId)}/release`,
    {
      body,
      cache: "no-store",
      timeoutMs: 20_000,
    }
  );
  invalidateArtifactCache();
}

function artifactCacheQuery(options: ArtifactCacheFetchOptions) {
  const params = new URLSearchParams();
  if (options.forceRefresh) params.set("refresh", "true");
  if (options.serverId) params.set("serverId", options.serverId);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.state) params.set("state", options.state);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function normalizeLimit(value?: number) {
  return Math.max(1, Math.min(Math.floor(value || 25), 100));
}

function invalidateArtifactCache() {
  invalidateAsyncCachePrefix(ARTIFACT_CACHE_ENTRIES_CACHE);
  invalidateAsyncCachePrefix(ARTIFACT_CACHE_PINS_CACHE);
}
