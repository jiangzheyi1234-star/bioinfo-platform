"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

export type WorkflowSampleDataStatus = {
  schemaVersion?: string;
  pipelineId: string;
  source?: string;
  cachePolicy?: string;
  status: "ready" | "source_required" | "blocked" | string;
  itemCount?: number;
  verifiedCacheCount?: number;
  missingCacheCount?: number;
  sourceRequired?: boolean;
  blockerCodes?: string[];
  items?: WorkflowSampleDataStatusItem[];
};

export type WorkflowSampleDataStatusItem = {
  filename: string;
  role: string;
  sourceUrl?: string;
  expectedSha256?: string;
  expectedSizeBytes?: number;
  sizeBytes?: number;
  observedSizeBytes?: number;
  sha256?: string;
  cacheStatus: "verified" | "missing" | "integrity_mismatch" | "unreadable" | string;
  status: "ready" | "source_required" | "blocked" | string;
  sourceRequired?: boolean;
  blockerCodes?: string[];
};

export async function fetchWorkflowSampleDataStatus(pipelineId: string): Promise<WorkflowSampleDataStatus> {
  const normalizedPipelineId = pipelineId.trim();
  if (!normalizedPipelineId) {
    throw new Error("pipelineId is required");
  }
  const response = await requestLocalApiJson<{ data: WorkflowSampleDataStatus }>(
    "GET",
    `/api/v1/workflow-sample-data/${encodeURIComponent(normalizedPipelineId)}/status`,
    { cache: "no-store", timeoutMs: 30_000 }
  );
  return response.data;
}
