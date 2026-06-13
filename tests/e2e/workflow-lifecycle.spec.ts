import { test, expect, APIRequestContext } from "@playwright/test";
import {
  createApiClient,
  waitForApiReady,
  fetchWorkflowCatalog,
  fetchRunDetail,
  fetchRunEvents,
  fetchRunResults,
  fetchResultPreview,
  buildTestRunSpec,
} from "./api-helpers";

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await createApiClient();
  await waitForApiReady(api);
});

test.afterAll(async () => {
  await api?.dispose();
});

test.describe("Workflow Catalog and Navigation", () => {
  test("browse workflow catalog page", async ({ page }) => {
    await page.goto("/workflows");
    await expect(page.getByText("流程目录")).toBeVisible({ timeout: 10_000 });

    const catalog = await fetchWorkflowCatalog(api);
    if (catalog.length > 0) {
      await expect(page.getByRole("table")).toBeVisible();
      for (const item of catalog.slice(0, 3)) {
        await expect(page.getByText(item.name).first()).toBeVisible({ timeout: 5_000 });
      }
    }
  });

  test("navigate to workflow detail page", async ({ page }) => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflowId = catalog[0].id;
    await page.goto(`/workflows/detail?workflow=${encodeURIComponent(workflowId)}`);
    await expect(page).toHaveURL(/\/workflows\/detail/, { timeout: 10_000 });
  });

  test("navigate to databases page", async ({ page }) => {
    await page.goto("/workflows/databases");
    await expect(page).toHaveURL(/\/workflows\/databases/, { timeout: 10_000 });
  });

  test("navigate to tools page", async ({ page }) => {
    await page.goto("/workflows/tools");
    await expect(page).toHaveURL(/\/workflows\/tools/, { timeout: 10_000 });
  });
});

test.describe("Run Submission and Status", () => {
  test("submit run via API and verify in results page", async ({ page }) => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const runSpec = await buildTestRunSpec(api, workflow, "proj_e2e_lifecycle", "submit");

    const response = await api.post("/api/v1/runs", { data: runSpec });
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const runId = body.data?.runId;
    expect(runId).toBeTruthy();

    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(runId)).toBeVisible({ timeout: 15_000 });
  });

  test("view run detail page with events and logs", async ({ page }) => {
    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];
    test.skip(runs.length === 0, "No runs exist");

    const runId = runs[0].runId;
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(runId)}`);
    await expect(page.getByText(runId)).toBeVisible({ timeout: 10_000 });

    const events = await fetchRunEvents(api, runId);
    if (events.length > 0) {
      await expect(page.getByText(events.at(-1).message).first()).toBeVisible({ timeout: 10_000 });
    }
  });

  test("switch between run detail tabs", async ({ page }) => {
    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];
    test.skip(runs.length === 0, "No runs exist");

    const runId = runs[0].runId;
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(runId)}`);
    await expect(page.getByText(runId)).toBeVisible({ timeout: 10_000 });

    const tabs = ["概览", "产物", "stdout", "stderr"];
    for (const tab of tabs) {
      const tabButton = page.getByRole("button", { name: tab });
      if (await tabButton.isVisible()) {
        await tabButton.click();
        await page.waitForTimeout(300);
      }
    }
  });

  test("filter runs by status", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });

    const filters = ["全部", "运行中", "已完成", "失败"];
    for (const filter of filters) {
      await page.getByRole("button", { name: filter, exact: true }).click();
      await page.waitForTimeout(500);
    }
  });

  test("refresh runs list", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Artifact Preview and Lineage", () => {
  test("view artifact preview for completed run", async ({ page }) => {
    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];
    const completedRun = runs.find((r: any) => r.status === "completed");
    test.skip(!completedRun, "No completed runs");

    const results = await fetchRunResults(api, completedRun.runId);
    test.skip(results.length === 0, "No results for completed run");
    const preview = await fetchResultPreview(
      api,
      completedRun.runId,
      results[0].artifactId
    );
    expect(preview.artifact?.artifactId).toBe(results[0].artifactId);
    expect(preview.preview?.kind).toBeTruthy();

    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(completedRun.runId)}`);
    await expect(page.getByText(completedRun.runId)).toBeVisible({ timeout: 10_000 });

    const artifactsTab = page.getByRole("button", { name: "产物" });
    if (await artifactsTab.isVisible()) {
      await artifactsTab.click();
      await page.waitForTimeout(1_000);
    }
  });

  test("verify artifact lineage metadata for completed run", async () => {
    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];
    const completedRun = runs.find((r: any) => r.status === "completed");
    test.skip(!completedRun, "No completed runs");

    const detail = await fetchRunDetail(api, completedRun.runId);
    expect(detail).toBeTruthy();
    expect(detail.runId).toBe(completedRun.runId);
    const results = await fetchRunResults(api, completedRun.runId);
    expect(results.length).toBeGreaterThan(0);
    for (const artifact of results) {
      expect(artifact.runId).toBe(completedRun.runId);
      expect(artifact.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(artifact.storageUri).toBeTruthy();
    }
  });
});

test.describe("Design Draft Lifecycle", () => {
  test("create, plan, and compile design draft via API", async () => {
    const draftPayload = {
      draft: {
        contractVersion: "workflow-design-draft-v1",
        engine: "snakemake",
        metadata: {
          name: `e2e-test-draft-${Date.now()}`,
          projectId: "proj_e2e_test",
        },
        inputs: [],
        nodes: [],
        edges: [],
        resources: { bindings: {}, metadata: {} },
        outputs: [],
        provenance: {},
      },
    };

    const createResponse = await api.post("/api/v1/workflow-design-drafts", {
      data: draftPayload,
    });
    expect(createResponse.ok()).toBeTruthy();
    const created = await createResponse.json();
    const draftId = created.data?.draftId;
    expect(draftId).toBeTruthy();

    const planResponse = await api.post(
      `/api/v1/workflow-design-drafts/${draftId}/plan`,
      { data: {} }
    );
    expect(planResponse.ok() || planResponse.status() === 422).toBeTruthy();

    const compileResponse = await api.post(
      `/api/v1/workflow-design-drafts/${draftId}/compile`,
      { data: {} }
    );
    expect(compileResponse.ok() || compileResponse.status() === 422).toBeTruthy();

    const listResponse = await api.get("/api/v1/workflow-design-drafts");
    expect(listResponse.ok()).toBeTruthy();
    const list = await listResponse.json();
    const drafts = list.data?.items || [];
    expect(drafts.length).toBeGreaterThan(0);
    const found = drafts.find((d: any) => d.draftId === draftId);
    expect(found).toBeTruthy();
  });

  test("fork design draft", async () => {
    const draftPayload = {
      draft: {
        contractVersion: "workflow-design-draft-v1",
        engine: "snakemake",
        metadata: {
          name: `e2e-fork-${Date.now()}`,
          projectId: "proj_e2e_test",
        },
        inputs: [],
        nodes: [],
        edges: [],
        resources: { bindings: {}, metadata: {} },
        outputs: [],
        provenance: {},
      },
    };

    const createResponse = await api.post("/api/v1/workflow-design-drafts", {
      data: draftPayload,
    });
    const created = await createResponse.json();
    const draftId = created.data?.draftId;
    test.skip(!draftId, "Failed to create draft");

    const forkResponse = await api.post(
      `/api/v1/workflow-design-drafts/${draftId}/fork`,
      { data: {} }
    );
    expect(forkResponse.ok()).toBeTruthy();
    const forked = await forkResponse.json();
    expect(forked.data?.draftId).toBeTruthy();
    expect(forked.data?.draftId).not.toBe(draftId);
  });
});

test.describe("WorkflowRevision Visibility", () => {
  test("run detail shows workflow revision when available", async ({ page }) => {
    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];
    const runWithRevision = runs.find((r: any) => r.workflowRevisionId);
    test.skip(!runWithRevision, "No runs with workflowRevisionId");

    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(runWithRevision.runId)}`);
    await expect(page.getByText(runWithRevision.runId)).toBeVisible({ timeout: 10_000 });

    const detail = await fetchRunDetail(api, runWithRevision.runId);
    if (detail.workflowRevisionId) {
      await expect(page.getByText(detail.workflowRevisionId).first()).toBeVisible({
        timeout: 5_000,
      });
    }
  });

  test("results list shows all runs", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });

    const runsResponse = await api.get("/api/v1/runs");
    const runs = (await runsResponse.json()).data?.items || [];

    for (const run of runs.slice(0, 5)) {
      if (run.runId) {
        await expect(page.getByText(run.runId).first()).toBeVisible({ timeout: 5_000 });
      }
    }
  });
});
