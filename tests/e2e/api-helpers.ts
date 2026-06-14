import { APIRequestContext, request } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE || "http://127.0.0.1:8765";
const REQUIRED_WORKFLOW_ID = process.env.E2E_WORKFLOW_ID || "file-summary-v1";

type WorkflowReadyTool = {
  id: string;
  name: string;
  toolRevisionId: string;
  ruleTemplate: {
    inputs?: Array<{ name?: string; required?: boolean }>;
    outputs?: Array<{ name?: string }>;
    params?: Record<string, unknown>;
  };
};

export type E2EFixture = {
  serverId: string;
  workflow: any;
  workflowReadyTool: WorkflowReadyTool;
};

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

export async function prepareE2EFixture(api: APIRequestContext): Promise<E2EFixture> {
  const [serverId, workflow, workflowReadyTool] = await Promise.all([
    fetchReadyServerId(api),
    requireWorkflow(api, REQUIRED_WORKFLOW_ID),
    requireWorkflowReadyTool(api),
  ]);
  return { serverId, workflow, workflowReadyTool };
}

export async function fetchRuns(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/runs?refresh=true");
  if (!response.ok()) throw new Error(`Failed to fetch runs: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function fetchRunDetail(api: APIRequestContext, runId: string): Promise<any> {
  const response = await api.get(`/api/v1/runs/${encodeURIComponent(runId)}/detail`);
  if (!response.ok()) throw new Error(`Failed to fetch run detail: ${response.status()}`);
  const body = await response.json();
  return body.data?.run;
}

export async function fetchRunEvents(api: APIRequestContext, runId: string): Promise<any[]> {
  const response = await api.get(`/api/v1/runs/${encodeURIComponent(runId)}/events`);
  if (!response.ok()) throw new Error(`Failed to fetch events: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || body.data || [];
}

export async function fetchRunResults(api: APIRequestContext, runId: string): Promise<any[]> {
  const bundle = await fetchRunResultBundle(api, runId);
  return bundle.artifacts || [];
}

export async function fetchRunResultBundle(api: APIRequestContext, runId: string): Promise<any> {
  const response = await api.get(`/api/v1/runs/${encodeURIComponent(runId)}/results`);
  if (!response.ok()) throw new Error(`Failed to fetch results: ${response.status()}`);
  const body = await response.json();
  return body.data || {};
}

export async function fetchResultPreview(api: APIRequestContext, resultId: string, artifactId: string): Promise<any> {
  const response = await api.get(`/api/v1/results/${encodeURIComponent(resultId)}/preview?artifact_id=${encodeURIComponent(artifactId)}`);
  if (!response.ok()) throw new Error(`Failed to fetch preview: ${response.status()}`);
  const body = await response.json();
  return body.data;
}

export async function fetchWorkflowCatalog(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/workflow-catalog?refresh=true");
  if (!response.ok()) throw new Error(`Failed to fetch catalog: ${response.status()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function requireWorkflow(api: APIRequestContext, workflowId: string): Promise<any> {
  const catalog = await fetchWorkflowCatalog(api);
  const workflow = catalog.find((item: any) => item.id === workflowId);
  if (!workflow) {
    throw new Error(`P0_2_WORKFLOW_REQUIRED: ${workflowId} is not available in workflow catalog`);
  }
  return workflow;
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
  const response = await api.post(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`);
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
  mimeType: string,
  serverId?: string
): Promise<any> {
  const response = await api.post("/api/v1/uploads", {
    data: { ...(serverId ? { serverId } : {}), filename, contentBase64, mimeType },
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
    if (terminalStatuses.has(String(detail.status || "").toLowerCase())) {
      return detail;
    }
    await new Promise((r) => setTimeout(r, 2_000));
  }
  throw new Error(`Run ${runId} did not reach terminal state within ${timeoutMs}ms`);
}

export async function waitForCompletedRun(
  api: APIRequestContext,
  runId: string,
  timeoutMs = 120_000
): Promise<any> {
  const detail = await waitForRunTerminal(api, runId, timeoutMs);
  if (String(detail.status || "").toLowerCase() !== "completed") {
    throw new Error(`P0_2_RUN_COMPLETION_REQUIRED: ${runId} ended as ${detail.status}`);
  }
  return detail;
}

export async function fetchReadyServerId(api: APIRequestContext): Promise<string> {
  const response = await api.get("/api/v1/servers");
  if (!response.ok()) throw new Error(`Failed to fetch servers: ${response.status()}`);
  const body = await response.json();
  const servers = body.data?.items || [];
  const readyServer = servers.find((server: any) => server.runner?.ready);
  const serverId = String(readyServer?.serverId || "").trim();
  if (!serverId) throw new Error("P0_2_READY_REMOTE_RUNNER_REQUIRED: no ready remote runner is available");
  return serverId;
}

export async function buildTestRunSpec(
  api: APIRequestContext,
  fixture: Pick<E2EFixture, "serverId" | "workflow">,
  projectId: string,
  suffix: string
) {
  const filename = `e2e-${suffix}-${Date.now()}.fastq`;
  const content = "@read-1\nACGTACGT\n+\nIIIIIIII\n";
  const upload = await uploadFile(
    api,
    filename,
    Buffer.from(content, "utf8").toString("base64"),
    "text/plain",
    fixture.serverId
  );
  const uploadId = String(upload?.uploadId || "").trim();
  if (!uploadId) throw new Error("E2E fixture upload did not return uploadId");

  return {
    serverId: fixture.serverId,
    requestId: `req_e2e_${suffix}_${Date.now()}`,
    idempotencyKey: `idem_e2e_${suffix}_${Date.now()}`,
    runSpec: {
      pipelineId: fixture.workflow.id,
      projectId,
      pipelineVersion: fixture.workflow.version || "0.1.0",
      runSpecVersion: "2026-04-21",
      params: {},
      inputs: [{ uploadId, filename, role: "reads" }],
    },
  };
}

export async function createAndCompletePipelineRun(
  api: APIRequestContext,
  fixture: E2EFixture,
  suffix: string
): Promise<any> {
  const runSpec = await buildTestRunSpec(api, fixture, "proj_e2e_lifecycle", suffix);
  const submitted = await submitRun(api, runSpec);
  const runId = String(submitted?.runId || "").trim();
  if (!runId) throw new Error("P0_2_RUN_ID_REQUIRED: submit did not return runId");
  return await waitForCompletedRun(api, runId);
}

export async function requireWorkflowReadyTool(api: APIRequestContext): Promise<WorkflowReadyTool> {
  const response = await api.get("/api/v1/tools?refresh=true");
  if (!response.ok()) throw new Error(`Failed to fetch tools: ${response.status()}`);
  const body = await response.json();
  const tools = body.data?.items || [];
  const tool = tools.find((item: any) => isWorkflowReadyTool(item));
  if (!tool) {
    throw new Error("P0_2_WORKFLOW_READY_TOOL_REQUIRED: register and validate at least one WorkflowReady tool before running E2E");
  }
  return {
    id: String(tool.id),
    name: String(tool.name || tool.id),
    toolRevisionId: String(tool.toolRevisionId),
    ruleTemplate: tool.ruleTemplate,
  };
}

export async function createWorkflowDesignFixture(
  api: APIRequestContext,
  fixture: E2EFixture,
  suffix: string
): Promise<{ draft: any; plan: any; compiled: any }> {
  const draft = buildWorkflowDesignDraft(fixture.workflowReadyTool, suffix);
  const createdResponse = await api.post("/api/v1/workflow-design-drafts", {
    data: { serverId: fixture.serverId, draft },
  });
  if (!createdResponse.ok()) {
    throw new Error(`Failed to create workflow design draft: ${createdResponse.status()} ${await createdResponse.text()}`);
  }
  const created = (await createdResponse.json()).data;
  const draftId = String(created?.draftId || "").trim();
  if (!draftId) throw new Error("P0_2_DRAFT_ID_REQUIRED: create draft did not return draftId");

  const planResponse = await api.post(`/api/v1/workflow-design-drafts/${encodeURIComponent(draftId)}/plan`, {
    data: { serverId: fixture.serverId },
  });
  if (!planResponse.ok()) {
    throw new Error(`WorkflowDesignDraft plan failed: ${planResponse.status()} ${await planResponse.text()}`);
  }
  const plan = (await planResponse.json()).data;
  if (plan?.valid !== true) {
    throw new Error(`P0_2_DRAFT_PLAN_VALID_REQUIRED: ${JSON.stringify(plan?.validationIssues || [])}`);
  }

  const compileResponse = await api.post(`/api/v1/workflow-design-drafts/${encodeURIComponent(draftId)}/compile`, {
    data: { serverId: fixture.serverId },
  });
  if (!compileResponse.ok()) {
    throw new Error(`WorkflowDesignDraft compile failed: ${compileResponse.status()} ${await compileResponse.text()}`);
  }
  const compiled = (await compileResponse.json()).data;
  const workflowRevisionId = String(compiled?.workflowRevisionId || "").trim();
  if (!workflowRevisionId) throw new Error("P0_2_WORKFLOW_REVISION_REQUIRED: compile did not return workflowRevisionId");
  if (compiled?.runSpec?.workflowRevisionId !== workflowRevisionId) {
    throw new Error("P0_2_WORKFLOW_REVISION_RUN_SPEC_MISMATCH");
  }
  return { draft: created, plan, compiled };
}

export async function submitWorkflowDesignRun(
  api: APIRequestContext,
  fixture: E2EFixture,
  compiled: any,
  suffix: string
): Promise<any> {
  const runSpec = { ...(compiled.runSpec || {}) };
  const plannedInput = Array.isArray(runSpec.inputs) ? runSpec.inputs[0] : null;
  if (!plannedInput?.role || !plannedInput?.filename) {
    throw new Error("P0_2_WORKFLOW_DESIGN_INPUT_REQUIRED");
  }
  const upload = await uploadFile(
    api,
    String(plannedInput.filename),
    Buffer.from("@read-1\nACGTACGT\n+\nIIIIIIII\n", "utf8").toString("base64"),
    "text/plain",
    fixture.serverId
  );
  runSpec.inputs = [
    {
      uploadId: upload.uploadId,
      filename: plannedInput.filename,
      role: plannedInput.role,
    },
  ];
  return await submitRun(api, {
    serverId: fixture.serverId,
    requestId: `req_e2e_design_${suffix}_${Date.now()}`,
    idempotencyKey: `idem_e2e_design_${suffix}_${Date.now()}`,
    runSpec,
  });
}

function isWorkflowReadyTool(tool: any): boolean {
  const revisionId = String(tool?.toolRevisionId || "").trim();
  const template = tool?.ruleTemplate;
  if (!revisionId || !template || typeof template !== "object") return false;
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  const outputs = Array.isArray(template.outputs) ? template.outputs : [];
  if (!inputs.some((item: any) => String(item?.name || "").trim())) return false;
  if (!outputs.some((item: any) => String(item?.name || "").trim())) return false;
  const contract = tool?.toolContract || {};
  if (contract.workflowReady === true || contract.state === "WorkflowReady" || contract.state === "ProductionEnabled") return true;
  const status = tool?.contractStatus || {};
  return ["dryRun", "smokeRun", "outputValidation"].every((key) => status?.[key]?.status === "passed");
}

function buildWorkflowDesignDraft(tool: WorkflowReadyTool, suffix: string): Record<string, unknown> {
  const inputName = firstNamedPort(tool.ruleTemplate.inputs, "input");
  const outputName = firstNamedPort(tool.ruleTemplate.outputs, "output");
  const params = defaultParams(tool.ruleTemplate.params);
  return {
    contractVersion: "workflow-design-draft-v1",
    engine: "snakemake",
    metadata: {
      name: `E2E WorkflowRevision ${suffix}`,
      description: "Playwright P0-2 fixture",
      projectId: "proj_e2e_design",
      tags: ["e2e", "p0-2"],
    },
    inputs: [
      {
        id: "reads",
        role: "input",
        path: "inputs/e2e.fastq",
        filename: "e2e.fastq",
        mimeType: "text/plain",
        metadata: { source: "playwright" },
      },
    ],
    nodes: [
      {
        id: "e2e_step",
        toolRevisionId: tool.toolRevisionId,
        inputs: { [inputName]: { fromInput: "input" } },
        params,
        runtime: { threads: 1, schedulerResources: { mem_mb: 128 } },
        resources: {},
        outputs: { [outputName]: { expose: true, metadata: { source: "playwright" } } },
        metadata: { toolId: tool.id },
        provenance: { createdBy: "playwright" },
      },
    ],
    edges: [],
    resources: { bindings: {}, metadata: { selectionMode: "e2e" } },
    outputs: [
      {
        from: { nodeId: "e2e_step", port: outputName },
        as: "e2e_output",
        metadata: { source: "playwright" },
      },
    ],
    provenance: { createdBy: "playwright" },
  };
}

function firstNamedPort(items: Array<{ name?: string }> | undefined, fallback: string): string {
  const item = (items || []).find((entry) => String(entry?.name || "").trim());
  return String(item?.name || fallback).trim();
}

function defaultParams(raw: Record<string, unknown> | undefined): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(raw || {})) {
    if (value && typeof value === "object" && !Array.isArray(value) && "default" in value) {
      const defaultValue = (value as { default?: unknown }).default;
      if (["string", "number", "boolean"].includes(typeof defaultValue)) {
        params[key] = defaultValue as string | number | boolean;
      }
    } else if (["string", "number", "boolean"].includes(typeof value)) {
      params[key] = value as string | number | boolean;
    }
  }
  return params;
}
