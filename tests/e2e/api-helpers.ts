import { APIRequestContext, request } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE || "http://127.0.0.1:8765";

export async function createApiClient(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: API_BASE });
}

export async function waitForApiReady(api: APIRequestContext, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await api.get("/health");
      if (response.ok()) return;
    } catch {
      // API not ready yet
    }
    await new Promise((r) => setTimeout(r, 1_000));
  }
  throw new Error(`API not ready after ${timeoutMs}ms`);
}

export async function fetchRuns(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/runs");
  if (!response.ok()) throw new Error(`Failed to fetch runs: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function fetchRunDetail(api: APIRequestContext, runId: string): Promise<any> {
  const response = await api.get(`/api/v1/runs/${runId}/detail`);
  if (!response.ok()) throw new Error(`Failed to fetch run detail: ${response.status()}`);
  const body = await response.json();
  return body.data?.run;
}

export async function fetchRunEvents(api: APIRequestContext, runId: string): Promise<any[]> {
  const response = await api.get(`/api/v1/runs/${runId}/events`);
  if (!response.ok()) throw new Error(`Failed to fetch events: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || body.data || [];
}

export async function fetchRunResults(api: APIRequestContext, runId: string): Promise<any[]> {
  const response = await api.get(`/api/v1/runs/${runId}/results`);
  if (!response.ok()) throw new Error(`Failed to fetch results: ${response.status()}`);
  const body = await response.json();
  return body.data?.artifacts || [];
}

export async function fetchResultPreview(api: APIRequestContext, resultId: string, artifactId: string): Promise<any> {
  const response = await api.get(`/api/v1/results/${resultId}/preview?artifact_id=${encodeURIComponent(artifactId)}`);
  if (!response.ok()) throw new Error(`Failed to fetch preview: ${response.status()}`);
  const body = await response.json();
  return body.data;
}

export async function fetchWorkflowCatalog(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/workflow-catalog");
  if (!response.ok()) throw new Error(`Failed to fetch catalog: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function submitRun(
  api: APIRequestContext,
  payload: Record<string, unknown>
): Promise<any> {
  const response = await api.post("/api/v1/runs", { data: payload });
  if (!response.ok()) {
    const text = await response.text();
    throw new Error(`Failed to submit run: ${response.status()} ${text}`);
  }
  const body = await response.json();
  return body.data;
}

export async function cancelRun(api: APIRequestContext, runId: string): Promise<any> {
  const response = await api.post(`/api/v1/runs/${runId}/cancel`);
  if (!response.ok()) {
    const text = await response.text();
    throw new Error(`Failed to cancel run: ${response.status()} ${text}`);
  }
  const body = await response.json();
  return body.data;
}

export async function uploadFile(
  api: APIRequestContext,
  filename: string,
  contentBase64: string,
  mimeType: string
): Promise<any> {
  const response = await api.post("/api/v1/uploads", {
    data: { filename, contentBase64, mimeType },
  });
  if (!response.ok()) {
    const text = await response.text();
    throw new Error(`Failed to upload: ${response.status()} ${text}`);
  }
  const body = await response.json();
  return body.data;
}

export async function waitForRunTerminal(
  api: APIRequestContext,
  runId: string,
  timeoutMs = 120_000
): Promise<any> {
  const terminalStatuses = new Set(["completed", "failed", "canceled", "cancelled"]);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const detail = await fetchRunDetail(api, runId);
    if (terminalStatuses.has(detail.status?.toLowerCase())) {
      return detail;
    }
    await new Promise((r) => setTimeout(r, 2_000));
  }
  throw new Error(`Run ${runId} did not reach terminal state within ${timeoutMs}ms`);
}

export async function fetchReadyServerId(api: APIRequestContext): Promise<string> {
  const response = await api.get("/api/v1/servers");
  if (!response.ok()) throw new Error(`Failed to fetch servers: ${response.status()}`);
  const body = await response.json();
  const servers = body.data?.items || [];
  const readyServer = servers.find((server: any) => server.runner?.ready);
  const serverId = String(readyServer?.serverId || "").trim();
  if (!serverId) throw new Error("No ready remote runner is available for E2E tests");
  return serverId;
}

export async function buildTestRunSpec(
  api: APIRequestContext,
  workflow: any,
  projectId: string,
  suffix: string
) {
  const serverId = await fetchReadyServerId(api);
  const filename = `e2e-${suffix}-${Date.now()}.fastq`;
  const fixture = "@read-1\nACGTACGT\n+\nIIIIIIII\n";
  const upload = await uploadFile(
    api,
    filename,
    Buffer.from(fixture, "utf8").toString("base64"),
    "text/plain"
  );
  const uploadId = String(upload?.uploadId || "").trim();
  if (!uploadId) throw new Error("E2E fixture upload did not return uploadId");

  return {
    serverId,
    requestId: `req_e2e_${suffix}_${Date.now()}`,
    idempotencyKey: `idem_e2e_${suffix}_${Date.now()}`,
    runSpec: {
      pipelineId: workflow.id,
      projectId,
      pipelineVersion: workflow.version || "0.1.0",
      runSpecVersion: "2026-04-21",
      params: {},
      inputs: [{ uploadId, filename, role: "reads" }],
    },
  };
}
