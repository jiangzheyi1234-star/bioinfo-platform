import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";

import {
  createApiClient,
  waitForApiReady,
} from "./api-helpers";

const FASTQ_QC_CAPABILITY_REQUIREMENTS = [
  {
    profileId: "fastqc",
    revisionPattern: /^bioconda::fastqc#[0-9a-f]{12}$/,
    version: "0.12.1",
  },
  {
    profileId: "multiqc",
    revisionPattern: /^bioconda::multiqc#[0-9a-f]{12}$/,
    version: "1.34",
  },
] as const;
const FASTQ_CONTENT = "@agent-e2e\nACGTACGT\n+\nIIIIIIII\n";
const REMOTE_COMMAND_TIMEOUT_MS = 180_000;
const REMOTE_SCENARIO_TIMEOUT_MS = 600_000;

const EDAM_GENERIC_DATA = "http://edamontology.org/data_0006";
const EDAM_SEQUENCE = "http://edamontology.org/data_2044";
const EDAM_QUALITY_CONTROL_REPORT = "http://edamontology.org/data_3914";
const EDAM_FASTQ = "http://edamontology.org/format_1930";
const EDAM_HTML = "http://edamontology.org/format_2331";
const EDAM_ZIP = "http://edamontology.org/format_3987";

type BrowserMutation = {
  method: string;
  path: string;
  postData: string | null;
};

type CreatedPlan = {
  planHash: string;
  planRevisionId: string;
  projectId: string;
  sessionId: string;
  summary: string;
};

type CapabilityPort = {
  data: string;
  format: string;
  kind: string;
  mimeType: string;
  name: string;
  operation: string;
  path?: string;
  required: boolean;
  resource: string;
  type: string;
};

let api: APIRequestContext;
let serverId = "";
let fastqQcRevisions: [string, string] = ["", ""];

test.beforeAll(async () => {
  test.setTimeout(REMOTE_COMMAND_TIMEOUT_MS);
  api = await createApiClient();
  await waitForApiReady(api);
  serverId = await fetchProductionReadyServerId(api);
  fastqQcRevisions = await requireFastqQcCapabilities(api, serverId);
});

test.afterAll(async () => {
  await api?.dispose();
});

test.describe("Agent Workbench durable FASTQ QC control plane", () => {
  test("creates, plans, hash-approves, reloads, and never submits a Run", async ({ page }) => {
    test.setTimeout(REMOTE_SCENARIO_TIMEOUT_MS);

    const mutations = observeBrowserMutations(page);
    const suffix = uniqueSuffix("approve");
    const created = await createPlanThroughUi(page, {
      projectId: `project-agent-e2e-${suffix}`,
      serverId,
      successCriterion: "生成可审查的 FastQC 证据与 MultiQC HTML 报告。",
      summary: `Agent E2E FASTQ QC approval ${suffix}`,
      filename: `agent-e2e-${suffix}.fastq`,
    });

    await expectWorkbenchIdentity(page, serverId, created.sessionId);
    await expect(page.getByTestId("agent-plan-card")).toHaveAttribute("data-plan-valid", "true");
    await expect(page.getByTestId("agent-plan-hash")).toContainText(created.planHash);
    await expect(page.getByTestId("agent-plan-tool")).toHaveCount(2);
    await expect(page.getByTestId("agent-plan-tool").nth(0)).toContainText(fastqQcRevisions[0]);
    await expect(page.getByTestId("agent-plan-tool").nth(1)).toContainText(fastqQcRevisions[1]);
    await assertReadOnlyExecutionGraph(page);

    const approvalOpen = page.getByTestId("agent-approve-open");
    await expect(approvalOpen).toBeEnabled();
    await approvalOpen.click();
    const dialog = page.getByTestId("agent-approve-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(created.planHash);
    await expect(dialog).toContainText(fastqQcRevisions[0]);
    await expect(dialog).toContainText(fastqQcRevisions[1]);
    await dialog.getByLabel("审批备注（可选）").fill("Reviewed exact digest, revisions, resources, outputs, risk, and budget.");
    const reviewConfirmation = dialog.getByTestId("agent-approval-review-confirmation");
    await reviewConfirmation.click();
    await expect(reviewConfirmation).toBeChecked();

    const approvalResponsePromise = page.waitForResponse(
      (response) =>
        apiResponseMatches(response, "POST", new RegExp(`/api/v1/agent-sessions/${escapeRegExp(created.sessionId)}/approval$`)),
      { timeout: REMOTE_COMMAND_TIMEOUT_MS }
    );
    await dialog.getByTestId("agent-approve-confirm").click();
    const approved = await responseData(await approvalResponsePromise);
    expect(approved.session?.sessionId).toBe(created.sessionId);
    expect(approved.session?.status).toBe("ready_to_run");
    expect(approved.approval?.planHash).toBe(created.planHash);
    expect(approved.approval?.scope).toBe("compile_workflow_revision");
    const workflowRevisionId = String(approved.session?.workflowRevisionId || "");
    expect(workflowRevisionId).toMatch(/^wfrev_/);

    const readyPanel = page.getByTestId("agent-ready-to-run");
    await expect(readyPanel).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("agent-workflow-revision-id")).toHaveText(workflowRevisionId);
    await expect(readyPanel).toContainText("本次审批没有提交 Run");
    assertNoRunMutation(mutations);
    assertHashBoundApprovalMutation(mutations, created.sessionId, created.planHash);
    assertBrowserNeverClaimsActor(mutations);

    const durableUrl = page.url();
    await page.reload();
    await expect(page.getByTestId("agent-ready-to-run")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("agent-workflow-revision-id")).toHaveText(workflowRevisionId);
    await expect(page.getByTestId("agent-plan-hash")).toContainText(created.planHash);
    await expectWorkbenchIdentity(page, serverId, created.sessionId);
    expect(page.url()).toBe(durableUrl);
    await assertReadOnlyExecutionGraph(page);
    await assertDurableTimeline(page, [
      "agent.session_created",
      "agent.plan_requested",
      "agent.plan_validated",
      "agent.approval_granted",
      "agent.workflow_revision_compiled",
    ]);
    assertNoRunMutation(mutations);

    const snapshot = await fetchAgentSnapshot(api, serverId, created.sessionId);
    expect(snapshot.session.status).toBe("ready_to_run");
    expect(snapshot.session.workflowRevisionId).toBe(workflowRevisionId);
    expect(snapshot.plans).toHaveLength(1);
    expect(snapshot.plans[0].planHash).toBe(created.planHash);
    expect(snapshot.approvals).toHaveLength(1);
    expect(snapshot.approvals[0]).toMatchObject({
      decision: "approve",
      planHash: created.planHash,
      scope: "compile_workflow_revision",
    });
    expect(snapshot.events.map((event: any) => event.eventType)).toEqual(
      expect.arrayContaining([
        "agent.session_created",
        "agent.plan_requested",
        "agent.plan_validated",
        "agent.approval_granted",
        "agent.workflow_revision_compiled",
      ])
    );
    assertEventHashChain(snapshot.events);
  });

  test("records request_changes, blocks free-text replan, and recovers through a new session", async ({ page }) => {
    test.setTimeout(REMOTE_SCENARIO_TIMEOUT_MS);

    const mutations = observeBrowserMutations(page);
    const suffix = uniqueSuffix("changes");
    const original = await createPlanThroughUi(page, {
      projectId: `project-agent-e2e-${suffix}`,
      serverId,
      successCriterion: "生成 FastQC 与 MultiQC 证据。",
      summary: `Agent E2E request changes ${suffix}`,
      filename: `agent-e2e-${suffix}.fastq`,
    });

    await page.getByTestId("agent-request-changes-open").click();
    const changesDialog = page.getByTestId("agent-request-changes-dialog");
    await expect(changesDialog).toBeVisible();
    await expect(changesDialog).toContainText("当前 FASTQ adapter 不支持 typed adjustment");
    const reason = "Change the scientific target and preserve the old plan lineage.";
    await changesDialog.getByTestId("agent-change-reason").fill(reason);
    const changesResponsePromise = page.waitForResponse(
      (response) =>
        apiResponseMatches(response, "POST", new RegExp(`/api/v1/agent-sessions/${escapeRegExp(original.sessionId)}/approval$`)),
      { timeout: REMOTE_COMMAND_TIMEOUT_MS }
    );
    await changesDialog.getByTestId("agent-request-changes-confirm").click();
    const changed = await responseData(await changesResponsePromise);
    expect(changed.session?.status).toBe("changes_requested");
    expect(changed.approval).toMatchObject({
      decision: "request_changes",
      planHash: original.planHash,
      reason,
    });

    await expect(page.getByTestId("agent-approval-panel")).toHaveAttribute(
      "data-session-status",
      "changes_requested"
    );
    const unsupported = page.getByTestId("agent-replan-unsupported");
    await expect(unsupported).toBeVisible({ timeout: 45_000 });
    await expect(unsupported).toContainText("WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED");
    await expect(unsupported.getByRole("button", { name: "重规划（当前不支持）" })).toBeDisabled();
    expect(mutations.filter((mutation) => /\/replan$/.test(mutation.path))).toHaveLength(0);
    assertNoRunMutation(mutations);
    assertHashBoundApprovalMutation(mutations, original.sessionId, original.planHash, "request_changes");

    const originalSnapshot = await fetchAgentSnapshot(api, serverId, original.sessionId);
    expect(originalSnapshot.session.status).toBe("changes_requested");
    expect(originalSnapshot.approvals.at(-1)).toMatchObject({
      decision: "request_changes",
      planHash: original.planHash,
      reason,
    });
    expect(originalSnapshot.events.some((event: any) => event.eventType === "agent.changes_requested")).toBe(true);
    const replanRequestId = `agent-e2e-replan:${uniqueSuffix("unsupported")}`;
    const rejectedReplan = await api.post(
      `/api/v1/agent-sessions/${encodeURIComponent(original.sessionId)}/replan`,
      {
        data: {
          serverId,
          requestId: replanRequestId,
          idempotencyKey: replanRequestId,
          expectedStateVersion: originalSnapshot.session.stateVersion,
          reason: "Free-text replanning must remain unsupported without a typed adjustment.",
        },
        timeout: REMOTE_COMMAND_TIMEOUT_MS,
      }
    );
    expect(rejectedReplan.status()).toBe(422);
    expect(String((await rejectedReplan.json())?.detail || "")).toContain(
      "WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED"
    );
    const unchangedAfterRejectedReplan = await fetchAgentSnapshot(
      api,
      serverId,
      original.sessionId
    );
    expect(unchangedAfterRejectedReplan.session).toMatchObject({
      activePlanHash: originalSnapshot.session.activePlanHash,
      planGeneration: originalSnapshot.session.planGeneration,
      stateVersion: originalSnapshot.session.stateVersion,
      status: "changes_requested",
    });
    expect(unchangedAfterRejectedReplan.plans).toEqual(originalSnapshot.plans);
    expect(unchangedAfterRejectedReplan.approvals).toEqual(originalSnapshot.approvals);

    await unsupported.getByRole("button", { name: "按新目标创建会话" }).click();
    await expect(page.getByTestId("agent-goal-composer")).toBeVisible();
    await expect(page.getByTestId("agent-project-id")).toHaveValue(original.projectId);
    await expect(page.getByTestId("agent-goal-summary")).toHaveValue(original.summary);
    const resetUrl = new URL(page.url());
    expect(resetUrl.searchParams.get("server")).toBe(serverId);
    expect(resetUrl.searchParams.has("session")).toBe(false);

    const revisedSummary = `${original.summary} with revised evidence target`;
    const replacement = await submitComposerAndWaitForPlan(page, {
      filename: `agent-e2e-${suffix}-replacement.fastq`,
      projectId: original.projectId,
      successCriterion: "生成新的独立 QC lineage，并保留旧会话审计事实。",
      summary: revisedSummary,
    });
    expect(replacement.sessionId).not.toBe(original.sessionId);
    expect(replacement.planHash).toMatch(/^[0-9a-f]{64}$/);
    await expectWorkbenchIdentity(page, serverId, replacement.sessionId);
    await expect(page.getByTestId("agent-approval-panel")).toHaveAttribute(
      "data-session-status",
      "awaiting_approval"
    );
    await expect(page.getByTestId("agent-plan-card")).toHaveAttribute("data-plan-valid", "true");
    expect(mutations.filter((mutation) => /\/replan$/.test(mutation.path))).toHaveLength(0);
    assertNoRunMutation(mutations);
    assertBrowserNeverClaimsActor(mutations);

    const persistedOriginal = await fetchAgentSnapshot(api, serverId, original.sessionId);
    const persistedReplacement = await fetchAgentSnapshot(api, serverId, replacement.sessionId);
    expect(persistedOriginal.session.status).toBe("changes_requested");
    expect(persistedReplacement.session.status).toBe("awaiting_approval");
    expect(persistedReplacement.session.goal.summary).toBe(revisedSummary);
    expect(persistedReplacement.plans).toHaveLength(1);
  });
});

async function createPlanThroughUi(
  page: Page,
  input: {
    filename: string;
    projectId: string;
    serverId: string;
    successCriterion: string;
    summary: string;
  }
): Promise<CreatedPlan> {
  await page.goto(`/workflows?server=${encodeURIComponent(input.serverId)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Agent 工作台" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("agent-server-identity")).toBeVisible();
  await expect(page.getByTestId("agent-goal-composer")).toBeVisible();
  return submitComposerAndWaitForPlan(page, input);
}

async function submitComposerAndWaitForPlan(
  page: Page,
  input: {
    filename: string;
    projectId: string;
    successCriterion: string;
    summary: string;
  }
): Promise<CreatedPlan> {
  await page.getByTestId("agent-project-id").fill(input.projectId);
  await page.getByTestId("agent-goal-summary").fill(input.summary);
  await page.getByTestId("agent-success-criterion").fill(input.successCriterion);
  await page.getByTestId("agent-fastq-file").setInputFiles({
    name: input.filename,
    mimeType: "text/plain",
    buffer: Buffer.from(FASTQ_CONTENT, "utf8"),
  });
  await expect(page.getByTestId("agent-fastq-file-summary")).toContainText(input.filename);

  const createResponsePromise = page.waitForResponse((response) =>
    apiResponseMatches(response, "POST", /^\/api\/v1\/agent-sessions$/)
  );
  const planResponsePromise = page.waitForResponse(
    (response) => apiResponseMatches(response, "POST", /^\/api\/v1\/agent-sessions\/[^/]+\/plan$/),
    { timeout: REMOTE_COMMAND_TIMEOUT_MS }
  );
  await expect(page.getByTestId("agent-create-and-plan")).toBeEnabled();
  await page.getByTestId("agent-create-and-plan").click();

  const created = await responseData(await createResponsePromise);
  const sessionId = String(created.sessionId || "");
  expect(sessionId).toMatch(/^ags_/);
  expect(created.projectId).toBe(input.projectId);
  const planned = await responseData(await planResponsePromise);
  expect(planned.session?.sessionId).toBe(sessionId);
  expect(planned.session?.status).toBe("awaiting_approval");
  expect(planned.validation?.valid).toBe(true);
  expect(planned.validation?.orderedSteps?.map((step: any) => step.toolRevisionId)).toEqual(
    fastqQcRevisions
  );
  const planHash = String(planned.plan?.planHash || "");
  const planRevisionId = String(planned.plan?.planRevisionId || "");
  expect(planHash).toMatch(/^[0-9a-f]{64}$/);
  expect(planRevisionId).toMatch(/^agpr_/);
  await expect(page.getByTestId("agent-plan-card")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByTestId("agent-approval-panel")).toHaveAttribute(
    "data-session-status",
    "awaiting_approval"
  );
  return {
    planHash,
    planRevisionId,
    projectId: input.projectId,
    sessionId,
    summary: input.summary,
  };
}

async function assertReadOnlyExecutionGraph(page: Page): Promise<void> {
  const graph = page.getByTestId("agent-execution-graph");
  await expect(graph).toHaveAttribute("data-read-only", "true");
  await graph.locator("summary").click();
  await expect(graph).toContainText("不支持拖拽、连线或参数编辑");
  await expect(graph.getByTestId("agent-execution-graph-node")).toHaveCount(2);
  await expect(graph.getByTestId("agent-execution-graph-edge")).toHaveCount(1);
  expect(
    await graph
      .locator("button, input, textarea, select, [draggable='true'], [contenteditable]:not([contenteditable='false'])")
      .count()
  ).toBe(0);
}

async function assertDurableTimeline(page: Page, expectedEventTypes: string[]): Promise<void> {
  const timeline = page.getByTestId("agent-event-timeline");
  await expect(timeline).toBeVisible({ timeout: 45_000 });
  const rows = timeline.getByTestId("agent-event-row");
  await expect.poll(async () => rows.count()).toBeGreaterThanOrEqual(expectedEventTypes.length);
  for (const eventType of expectedEventTypes) {
    await expect(
      timeline.locator(`[data-testid="agent-event-row"][data-event-type="${eventType}"]`)
    ).toHaveCount(1);
  }
}

async function expectWorkbenchIdentity(page: Page, expectedServerId: string, expectedSessionId: string): Promise<void> {
  await expect(page).toHaveURL((url) => {
    return url.pathname === "/workflows" &&
      url.searchParams.get("server") === expectedServerId &&
      url.searchParams.get("session") === expectedSessionId;
  });
  await expect(page.getByTestId("agent-session-summary")).toContainText(expectedSessionId);
}

async function fetchProductionReadyServerId(apiContext: APIRequestContext): Promise<string> {
  const response = await apiContext.get("/api/v1/servers?refresh=true");
  if (!response.ok()) {
    throw new Error(`P0_AGENT_READY_SERVER_REQUIRED: ${response.status()} ${await response.text()}`);
  }
  const body = await response.json();
  const servers = Array.isArray(body.data?.items) ? body.data.items : [];
  const readyServer = servers.find(
    (server: any) =>
      server?.connected === true &&
      server?.ready === true &&
      String(server?.serverId || "").trim()
  );
  const selectedServerId = String(readyServer?.serverId || "").trim();
  if (selectedServerId) return selectedServerId;
  throw new Error(
    "P0_AGENT_READY_SERVER_REQUIRED: no server satisfies the production readiness gate " +
      `connected===true && ready===true. Observed: ${JSON.stringify(
        servers.map((server: any) => ({
          connected: server?.connected,
          ready: server?.ready,
          serverId: server?.serverId,
        }))
      )}`
  );
}

async function requireFastqQcCapabilities(
  apiContext: APIRequestContext,
  expectedServerId: string
): Promise<[string, string]> {
  const query = new URLSearchParams({
    q: "",
    page: "1",
    pageSize: "100",
    targetPlatform: "linux-64",
    agentSelectableOnly: "true",
    serverId: expectedServerId,
  });
  const response = await apiContext.get(
    `/api/v1/tool-capabilities/capability-graph?${query.toString()}`
  );
  if (!response.ok()) {
    throw new Error(
      `P0_AGENT_FASTQ_QC_CAPABILITY_GRAPH_REQUIRED[server=${expectedServerId}]: ` +
        `${response.status()} ${await response.text()}`
    );
  }
  const body = await response.json();
  if (body.data?.contractVersion !== "capability-graph-snapshot-v1") {
    throw new Error(
      `P0_AGENT_FASTQ_QC_CAPABILITY_GRAPH_CONTRACT_INVALID[server=${expectedServerId}]: ` +
        String(body.data?.contractVersion || "missing")
    );
  }
  if (body.data?.targetPlatform !== "linux-64") {
    throw new Error(
      `P0_AGENT_FASTQ_QC_CAPABILITY_GRAPH_PLATFORM_INVALID[server=${expectedServerId}]: ` +
        String(body.data?.targetPlatform || "missing")
    );
  }
  if (body.data?.serverId !== expectedServerId) {
    throw new Error(
      `P0_AGENT_FASTQ_QC_CAPABILITY_GRAPH_SERVER_MISMATCH: expected=${expectedServerId} ` +
        `actual=${String(body.data?.serverId || "missing")}`
    );
  }
  const bundles = Array.isArray(body.data?.capabilityBundles) ? body.data.capabilityBundles : [];
  const selected = FASTQ_QC_CAPABILITY_REQUIREMENTS.map((requirement) => {
    const { profileId, version } = requirement;
    const matches = bundles.filter(
      (bundle: any) =>
        String(bundle?.profileId || "") === profileId &&
        String(bundle?.version || "") === version
    );
    if (matches.length !== 1) {
      throw new Error(
        `P0_AGENT_FASTQ_QC_CAPABILITIES_REQUIRED[server=${expectedServerId}]: expected exactly one ` +
          `bundle for ${profileId}=${version}, found ${matches.length}. Prepare and validate the built-in ` +
          "FastQC/MultiQC profiles through /workflows/tools."
      );
    }
    assertFastqQcCapabilityBundle(matches[0], requirement, expectedServerId);
    return String(matches[0].toolRevisionId);
  });
  return [selected[0], selected[1]];
}

function assertFastqQcCapabilityBundle(
  bundle: any,
  requirement: (typeof FASTQ_QC_CAPABILITY_REQUIREMENTS)[number],
  expectedServerId: string
): void {
  const label = `${requirement.profileId}=${requirement.version}[server=${expectedServerId}]`;
  expect(bundle?.capabilityBundleVersion, `${label} bundle contract`).toBe("capability-bundle-v1");
  expect(bundle?.agentSelectable, `${label} agent selection gate`).toBe(true);
  expect(String(bundle?.toolRevisionId || ""), `${label} immutable tool revision`).toMatch(
    requirement.revisionPattern
  );
  assertCapabilityPortSignatures(bundle, requirement.profileId, label);
  assertCapabilityValidationEvidence(bundle?.validationEvidence, requirement.profileId, label);
}

function assertCapabilityPortSignatures(bundle: any, profileId: "fastqc" | "multiqc", label: string): void {
  const expected = expectedCapabilityPortSignatures(profileId);
  expect(normalizeCapabilityPorts(bundle?.inputs), `${label} input port signature`).toEqual(expected.inputs);
  expect(normalizeCapabilityPorts(bundle?.outputs), `${label} output port signature`).toEqual(expected.outputs);
}

function assertCapabilityValidationEvidence(
  evidence: any,
  profileId: "fastqc" | "multiqc",
  label: string
): void {
  expect(evidence?.status, `${label} validation status`).toBe("passed");
  expect(String(evidence?.validationResultId || ""), `${label} validationResultId`).not.toBe("");
  expect(String(evidence?.evidenceId || ""), `${label} evidenceId`).not.toBe("");
  expect(String(evidence?.checkedAt || ""), `${label} checkedAt`).not.toBe("");
  expect(
    Array.isArray(evidence?.stages)
      ? evidence.stages.map((stage: any) => ({ id: stage?.id, status: stage?.status }))
      : [],
    `${label} validation stages`
  ).toEqual([
    { id: "dryRun", status: "passed" },
    { id: "smokeRun", status: "passed" },
    { id: "outputValidation", status: "passed" },
  ]);
  const fixtureInputs = Array.isArray(evidence?.fixture?.inputs) ? evidence.fixture.inputs : [];
  const expectedArtifacts = Array.isArray(evidence?.fixture?.expectedArtifacts)
    ? evidence.fixture.expectedArtifacts
    : [];
  expect(fixtureInputs.map((item: any) => item?.name), `${label} smoke fixture inputs`).toEqual(
    profileId === "fastqc" ? ["reads"] : ["fastqc_data"]
  );
  expect(expectedArtifacts.map((item: any) => item?.name), `${label} expected artifacts`).toEqual(
    profileId === "fastqc" ? ["html", "zip"] : ["report"]
  );
  for (const item of fixtureInputs) {
    expect(String(item?.filename || ""), `${label} fixture filename`).not.toBe("");
    expect(String(item?.mimeType || ""), `${label} fixture MIME type`).not.toBe("");
  }
  for (const item of expectedArtifacts) {
    expect(String(item?.path || ""), `${label} expected artifact path`).not.toBe("");
    expect(String(item?.mimeType || ""), `${label} expected artifact MIME type`).not.toBe("");
  }
}

function normalizeCapabilityPorts(value: unknown): CapabilityPort[] {
  if (!Array.isArray(value)) return [];
  return value.map((item: any) => {
    const port: CapabilityPort = {
      data: String(item?.data || ""),
      format: String(item?.format || ""),
      kind: String(item?.kind || ""),
      mimeType: String(item?.mimeType || ""),
      name: String(item?.name || ""),
      operation: String(item?.operation || ""),
      required: item?.required === true,
      resource: String(item?.resource || ""),
      type: String(item?.type || ""),
    };
    if (String(item?.path || "")) port.path = String(item.path);
    return port;
  });
}

function expectedCapabilityPortSignatures(profileId: "fastqc" | "multiqc"): {
  inputs: CapabilityPort[];
  outputs: CapabilityPort[];
} {
  if (profileId === "fastqc") {
    return {
      inputs: [capabilityPort("reads", "sequence_reads", "text/plain", EDAM_SEQUENCE, EDAM_FASTQ, true)],
      outputs: [
        capabilityPort("html", "report", "text/html", EDAM_GENERIC_DATA, EDAM_HTML, false, "results/reads_fastqc.html"),
        capabilityPort(
          "zip",
          "qc_report",
          "application/zip",
          EDAM_QUALITY_CONTROL_REPORT,
          EDAM_ZIP,
          false,
          "results/reads_fastqc.zip"
        ),
      ],
    };
  }
  return {
    inputs: [
      capabilityPort(
        "fastqc_data",
        "qc_report",
        "application/zip",
        EDAM_QUALITY_CONTROL_REPORT,
        EDAM_ZIP,
        true
      ),
    ],
    outputs: [
      capabilityPort("report", "report", "text/html", EDAM_GENERIC_DATA, EDAM_HTML, false, "results/multiqc.html"),
    ],
  };
}

function capabilityPort(
  name: string,
  kind: string,
  mimeType: string,
  data: string,
  format: string,
  required: boolean,
  path?: string
): CapabilityPort {
  return {
    data,
    format,
    kind,
    mimeType,
    name,
    operation: "",
    ...(path ? { path } : {}),
    required,
    resource: "",
    type: "file",
  };
}

async function fetchAgentSnapshot(apiContext: APIRequestContext, expectedServerId: string, sessionId: string) {
  const query = `serverId=${encodeURIComponent(expectedServerId)}&refresh=true`;
  const snapshot = await fetchEnvelopeData(
    apiContext,
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}/snapshot?${query}`
  );
  expect(snapshot).toMatchObject({
    contractVersion: "agent-session-snapshot.v1",
    session: { sessionId },
  });
  return snapshot;
}

async function fetchEnvelopeData(apiContext: APIRequestContext, path: string): Promise<any> {
  const response = await apiContext.get(path);
  if (!response.ok()) throw new Error(`Agent E2E read failed: ${response.status()} ${await response.text()}`);
  return (await response.json()).data;
}

function observeBrowserMutations(page: Page): BrowserMutation[] {
  const mutations: BrowserMutation[] = [];
  page.on("request", (request: Request) => {
    const method = request.method().toUpperCase();
    if (method === "GET" || method === "HEAD" || method === "OPTIONS") return;
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
    mutations.push({ method, path: url.pathname, postData: request.postData() });
  });
  return mutations;
}

function assertNoRunMutation(mutations: BrowserMutation[]): void {
  expect(
    mutations.filter((mutation) =>
      mutation.path === "/api/v1/runs" || mutation.path.startsWith("/api/v1/runs/")
    )
  ).toEqual([]);
}

function assertHashBoundApprovalMutation(
  mutations: BrowserMutation[],
  sessionId: string,
  planHash: string,
  decision = "approve"
): void {
  const mutation = mutations.find(
    (candidate) =>
      candidate.method === "POST" &&
      candidate.path === `/api/v1/agent-sessions/${sessionId}/approval` &&
      parsePostData(candidate.postData)?.decision === decision
  );
  expect(mutation, `missing ${decision} browser mutation for ${sessionId}`).toBeTruthy();
  const body = parsePostData(mutation?.postData);
  expect(body?.expectedPlanHash).toBe(planHash);
  expect(body?.serverId).toBe(serverId);
  expect(body?.expectedStateVersion).toEqual(expect.any(Number));
  expect(body?.requestId).toBe(body?.idempotencyKey);
}

function assertBrowserNeverClaimsActor(mutations: BrowserMutation[]): void {
  const agentMutations = mutations.filter((mutation) => mutation.path.includes("/api/v1/agent-sessions"));
  for (const mutation of agentMutations) {
    const body = parsePostData(mutation.postData);
    expect(body).not.toHaveProperty("actor");
    expect(body).not.toHaveProperty("createdBy");
    expect(body).not.toHaveProperty("proposal");
    expect(body).not.toHaveProperty("nodes");
    expect(body).not.toHaveProperty("edges");
  }
}

function assertEventHashChain(events: any[]): void {
  const ordered = [...events].sort((left, right) => Number(left.sequence) - Number(right.sequence));
  expect(ordered.length).toBeGreaterThanOrEqual(5);
  for (let index = 0; index < ordered.length; index += 1) {
    expect(ordered[index].sequence).toBe(index + 1);
    expect(ordered[index].eventHash).toMatch(/^[0-9a-f]{64}$/);
    expect(ordered[index].payloadHash).toMatch(/^[0-9a-f]{64}$/);
    expect(ordered[index].prevEventHash || null).toBe(index === 0 ? null : ordered[index - 1].eventHash);
  }
}

function apiResponseMatches(response: Response, method: string, path: RegExp): boolean {
  const request = response.request();
  return request.method().toUpperCase() === method && path.test(new URL(response.url()).pathname);
}

async function responseData(response: Response): Promise<any> {
  const body = await response.json();
  if (!response.ok()) throw new Error(`Agent UI command failed: ${response.status()} ${JSON.stringify(body)}`);
  return body.data;
}

function parsePostData(raw: string | null | undefined): Record<string, any> | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function uniqueSuffix(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
