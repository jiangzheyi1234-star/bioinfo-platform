"use client";

export const ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION = "release-artifact-cache-policy-pin";

export type WorkflowArtifactCacheEntryList = {
  schemaVersion?: string;
  redactionPolicy?: Record<string, boolean>;
  items: WorkflowArtifactCacheEntry[];
};

export type WorkflowArtifactCachePinList = {
  schemaVersion?: string;
  redactionPolicy?: Record<string, boolean>;
  items: WorkflowArtifactCachePin[];
};

export type WorkflowArtifactCacheEntry = {
  cacheEntryId: string;
  artifactBlobId?: string;
  storageBackend?: string;
  sizeBytes?: number;
  sha256?: string;
  lifecycleState?: string;
  createdAt?: string;
  lastUsedAt?: string;
  hitCount?: number;
  cacheKeyFingerprint?: string;
  workflowRevisionFingerprint?: string;
};

export type WorkflowArtifactCachePin = {
  cachePinId: string;
  cacheEntryId: string;
  artifactBlobId?: string;
  storageBackend?: string;
  sha256?: string;
  pinScope?: string;
  ownerKind?: string;
  ownerId?: string;
  reason?: string;
  state?: string;
  createdAt?: string;
  releasedAt?: string;
  expiresAt?: string | null;
  cacheKeyFingerprint?: string;
};

export type WorkflowArtifactCachePinRetainRequest = {
  serverId?: string;
  ownerId?: string;
  reason?: string;
  expiresAt?: string;
  actor?: string;
};

export type WorkflowArtifactCachePinReleaseRequest = {
  serverId?: string;
  confirmation: string;
  reason?: string;
  actor?: string;
};
