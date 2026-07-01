import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type { WorkflowLogLines } from "./workflows-page-model";

export type WorkflowRunLogStream = "stdout" | "stderr";

export type WorkflowRunLogPage = WorkflowLogLines & {
  runId?: string;
  stream?: WorkflowRunLogStream;
  cursor?: string;
};

export async function fetchWorkflowRunLogs(
  runId: string,
  stream: WorkflowRunLogStream,
  cursor?: string
): Promise<WorkflowRunLogPage> {
  const normalizedRunId = runId.trim();
  if (!normalizedRunId) {
    throw new Error("WORKFLOW_RUN_ID_REQUIRED");
  }
  const params = new URLSearchParams();
  params.set("stream", stream);
  if (cursor) params.set("cursor", cursor);
  const response = await requestLocalApiJson<{ data: WorkflowRunLogPage }>(
    "GET",
    `/api/v1/runs/${encodeURIComponent(normalizedRunId)}/logs?${params.toString()}`,
    { cache: "no-store" }
  );
  return response.data;
}
