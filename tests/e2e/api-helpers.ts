import { APIRequestContext, request } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE || "http://127.0.0.1:8765";
const REQUIRED_WORKFLOW_ID = process.env.E2E_WORKFLOW_ID || "file-summary-v1";
export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";
export const E2E_VALIDATION_TOOL_PACK_ID = "h2ometa-e2e-validation-queue-pack";

const DEFAULT_DATABASE_TEMPLATE_ID = process.env.E2E_DATABASE_TEMPLATE_ID || "kraken2";
const LOCAL_E2E_API_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const PREFERRED_WORKFLOW_READY_TOOL_IDS = (
  process.env.E2E_WORKFLOW_READY_TOOL_ID || "bioconda::seqkit-stats,bioconda::seqkit-subseq,bioconda::mash-sketch"
)
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

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
  if (!response.ok()) throw new Error(`Failed to fetch runs: ${response.status()} ${await response.text()}`);
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

export async function fetchDatabases(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/databases?refresh=true");
  if (!response.ok()) throw new Error(`Failed to fetch databases: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function fetchDatabaseTemplates(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/database-templates?refresh=true");
  if (!response.ok()) throw new Error(`Failed to fetch database templates: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return body.data?.items || [];
}

export async function requireDatabaseRegistrationFixture(
  api: APIRequestContext
): Promise<{ templateId: string; path: string; source: string }> {
  const templates = await fetchDatabaseTemplates(api);
  const templateById = new Map(templates.map((item: any) => [String(item.id || "").toLowerCase(), item]));
  const envPath = String(process.env.E2E_DATABASE_PATH || "").trim();
  const envTemplateId = String(DEFAULT_DATABASE_TEMPLATE_ID || "").trim().toLowerCase();
  if (envPath) {
    if (!templateById.has(envTemplateId)) {
      throw new Error(`P0_12_DATABASE_TEMPLATE_REQUIRED: ${envTemplateId} is not available in /api/v1/database-templates`);
    }
    return { templateId: envTemplateId, path: envPath, source: "env" };
  }

  const databases = await fetchDatabases(api);
  const candidate = databases.find((item: any) => {
    const templateId = String(item?.metadata?.templateId || "").trim().toLowerCase();
    const template = templateById.get(templateId);
    const selectorKind = String(template?.selectorKind || template?.pathKind || "");
    return (
      String(item?.status || "").toLowerCase() === "available" &&
      templateId &&
      template &&
      selectorKind !== "composite" &&
      String(item?.path || item?.inputPath || "").trim()
    );
  });
  if (candidate) {
    return {
      templateId: String(candidate.metadata.templateId).toLowerCase(),
      path: String(candidate.inputPath || candidate.path),
      source: `existing:${candidate.id}`,
    };
  }
  throw new Error(
    "P0_12_DATABASE_FIXTURE_REQUIRED: set E2E_DATABASE_PATH to a remote-runner path that matches E2E_DATABASE_TEMPLATE_ID, " +
      "or pre-register one available non-composite database before running this E2E."
  );
}

export async function findDatabaseByName(api: APIRequestContext, name: string): Promise<any | null> {
  const databases = await fetchDatabases(api);
  return databases.find((item: any) => item.name === name) || null;
}

export async function deleteDatabase(api: APIRequestContext, databaseId: string): Promise<void> {
  const response = await api.delete(`/api/v1/databases/${encodeURIComponent(databaseId)}`);
  if (!response.ok() && response.status() !== 404) {
    throw new Error(`Failed to delete database ${databaseId}: ${response.status()} ${await response.text()}`);
  }
}

export async function fetchCapabilityGraphSnapshot(api: APIRequestContext): Promise<any> {
  const response = await api.get("/api/v1/tool-capabilities/capability-graph?q=&page=1&pageSize=100&targetPlatform=linux-64");
  if (!response.ok()) throw new Error(`Failed to fetch capability graph: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return body.data;
}

export async function requireValidationQueueCandidate(api: APIRequestContext): Promise<any> {
  return waitForValidationQueueCandidate(api);
}

export async function seedValidationQueueCandidate(
  api: APIRequestContext
): Promise<{ candidate: any; packId: string }> {
  assertLocalE2EApiBase();
  const fixture = e2eValidationQueuePackFixture();
  await deleteBioToolPack(api, E2E_VALIDATION_TOOL_PACK_ID);
  await importBioToolPack(api, fixture.manifest, true);
  const candidate = await waitForValidationQueueCandidate(api, fixture.candidateId);
  return { candidate, packId: E2E_VALIDATION_TOOL_PACK_ID };
}

export async function deleteBioToolPack(api: APIRequestContext, packId: string): Promise<void> {
  assertLocalE2EApiBase();
  const items = await fetchBioToolPacks(api);
  if (!items.some((item: any) => item?.packId === packId)) return;
  const response = await api.delete(`/api/v1/tool-capabilities/tool-packs/${encodeURIComponent(packId)}`);
  if (!response.ok()) {
    throw new Error(`Failed to delete tool pack ${packId}: ${response.status()} ${await response.text()}`);
  }
}

export async function fetchToolPrepareJob(api: APIRequestContext, jobId: string): Promise<any> {
  const response = await api.get(`/api/v1/tools/prepare-jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok()) throw new Error(`Failed to fetch prepare job: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return body.data;
}

export async function cancelToolPrepareJob(api: APIRequestContext, jobId: string): Promise<void> {
  const response = await api.post(`/api/v1/tools/prepare-jobs/${encodeURIComponent(jobId)}/cancel`, { data: {} });
  if (!response.ok()) {
    const body = await response.text();
    if (!/terminal|succeeded|failed|cancelled|waiting_resource|exhausted/i.test(body)) {
      throw new Error(`Failed to cancel prepare job ${jobId}: ${response.status()} ${body}`);
    }
  }
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
  const workflowReadyTools = tools.filter((item: any) => isWorkflowReadyTool(item));
  const tool = preferredWorkflowReadyTool(workflowReadyTools) || workflowReadyTools[0];
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
  const { record: created } = await createWorkflowDesignDraftRecord(api, fixture, suffix);
  const draftId = String(created?.draftId || "").trim();

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

export async function createWorkflowDesignDraftRecord(
  api: APIRequestContext,
  fixture: E2EFixture,
  suffix: string
): Promise<{ draft: Record<string, unknown>; record: any }> {
  const draft = buildWorkflowDesignDraft(fixture.workflowReadyTool, suffix);
  const createdResponse = await api.post("/api/v1/workflow-design-drafts", {
    data: { serverId: fixture.serverId, draft },
  });
  if (!createdResponse.ok()) {
    throw new Error(`Failed to create workflow design draft: ${createdResponse.status()} ${await createdResponse.text()}`);
  }
  const record = (await createdResponse.json()).data;
  const draftId = String(record?.draftId || "").trim();
  if (!draftId) throw new Error("P0_2_DRAFT_ID_REQUIRED: create draft did not return draftId");
  return { draft, record };
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

function preferredWorkflowReadyTool(tools: any[]): any | null {
  for (const preferredId of PREFERRED_WORKFLOW_READY_TOOL_IDS) {
    const tool = tools.find((item: any) => {
      return [item?.id, item?.toolId, item?.name, item?.toolRevisionId]
        .map((value) => String(value || "").trim())
        .some((value) => value === preferredId || value.startsWith(`${preferredId}#`));
    });
    if (tool) return tool;
  }
  return null;
}

function isActivePrepareJob(job: any): boolean {
  const status = String(job?.status || "").toLowerCase();
  return status === "queued" || status === "running";
}

async function importBioToolPack(api: APIRequestContext, manifest: Record<string, unknown>, enable: boolean): Promise<any> {
  const response = await api.post(`/api/v1/tool-capabilities/tool-packs?enable=${enable ? "true" : "false"}`, {
    data: manifest,
  });
  if (!response.ok()) {
    throw new Error(`Failed to import E2E tool pack: ${response.status()} ${await response.text()}`);
  }
  const body = await response.json();
  return body.data;
}

async function waitForValidationQueueCandidate(
  api: APIRequestContext,
  expectedCandidateId = "",
  timeoutMs = 20_000
): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  let lastQueueSummary = "";
  while (Date.now() < deadline) {
    const graph = await fetchCapabilityGraphSnapshot(api);
    const queue = graph?.targetAcceptance?.validationQueue || {};
    const items = Array.isArray(queue?.items) ? queue.items : [];
    lastQueueSummary = JSON.stringify({
      remaining: queue?.remaining,
      available: queue?.available,
      candidateIds: items.map((item: any) => item?.candidateId).filter(Boolean),
    });
    const candidate = items.find((item: any) => {
      if (expectedCandidateId && item?.candidateId !== expectedCandidateId) return false;
      const payload = item?.preparePayload;
      return payload && typeof payload === "object";
    });
    if (candidate && !isActivePrepareJob(candidate.latestPrepareJob)) return candidate;

    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(
    "P0_12_VALIDATION_QUEUE_ITEM_REQUIRED: /api/v1/tool-capabilities/capability-graph has no validation queue item " +
      `with preparePayload. Last queue: ${lastQueueSummary}`
  );
}

async function fetchBioToolPacks(api: APIRequestContext): Promise<any[]> {
  const response = await api.get("/api/v1/tool-capabilities/tool-packs");
  if (!response.ok()) throw new Error(`Failed to fetch tool packs: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return body.data?.items || [];
}

function assertLocalE2EApiBase(): void {
  if (process.env.E2E_ALLOW_REMOTE_FIXTURE_MUTATION === "1") return;
  const hostname = new URL(API_BASE).hostname.toLowerCase();
  if (LOCAL_E2E_API_HOSTS.has(hostname)) return;
  throw new Error(
    "P0_12_LOCAL_E2E_API_REQUIRED: validation queue fixture mutation is allowed only against localhost " +
      "unless E2E_ALLOW_REMOTE_FIXTURE_MUTATION=1 is set explicitly."
  );
}

function e2eValidationQueuePackFixture(): { candidateId: string; manifest: Record<string, unknown> } {
  const suffix = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const profileId = `e2e-validation-queue-tool-${suffix}`;
  const packageName = `h2ometa-e2e-validation-queue-tool-${suffix}`;
  return {
    candidateId: `h2ometa-tool-profile::${profileId}`,
    manifest: e2eValidationQueuePackManifest({ packageName, profileId }),
  };
}

function e2eValidationQueuePackManifest({
  packageName,
  profileId,
}: {
  packageName: string;
  profileId: string;
}): Record<string, unknown> {
  return {
    contractVersion: "bio-tool-pack-v1",
    packId: E2E_VALIDATION_TOOL_PACK_ID,
    version: "1",
    name: "H2OMeta E2E Validation Queue Pack",
    source: "https://example.test/h2ometa-e2e-validation-queue-pack",
    license: "internal-test-fixture",
    citations: ["H2OMeta E2E validation queue fixture"],
    profiles: [
      {
        profileId,
        version: 1,
        toolNames: [packageName],
        packageName,
        packageSource: "bioconda",
        packageVersion: "0.0.0",
        workflowStage: "e2e-validation",
        operation: "queue-closure-fixture",
        ruleTemplate: {
          commandTemplate: `${packageName} --input {input.reads:q} --output {output.report:q}`,
          inputs: [
            {
              name: "reads",
              type: "file",
              kind: "sequence_reads",
              mimeType: "text/plain",
              required: true,
            },
          ],
          outputs: [
            {
              name: "report",
              path: "results/e2e-validation-report.txt",
              kind: "report",
              mimeType: "text/plain",
            },
          ],
          params: {},
          resources: { threads: { default: 1 }, mem_mb: { default: 128 } },
          environment: {
            conda: {
              channels: ["conda-forge", "bioconda"],
              dependencies: ["{packageSpec}"],
            },
          },
          log: "logs/e2e-validation-queue.log",
          smokeTest: {
            inputs: {
              reads: {
                filename: "reads.fastq",
                content: "@smoke\nACGTACGT\n+\nFFFFFFFF\n",
                mimeType: "text/plain",
              },
            },
            timeoutSeconds: 60,
          },
        },
        reportSchemas: [
          {
            key: "report",
            sourcePort: "report",
            kind: "report",
            assertions: ["exists", "non-empty"],
          },
        ],
      },
    ],
  };
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
