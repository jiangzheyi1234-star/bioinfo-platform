"use client";

import { cachedAsync } from "@/app/lib/async-cache";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type { WorkflowRunAttemptsReadModel, WorkflowRunAttemptsResponse } from "./workflow-run-attempts-model";

const RUN_ATTEMPTS_CACHE_KEY = "workflow:run-attempts";

export async function fetchWorkflowRunAttempts(
  runId: string,
  options: { forceRefresh?: boolean } = {}
): Promise<WorkflowRunAttemptsReadModel> {
  const normalizedRunId = runId.trim();
  if (!normalizedRunId) {
    throw new Error("WORKFLOW_RUN_ID_REQUIRED");
  }
  const key = `${RUN_ATTEMPTS_CACHE_KEY}:${normalizedRunId}`;
  return cachedAsync(key, 6_000, async () => {
    const response = await requestLocalApiJson<WorkflowRunAttemptsResponse>(
      "GET",
      `/api/v1/runs/${encodeURIComponent(normalizedRunId)}/attempts`,
      { cache: "no-store" }
    );
    return {
      ...response.data,
      attempts: response.data.attempts || [],
      slots: response.data.slots || [],
    };
  }, {
    forceRefresh: options.forceRefresh,
  });
}
