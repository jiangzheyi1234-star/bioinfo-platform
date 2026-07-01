import { expect, test, type Page, type Route } from "@playwright/test";

const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1";
const SERVER_ID = "srv_first_run_e2e";
const RUN_ID = "run_first_run_e2e";
const RESULT_ID = `res_${RUN_ID}`;
const WORKFLOW_REVISION_ID = "wfrev_first_run_e2e";
const PACKAGE_EXPORT_ID = "pkg_first_run_e2e";
const HASH = "a".repeat(64);
const MANIFEST_HASH = "b".repeat(64);

type FirstRunMockMode = "ready-to-submit" | "package-required" | "completed";

test.describe("First Successful Run onboarding", () => {
  test("submits the Moving Pictures first-run through the first-run contract", async ({ page }) => {
    const api = await installFirstRunApiMocks(page, "ready-to-submit");

    await page.goto("/workflows/first-run");

    await expect(page.getByTestId("first-successful-run-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "SUBMIT_RUN");
    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-target", "#sample-data");
    await expect(page.getByTestId("first-run-sample-selection")).toHaveAttribute("data-selection-state", "selected");
    await expect(page.getByTestId("first-run-sample-data-status")).toHaveAttribute("data-sample-data-status", "ready");
    await expect(page.getByTestId("first-run-submit-run")).toBeEnabled();

    const [response, request] = await Promise.all([
      page.waitForResponse((item) => new URL(item.url()).pathname === "/api/v1/first-run/runs" && item.request().method() === "POST"),
      page.waitForRequest((item) => new URL(item.url()).pathname === "/api/v1/first-run/runs" && item.method() === "POST"),
      page.getByTestId("first-run-continue").click(),
    ]);
    expect(response.ok()).toBe(true);
    const payload = request.postDataJSON();
    expect(payload).toMatchObject({
      actor: "first-run-ui",
      confirmation: "submit-first-run",
      serverId: SERVER_ID,
    });
    expect(String(payload.idempotencyKey || "")).toMatch(/^idem_first_run_/);
    expect(api.firstRunSubmitted).toBe(true);
    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "REFRESH_RUN");
    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "COMPLETE", {
      timeout: 12_000,
    });
    await expect(page.getByTestId("first-run-completion-panel")).toBeVisible();
    expect(api.firstRunStatusPollsAfterSubmit).toBeGreaterThanOrEqual(3);
  });

  test("renders the completed result package, validation card, and evidence bundle", async ({ page }) => {
    await installFirstRunApiMocks(page, "completed");

    await page.goto("/workflows/first-run");

    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "COMPLETE");
    await expect(page.getByTestId("first-run-completion-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("first-run-pilot-handoff")).toBeVisible();
    await expect(page.getByTestId("first-run-evidence-bundle")).toBeVisible();
    await expect(page.getByTestId("first-run-evidence-bundle-file")).toHaveCount(4);
    await expect(page.getByTestId("first-run-completion-download-result-package")).toBeVisible();
    await expect(page.getByTestId("first-run-completion-download-validation-card-json")).toBeVisible();
    await expect(page.getByTestId("first-run-completion-download-validation-card-markdown")).toBeVisible();
    await expect(page.getByTestId("first-run-completion-download-pilot-handoff")).toBeVisible();
    await expect(page.getByTestId("first-run-completion-key-results")).toContainText("summary.tsv");
    await expect(page.getByTestId("first-run-pilot-handoff")).toContainText(PACKAGE_EXPORT_ID);
    await expect(page.getByTestId("first-run-evidence-bundle")).toContainText(PACKAGE_EXPORT_ID);
  });

  test("marks report ready while guiding result package export", async ({ page }) => {
    const api = await installFirstRunApiMocks(page, "package-required");

    await page.goto("/workflows/first-run");

    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "FINALIZE_FIRST_RUN");
    await expect(page.locator('[data-first-run-step="report"]')).toHaveAttribute("data-step-state", "done");
    await expect(page.locator('[data-first-run-step="package"]')).toHaveAttribute("data-step-state", "blocked");
    await expect(page.getByTestId("first-run-report-insight")).toContainText("关键结果完整");
    await expect(page.getByTestId("first-run-report-insight")).toContainText("passed reads");
    await expect(page.getByTestId("first-run-completion-panel")).not.toBeVisible();

    const [response, request] = await Promise.all([
      page.waitForResponse((item) => new URL(item.url()).pathname === `/api/v1/first-run/runs/${RUN_ID}/finalize` && item.request().method() === "POST"),
      page.waitForRequest((item) => new URL(item.url()).pathname === `/api/v1/first-run/runs/${RUN_ID}/finalize` && item.method() === "POST"),
      page.getByTestId("first-run-continue").click(),
    ]);
    expect(response.ok()).toBe(true);
    expect(request.postDataJSON()).toMatchObject({
      actor: "first-run-ui",
      serverId: SERVER_ID,
    });
    expect(api.firstRunFinalized).toBe(true);
    await expect(page.getByTestId("first-run-conductor")).toHaveAttribute("data-first-run-next-action", "COMPLETE");
    await expect(page.getByTestId("first-run-completion-panel")).toBeVisible();
    await expect(page.getByTestId("first-run-evidence-bundle-file")).toHaveCount(4);
  });
});

async function installFirstRunApiMocks(page: Page, mode: FirstRunMockMode) {
  const api = {
    firstRunStatus:
      mode === "completed"
        ? completedFirstRunStatus()
        : mode === "package-required"
          ? packageRequiredFirstRunStatus()
          : readyToSubmitFirstRunStatus(),
    firstRunFinalized: false,
    firstRunStatusPollsAfterSubmit: 0,
    firstRunSubmitted: false,
  };

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (method === "GET" && path === "/api/v1/ssh/status") {
      return json(route, { item: sshStatus() });
    }
    if (method === "GET" && path === "/api/v1/workflow-catalog") {
      return data(route, { items: [movingPicturesWorkflow()] });
    }
    if (method === "GET" && path === "/api/v1/tool-capabilities/capability-graph") {
      return data(route, { agentSelectableTools: [], targetAcceptance: { validationQueue: { items: [] } } });
    }
    if (method === "GET" && path === "/api/v1/databases") {
      return data(route, { items: [] });
    }
    if (method === "GET" && path === "/api/v1/servers") {
      return data(route, { items: [workflowServer()] });
    }
    if (method === "GET" && path === `/api/v1/servers/${SERVER_ID}/execution-diagnostics`) {
      return data(route, executionDiagnostics());
    }
    if (method === "GET" && path === "/api/v1/workflow-design-drafts") {
      return data(route, { items: [] });
    }
    if (method === "GET" && path === "/api/v1/runs") {
      return data(route, { items: mode === "completed" || api.firstRunSubmitted ? [workflowRun()] : [] });
    }
    if (method === "GET" && path === "/api/v1/first-run/status") {
      const requestedServerId = url.searchParams.get("serverId") || "";
      if (requestedServerId && requestedServerId !== SERVER_ID) {
        return data(route, missingServerFirstRunStatus());
      }
      if (mode === "ready-to-submit" && api.firstRunSubmitted) {
        api.firstRunStatusPollsAfterSubmit += 1;
        if (api.firstRunStatusPollsAfterSubmit >= 3) {
          api.firstRunStatus = completedFirstRunStatus();
        }
      }
      return data(route, api.firstRunStatus);
    }
    if (method === "GET" && path === `/api/v1/workflow-sample-data/${FIRST_RUN_PIPELINE_ID}/status`) {
      return data(route, sampleDataStatus());
    }
    if (method === "POST" && path === "/api/v1/first-run/runs") {
      api.firstRunSubmitted = true;
      api.firstRunStatus = submittedFirstRunStatus();
      return data(route, firstRunSubmission());
    }
    if (method === "POST" && path === `/api/v1/first-run/runs/${RUN_ID}/finalize`) {
      api.firstRunFinalized = true;
      api.firstRunStatus = completedFirstRunStatus();
      return data(route, firstRunFinalization());
    }
    if (method === "GET" && path === `/api/v1/runs/${RUN_ID}/detail`) {
      return data(route, runDetail());
    }
    if (method === "GET" && path === `/api/v1/results/${RESULT_ID}/exports`) {
      return data(route, { items: [resultPackageExport()] });
    }
    if (method === "GET" && path === `/api/v1/first-run/runs/${RUN_ID}/validation-card`) {
      return data(route, validationCard());
    }
    if (method === "GET" && path === "/api/v1/workflow-scenario-packs") {
      return data(route, { items: [] });
    }
    return json(route, { detail: `Unhandled first-run E2E mock route: ${method} ${path}` }, 404);
  });

  return api;
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function data(route: Route, value: unknown, status = 200) {
  return json(route, { data: value }, status);
}

function sshStatus() {
  return {
    configured: true,
    connected: true,
    displayTarget: "First-run E2E runner",
    host: "first-run-e2e.local",
    port: 22,
    runner: { ready: true, state: "ready", message: "runner ready" },
    serverId: SERVER_ID,
    user: "codex",
  };
}

function workflowServer() {
  return {
    connected: true,
    health: {
      pipelineRegistry: { count: 1, ok: true },
      workflowRuntime: {
        snakemakeVersion: "8.30.0",
        workflowProfileMessage: "profile ready",
        workflowProfileOk: true,
        workflowProfilePath: "~/.h2ometa/runner/shared/profile",
      },
    },
    label: "First-run E2E runner",
    message: "ready",
    ready: true,
    runner: {
      bootstrapMetadata: {
        canary: { ok: true, status: "passed" },
        workflow_profile: { written: true },
      },
      message: "runner ready",
      ready: true,
      state: "ready",
    },
    serverId: SERVER_ID,
  };
}

function movingPicturesWorkflow() {
  return {
    id: FIRST_RUN_PIPELINE_ID,
    description: "Official Moving Pictures 16S first-run scenario.",
    name: "Moving Pictures 16S",
    runnable: true,
    source: "builtin",
    status: "WorkflowReady",
    version: "1.0.0",
  };
}

function executionDiagnostics() {
  return {
    schemaVersion: "execution-diagnostics.v1",
    readiness: {
      ok: true,
      status: "ready",
      blockingReasons: [],
    },
  };
}

function sampleDataStatus() {
  return {
    pipelineId: FIRST_RUN_PIPELINE_ID,
    source: "official Moving Pictures sample",
    status: "ready",
    itemCount: 3,
    verifiedCacheCount: 3,
    missingCacheCount: 0,
    items: ["metadata", "barcodes", "sequences"].map((role) => ({
      role,
      filename: sampleFilename(role),
      cacheStatus: "verified",
      status: "ready",
      expectedSha256: HASH,
      sha256: HASH,
    })),
  };
}

function readyToSubmitFirstRunStatus() {
  return {
    schemaVersion: "h2ometa.first-run.status.v1",
    scenario: {
      expectedSampleRoles: ["metadata", "barcodes", "sequences"],
      pipelineId: FIRST_RUN_PIPELINE_ID,
      pipelineName: "Moving Pictures 16S",
    },
    serverId: SERVER_ID,
    status: "blocked",
    stage: "submit_run",
    nextAction: {
      code: "SUBMIT_RUN",
      detail: "提交 Moving Pictures 16S 首跑。",
      label: "提交运行",
      target: "#sample-data",
    },
    latestEligibleRun: null,
    evidence: {
      server: { connected: true, ready: true, runnerReady: true, serverId: SERVER_ID },
      execution: { ready: true, status: "ready", blockingReasons: [] },
      workflow: { ready: true, pipelineId: FIRST_RUN_PIPELINE_ID, name: "Moving Pictures 16S", status: "WorkflowReady" },
      sampleCache: { status: "ready", verifiedCacheCount: 3, itemCount: 3, missingCacheCount: 0 },
    },
  };
}

function submittedFirstRunStatus() {
  return {
    ...readyToSubmitFirstRunStatus(),
    status: "waiting",
    stage: "run_in_progress",
    nextAction: {
      code: "REFRESH_RUN",
      detail: "等待服务端首跑状态聚合返回 run、报告、结果包和验证卡状态。",
      label: "刷新首跑状态",
      target: "#run-report",
    },
    latestEligibleRun: workflowRun(),
    evidence: {
      ...readyToSubmitFirstRunStatus().evidence,
      run: workflowRun(),
    },
  };
}

function completedFirstRunStatus() {
  return {
    ...readyToSubmitFirstRunStatus(),
    status: "ready",
    stage: "validation_ready",
    nextAction: {
      code: "COMPLETE",
      detail: "结果包、验证卡和 pilot handoff 已准备好。",
      label: "首跑已完成",
      target: "#evidence-bundle",
    },
    latestEligibleRun: workflowRun(),
    evidence: {
      ...readyToSubmitFirstRunStatus().evidence,
      run: workflowRun(),
      report: {
        ready: true,
        outputs: ["summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"],
      },
      resultPackage: {
        artifactPayloadMode: "full",
        includeArtifacts: true,
        manifestSha256: MANIFEST_HASH,
        packageExportId: PACKAGE_EXPORT_ID,
        ready: true,
        sha256: HASH,
      },
      validation: {
        evidenceBundleId: "bundle_first_run_e2e",
        evidenceBundleReady: true,
        ready: true,
        validationChecksPassed: 6,
        validationChecksTotal: 6,
      },
    },
  };
}

function packageRequiredFirstRunStatus() {
  return {
    ...readyToSubmitFirstRunStatus(),
    status: "blocked",
    stage: "export_result_package",
    nextAction: {
      blockedCode: "FIRST_RUN_RESULT_PACKAGE_REQUIRED",
      code: "FINALIZE_FIRST_RUN",
      detail: "报告已通过服务端可信检查，下一步导出完整结果包。",
      label: "导出完整结果包",
      target: "#result-package",
    },
    latestEligibleRun: workflowRun(),
    evidence: {
      ...readyToSubmitFirstRunStatus().evidence,
      run: workflowRun(),
      report: reportEvidence(),
      resultPackage: {
        ready: false,
        blockedCode: "FIRST_RUN_RESULT_PACKAGE_REQUIRED",
      },
      validation: {
        ready: false,
        blockedCode: "FIRST_RUN_RESULT_PACKAGE_REQUIRED",
      },
    },
  };
}

function reportEvidence() {
  return {
    ready: true,
    outputs: ["summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"],
    metrics: [
      { metricId: "sample_count", label: "samples", value: 2, displayValue: "2", source: "summary.tsv" },
      { metricId: "passed_reads_total", label: "passed reads", value: 30, displayValue: "30", source: "summary.tsv" },
      { metricId: "unique_features_sample_sum", label: "unique features", value: 7, displayValue: "7", source: "summary.tsv" },
    ],
  };
}

function firstRunSubmission() {
  return {
    schemaVersion: "h2ometa.first-run.submit.v1",
    status: "submitted",
    serverId: SERVER_ID,
    actor: "first-run-ui",
    submittedRun: workflowRun(),
    sampleData: {
      schemaVersion: "h2ometa.first-run.sample-data.v1",
      status: "ready",
      items: sampleUploads(),
    },
    runSpec: {
      projectId: "first-run-pilot",
      pipelineId: FIRST_RUN_PIPELINE_ID,
      inputs: sampleUploads().map((item) => ({
        filename: item.filename,
        role: item.role,
        uploadId: item.uploadId,
      })),
      sampleDataPrepProof: {
        schemaVersion: "h2ometa.workflow-sample-data-prep-proof.v1",
        items: sampleUploads().map((item) => item.prepProof),
      },
    },
    nextAction: {
      code: "REFRESH_RUN",
      detail: "首跑已提交，等待 runner 返回运行状态、报告和结果包证据。",
      label: "查看运行状态",
      target: "/workflows/first-run#run-report",
    },
  };
}

function firstRunFinalization() {
  const card = validationCard();
  return {
    schemaVersion: "h2ometa.first-run.finalization.v1",
    status: "ready",
    packageAction: "exported",
    evidenceBundle: pilotHandoff().evidenceBundle,
    pilotHandoff: pilotHandoff(),
    resultPackage: card.resultPackage,
    validationCard: card,
  };
}

function workflowRun() {
  return {
    runId: RUN_ID,
    resultId: RESULT_ID,
    runSpec: {
      pipelineId: FIRST_RUN_PIPELINE_ID,
      workflowRevisionId: WORKFLOW_REVISION_ID,
    },
    stage: "completed",
    status: "completed",
    workflowRevisionId: WORKFLOW_REVISION_ID,
  };
}

function runDetail() {
  return {
    run: workflowRun(),
    artifacts: [],
    inputArtifacts: [],
    logs: {
      stderr: { lines: [] },
      stdout: { lines: [] },
    },
    previews: [],
    results: {
      resultId: RESULT_ID,
      artifacts: [],
      inputArtifacts: [],
    },
    rules: {
      items: [],
      summary: {
        failedRuleCount: 0,
        ruleCount: 0,
        rulesWithAvailableLogEvidence: 0,
        rulesWithLogReferences: 0,
        runningRuleCount: 0,
      },
    },
  };
}

function resultPackageExport() {
  return {
    artifactPayloadMode: "full",
    download: {
      filename: "first-run-result-package.zip",
      href: `/api/v1/results/${RESULT_ID}/exports/${PACKAGE_EXPORT_ID}/download`,
    },
    evidenceId: "ev_first_run_e2e",
    includeArtifacts: true,
    lifecycleState: "active",
    manifestSha256: MANIFEST_HASH,
    packageBytesState: "available",
    packageExportId: PACKAGE_EXPORT_ID,
    resultId: RESULT_ID,
    sha256: HASH,
    sizeBytes: 4096,
    workflowRevisionId: WORKFLOW_REVISION_ID,
  };
}

function missingServerFirstRunStatus() {
  return {
    schemaVersion: "h2ometa.first-run.status.v1",
    scenario: {
      expectedSampleRoles: ["metadata", "barcodes", "sequences"],
      pipelineId: FIRST_RUN_PIPELINE_ID,
      pipelineName: "Moving Pictures 16S",
    },
    serverId: "",
    status: "blocked",
    stage: "connect_remote",
    nextAction: {
      blockedCode: "FIRST_RUN_SERVER_REQUIRED",
      code: "CONNECT_REMOTE",
      detail: "连接远端 runner 后继续首跑。",
      label: "连接远端",
      target: "#runner-readiness",
    },
    latestEligibleRun: null,
    evidence: {
      server: {
        blockedCode: "FIRST_RUN_SERVER_REQUIRED",
        connected: false,
        ready: false,
        serverId: "",
      },
      execution: { blockedCode: "FIRST_RUN_SERVER_REQUIRED", ready: false },
      workflow: { blockedCode: "FIRST_RUN_SERVER_REQUIRED", ready: false },
      sampleCache: { status: "ready", verifiedCacheCount: 3, itemCount: 3, missingCacheCount: 0 },
    },
  };
}

function validationCard() {
  return {
    schemaVersion: "h2ometa.first-run.validation-card.v1",
    checks: [
      { code: "sample-inputs", status: "passed", detail: "three expected roles" },
      { code: "result-package", status: "passed", detail: "manifest and payload checksums recorded" },
    ],
    generatedAt: "2026-07-01T00:00:00Z",
    keyResults: [
      {
        artifactId: "summary",
        displayName: "summary.tsv",
        kind: "report",
        sha256: HASH,
      },
    ],
    pilotHandoff: pilotHandoff(),
    reportInterpretation: {
      status: "ready",
      summary: "Moving Pictures 16S produced the expected report outputs.",
    },
    result: {
      artifactCount: 4,
      inputArtifactCount: 3,
      resultId: RESULT_ID,
    },
    resultPackage: {
      packageExportId: PACKAGE_EXPORT_ID,
      artifactPayloadMode: "full",
      includeArtifacts: true,
      sizeBytes: 4096,
      sha256: HASH,
      manifestSha256: MANIFEST_HASH,
      evidenceId: "ev_first_run_e2e",
    },
    run: {
      runId: RUN_ID,
      status: "completed",
      stage: "completed",
    },
    sampleData: {
      status: "ready",
      items: sampleUploads(),
    },
    scenario: {
      dataset: "Moving Pictures",
      pipelineId: FIRST_RUN_PIPELINE_ID,
      pipelineName: "Moving Pictures 16S",
    },
    workflowRevision: {
      contentHash: HASH,
      workflowRevisionId: WORKFLOW_REVISION_ID,
    },
  };
}

function pilotHandoff() {
  return {
    schemaVersion: "h2ometa.first-run.single-user-lab-pilot-handoff.v1",
    scope: "single-user-pilot",
    status: "ready",
    evidence: {
      runId: RUN_ID,
      resultId: RESULT_ID,
      workflowRevisionId: WORKFLOW_REVISION_ID,
      packageExportId: PACKAGE_EXPORT_ID,
      packageSha256: HASH,
      manifestSha256: MANIFEST_HASH,
      validationChecksPassed: 6,
      validationChecksTotal: 6,
    },
    evidenceBundle: {
      schemaVersion: "h2ometa.first-run.evidence-bundle.v1",
      status: "ready",
      bundleId: "bundle_first_run_e2e",
      requiredFiles: [
        {
          role: "result-package",
          filename: "first-run-result-package.zip",
          href: `/api/v1/results/${RESULT_ID}/exports/${PACKAGE_EXPORT_ID}/download`,
          packageExportId: PACKAGE_EXPORT_ID,
          sha256: HASH,
          manifestSha256: MANIFEST_HASH,
        },
        {
          role: "validation-card-json",
          filename: "first-run.validation-card.json",
          href: `/api/v1/first-run/runs/${RUN_ID}/validation-card.json?serverId=${SERVER_ID}`,
        },
        {
          role: "validation-card-markdown",
          filename: "first-run.validation-card.md",
          href: `/api/v1/first-run/runs/${RUN_ID}/validation-card.md?serverId=${SERVER_ID}`,
        },
        {
          role: "pilot-handoff",
          filename: "first-run.pilot-handoff.md",
          href: `/api/v1/first-run/runs/${RUN_ID}/pilot-handoff.md?serverId=${SERVER_ID}`,
        },
      ],
      integrity: {
        runId: RUN_ID,
        resultId: RESULT_ID,
        workflowRevisionId: WORKFLOW_REVISION_ID,
        packageExportId: PACKAGE_EXPORT_ID,
        packageSha256: HASH,
        manifestSha256: MANIFEST_HASH,
      },
      consumerChecklist: ["keep-result-package-validation-card-and-handoff-together"],
    },
    backupRestore: {
      mode: "operator-runbook",
      planCommand: "scripts\\single_user_pilot_backup_plan.ps1",
      restoreProofCommand: "scripts\\first_run_pilot_check.ps1 -RequireFinalizationReady",
    },
  };
}

function sampleUploads() {
  return ["metadata", "barcodes", "sequences"].map((role) => ({
    role,
    filename: sampleFilename(role),
    uploadId: `upl_${role}`,
    artifactBlobId: `blob_${role}`,
    sha256: HASH,
    expectedSha256: HASH,
    sizeBytes: 1024,
    expectedSizeBytes: 1024,
    integrityStatus: "passed",
    prepProof: {
      schemaVersion: "h2ometa.workflow-sample-data-prep-proof.v1",
      role,
      filename: sampleFilename(role),
      sha256: HASH,
      expectedSha256: HASH,
      cacheStatus: "verified",
      downloadStatus: "cached",
      downloadAttempts: 0,
    },
  }));
}

function sampleFilename(role: string) {
  if (role === "metadata") return "sample-metadata.tsv";
  if (role === "barcodes") return "barcodes.fastq.gz";
  return "sequences.fastq.gz";
}
