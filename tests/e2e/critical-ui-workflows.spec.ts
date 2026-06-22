import { test, expect, APIRequestContext } from "@playwright/test";

import {
  GENERATED_TOOL_RUN_PIPELINE_ID,
  cancelToolPrepareJob,
  createApiClient,
  createWorkflowDesignDraftRecord,
  deleteDatabase,
  deleteBioToolPack,
  fetchToolPrepareJob,
  findDatabaseByName,
  prepareE2EFixture,
  requireDatabaseRegistrationFixture,
  seedValidationQueueCandidate,
  waitForApiReady,
  waitForCompletedRun,
} from "./api-helpers";

let api: APIRequestContext;
const createdDatabaseIds: string[] = [];
const createdPrepareJobIds: string[] = [];
const importedToolPackIds = new Set<string>();

test.beforeAll(async () => {
  api = await createApiClient();
  await waitForApiReady(api);
});

test.afterAll(async () => {
  for (const jobId of createdPrepareJobIds) {
    await cancelToolPrepareJob(api, jobId).catch(() => undefined);
  }
  for (const packId of importedToolPackIds) {
    await deleteBioToolPack(api, packId).catch(() => undefined);
  }
  for (const databaseId of createdDatabaseIds.reverse()) {
    await deleteDatabase(api, databaseId).catch(() => undefined);
  }
  await api?.dispose();
});

test.describe("Critical UI Workflow Closure", () => {
  test("registers a reference database through the UI and exposes validation actions", async ({ page }) => {
    const registration = await requireDatabaseRegistrationFixture(api);
    const databaseName = `E2E UI Database ${Date.now()}`;

    await page.goto("/workflows/databases");
    await expect(page.getByRole("heading", { name: "数据库" })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "添加数据库" }).click();
    await page.getByTestId(`database-template-${registration.templateId}`).click();
    await page.getByLabel("数据库名称").fill(databaseName);
    await page.locator("#database-path").fill(registration.path);

    const [createResponse] = await Promise.all([
      page.waitForResponse((response) => apiPath(response, "POST", "/api/v1/databases")),
      page.getByRole("button", { name: "校验并保存" }).click(),
    ]);
    const created = await responseData(createResponse);
    const databaseId = String(created?.id || "");
    expect(databaseId).toBeTruthy();
    createdDatabaseIds.push(databaseId);

    const registered = await findDatabaseByName(api, databaseName);
    expect(registered?.id).toBe(databaseId);
    expect(registered?.status).toBe("available");
    expect(String(registered?.metadata?.templateId || "")).toBe(registration.templateId);

    const row = page.getByTestId(`database-row-${databaseId}`);
    await expect(row).toContainText(databaseName, { timeout: 10_000 });
    await expect(row).toContainText("可用");
    await row.hover();
    await row.getByRole("button", { name: `${databaseName} 操作` }).click();
    await page.getByRole("menuitem", { name: "查看校验详情" }).click();
    await expect(page.getByRole("dialog")).toContainText(databaseName);
    await expect(page.getByRole("dialog")).toContainText(registration.templateId);
  });

  test("queues a tool validation job from the processing queue UI", async ({ page }) => {
    const seeded = await seedValidationQueueCandidate(api);
    importedToolPackIds.add(seeded.packId);
    const candidate = seeded.candidate;
    const candidateId = String(candidate.candidateId || "");
    expect(candidateId).toBeTruthy();

    await page.goto("/workflows/tools");
    await expect(page.getByRole("heading", { level: 1, name: "工具" })).toBeVisible({ timeout: 10_000 });
    const queue = page.getByTestId("tool-processing-queue");
    await expect(queue).toBeVisible({ timeout: 20_000 });
    await queue.locator("summary").click();

    const row = page.getByTestId(`tool-validation-queue-item-${candidateId}`);
    await expect(row).toBeVisible({ timeout: 10_000 });
    const [jobResponse] = await Promise.all([
      page.waitForResponse((response) => apiPath(response, "POST", "/api/v1/tools/prepare-jobs")),
      page.getByTestId(`tool-validation-queue-validate-${candidateId}`).click(),
    ]);
    const job = await responseData(jobResponse);
    const jobId = String(job?.jobId || "");
    expect(jobId).toBeTruthy();
    createdPrepareJobIds.push(jobId);

    const fetched = await fetchToolPrepareJob(api, jobId);
    expect(fetched.jobId).toBe(jobId);
    expect(String(fetched.toolId || fetched.request?.id || "")).toBeTruthy();
    await expect(page.getByLabel("prepare job queue")).toContainText("验证任务", { timeout: 20_000 });
  });

  test("saves, validates, compiles, and submits a generated workflow through the UI", async ({ page }) => {
    test.setTimeout(240_000);
    const fixture = await prepareE2EFixture(api);
    const suffix = `ui_${Date.now()}`;
    const { draft, record } = await createWorkflowDesignDraftRecord(api, fixture, suffix);
    const draftName = String(record?.name || (draft.metadata as { name?: string }).name || "");
    expect(draftName).toBeTruthy();

    await page.goto(`/workflows/detail?workflow=${encodeURIComponent(GENERATED_TOOL_RUN_PIPELINE_ID)}`);
    await expect(page.getByText("工具工作流")).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("workflow-design-draft-select").click();
    await page.getByRole("option", { name: draftName, exact: true }).click();
    await expect(page.getByText(record.draftId).first()).toBeVisible({ timeout: 10_000 });

    await page.locator("#workflow-files").setInputFiles({
      name: "e2e.fastq",
      mimeType: "text/plain",
      buffer: Buffer.from("@read-1\nACGTACGT\n+\nIIIIIIII\n", "utf8"),
    });
    await expect(page.getByText("e2e.fastq")).toBeVisible();

    const [planResponse] = await Promise.all([
      page.waitForResponse((response) => apiPathMatches(response, "POST", /\/api\/v1\/workflow-design-drafts\/[^/]+\/plan$/)),
      page.getByRole("button", { name: "保存并验证" }).click(),
    ]);
    const plan = await responseData(planResponse);
    expect(plan.valid).toBe(true);
    await expect(page.getByText("plan valid")).toBeVisible({ timeout: 10_000 });

    const compileButton = page.getByRole("button", { name: "编译导出" });
    await expect(compileButton).toBeEnabled({ timeout: 10_000 });
    const [compileResponse] = await Promise.all([
      page.waitForResponse((response) => apiPathMatches(response, "POST", /\/api\/v1\/workflow-design-drafts\/[^/]+\/compile$/)),
      compileButton.click(),
    ]);
    const compiled = await responseData(compileResponse);
    const workflowRevisionId = String(compiled.workflowRevisionId || "");
    expect(workflowRevisionId).toMatch(/^wfrev_/);
    await expect(page.getByText(workflowRevisionId).first()).toBeVisible({ timeout: 10_000 });

    const submitButton = page.getByRole("button", { name: "提交流程" });
    await expect(submitButton).toBeEnabled({ timeout: 10_000 });
    const [submitResponse] = await Promise.all([
      page.waitForResponse((response) => apiPath(response, "POST", "/api/v1/runs")),
      submitButton.click(),
    ]);
    const submitted = await responseData(submitResponse);
    const runId = String(submitted.runId || "");
    expect(runId).toBeTruthy();
    await expect(page.getByText(`已提交 ${runId}`)).toBeVisible({ timeout: 10_000 });

    const completed = await waitForCompletedRun(api, runId, 220_000);
    expect(completed.status).toBe("completed");
    expect(completed.workflowRevisionId).toBe(workflowRevisionId);
    expect(completed.runSpec.workflowRevisionId).toBe(workflowRevisionId);
  });
});

function apiPath(response: { url(): string; request(): { method(): string } }, method: string, path: string) {
  return apiPathMatches(response, method, new RegExp(`^${escapeRegExp(path)}$`));
}

function apiPathMatches(response: { url(): string; request(): { method(): string } }, method: string, pathPattern: RegExp) {
  return response.request().method() === method && pathPattern.test(new URL(response.url()).pathname);
}

async function responseData(response: { ok(): boolean; status(): number; text(): Promise<string>; json(): Promise<any> }) {
  if (!response.ok()) {
    throw new Error(`E2E API response failed: ${response.status()} ${await response.text()}`);
  }
  const body = await response.json();
  return body.data;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
