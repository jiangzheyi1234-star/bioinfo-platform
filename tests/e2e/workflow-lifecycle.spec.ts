import { test, expect, APIRequestContext, type Page } from "@playwright/test";
import {
  createApiClient,
  waitForApiReady,
  prepareE2EFixture,
  fetchWorkflowCatalog,
  fetchRunDetail,
  fetchRunEvents,
  fetchRunResults,
  fetchRunResultBundle,
  fetchResultPreview,
  fetchRuns,
  createAndCompletePipelineRun,
  createWorkflowDesignFixture,
  submitWorkflowDesignRun,
  waitForCompletedRun,
  type E2EFixture,
} from "./api-helpers";

let api: APIRequestContext;
let fixture: E2EFixture;
let completedRun: any;
let designRun: any;
let workflowRevisionId = "";

test.beforeAll(async () => {
  api = await createApiClient();
  await waitForApiReady(api);
  fixture = await prepareE2EFixture(api);
  completedRun = await createAndCompletePipelineRun(api, fixture, "lifecycle");
  const design = await createWorkflowDesignFixture(api, fixture, "lifecycle");
  workflowRevisionId = design.compiled.workflowRevisionId;
  const submitted = await submitWorkflowDesignRun(api, fixture, design.compiled, "lifecycle");
  designRun = await waitForCompletedRun(api, String(submitted.runId));
});

test.afterAll(async () => {
  await api?.dispose();
});

test.describe("Workflow Catalog and Navigation", () => {
  test("browse workflow catalog page", async ({ page }) => {
    await page.goto("/workflows");
    await expect(page.getByText("流程目录")).toBeVisible({ timeout: 10_000 });

    const catalog = await fetchWorkflowCatalog(api);
    expect(catalog.length).toBeGreaterThan(0);
    await expect(page.getByRole("table")).toBeVisible();
    for (const item of catalog.slice(0, 3)) {
      await expect(page.getByText(item.name).first()).toBeVisible({ timeout: 5_000 });
    }
  });

  test("navigate to workflow detail page", async ({ page }) => {
    await page.goto(`/workflows/detail?workflow=${encodeURIComponent(fixture.workflow.id)}`);
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
  test("completed fixture run appears in results page", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });
    await waitForResultsPageLoaded(page);
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 15_000 });
  });

  test("view run detail page with events and logs", async ({ page }) => {
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(completedRun.runId)}`);
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 10_000 });

    const events = await fetchRunEvents(api, completedRun.runId);
    expect(events.length).toBeGreaterThan(0);
    await expect(page.getByText(events.at(-1).message).first()).toBeVisible({ timeout: 10_000 });
  });

  test("switch between run detail tabs", async ({ page }) => {
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(completedRun.runId)}`);
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 10_000 });

    const tabs = ["概览", "产物", "stdout", "stderr"];
    for (const tab of tabs) {
      const tabButton = page.getByRole("button", { name: tab });
      await expect(tabButton).toBeVisible({ timeout: 5_000 });
      await tabButton.click();
    }
  });

  test("filter and refresh runs list", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });
    await waitForResultsPageLoaded(page);

    for (const filter of ["全部", "运行中", "已完成", "失败"]) {
      await page.getByRole("button", { name: filter, exact: true }).click();
    }
    await page.getByRole("button", { name: "全部", exact: true }).click();
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 10_000 });
  });
});

test.describe("Artifact Preview and Lineage", () => {
  test("view artifact preview for completed run", async ({ page }) => {
    const results = await fetchRunResults(api, completedRun.runId);
    expect(results.length).toBeGreaterThan(0);
    const resultId = `res_${completedRun.runId}`;
    const preview = await fetchResultPreview(api, resultId, results[0].artifactId);
    expect(preview.artifact?.artifactId).toBe(results[0].artifactId);
    expect(preview.preview?.kind).toBeTruthy();

    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(completedRun.runId)}`);
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "产物" }).click();
    await expect(page.getByText(results[0].artifactId).first()).toBeVisible({ timeout: 10_000 });
  });

  test("verify artifact and event lineage metadata for completed run", async () => {
    const detail = await fetchRunDetail(api, completedRun.runId);
    expect(detail.runId).toBe(completedRun.runId);
    expect(detail.status).toBe("completed");
    const resultBundle = await fetchRunResultBundle(api, completedRun.runId);
    const artifacts = resultBundle.artifacts || [];
    expect(artifacts.length).toBeGreaterThan(0);
    for (const artifact of artifacts) {
      expect(artifact.runId).toBe(completedRun.runId);
      expect(artifact.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(artifact.storageUri).toBeTruthy();
    }
    const events = await fetchRunEvents(api, completedRun.runId);
    expect(events.some((event) => event.eventType === "run_state_changed" || event.eventType === "run_attempt_completed")).toBeTruthy();
  });
});

test.describe("Design Draft and WorkflowRevision Lifecycle", () => {
  test("create, plan, compile, submit, and complete WorkflowRevision run", async () => {
    expect(workflowRevisionId).toMatch(/^wfrev_/);
    expect(designRun.status).toBe("completed");
    expect(designRun.workflowRevisionId).toBe(workflowRevisionId);
    expect(designRun.runSpec.workflowRevisionId).toBe(workflowRevisionId);
    expect(designRun.runSpec.workflowDesign?.draftId).toBeTruthy();
    const designResults = await fetchRunResults(api, designRun.runId);
    expect(designResults.length).toBeGreaterThan(0);
  });

  test("run detail shows workflow revision", async ({ page }) => {
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(designRun.runId)}`);
    await expect(page.getByText(designRun.runId).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(workflowRevisionId).first()).toBeVisible({ timeout: 10_000 });
  });

  test("results list shows fixture runs", async ({ page }) => {
    await page.goto("/workflows/results");
    await expect(page.getByRole("heading", { name: "运行记录" })).toBeVisible({ timeout: 10_000 });
    await waitForResultsPageLoaded(page);

    const runs = await fetchRuns(api);
    expect(runs.some((run: any) => run.runId === completedRun.runId)).toBeTruthy();
    expect(runs.some((run: any) => run.runId === designRun.runId)).toBeTruthy();
    await expect(page.getByText(completedRun.runId).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(designRun.runId).first()).toBeVisible({ timeout: 10_000 });
  });
});

async function waitForResultsPageLoaded(page: Page): Promise<void> {
  await expect(page.getByText("正在读取运行记录")).toBeHidden({ timeout: 45_000 });
  await expect(page.getByRole("button", { name: "刷新", exact: true })).toBeEnabled({ timeout: 5_000 });
}
