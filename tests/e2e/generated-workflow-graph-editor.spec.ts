import { test, expect, APIRequestContext } from "@playwright/test";

import {
  GENERATED_TOOL_RUN_PIPELINE_ID,
  createApiClient,
  prepareE2EFixture,
  waitForApiReady,
} from "./api-helpers";

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await createApiClient();
  await waitForApiReady(api);
});

test.afterAll(async () => {
  await api?.dispose();
});

test("graph editor supports add, undo, redo, search focus, layout, and subflow labels", async ({ page }) => {
  test.setTimeout(120_000);
  await prepareE2EFixture(api);

  await page.goto(`/workflows/detail?workflow=${encodeURIComponent(GENERATED_TOOL_RUN_PIPELINE_ID)}`);
  await expect(page.getByText("工具工作流")).toBeVisible({ timeout: 20_000 });

  const canvas = page.locator("[data-workflow-react-flow-canvas]");
  await expect(canvas).toBeVisible({ timeout: 10_000 });
  const nodeCards = page.getByTestId("rule-graph-node-card");
  await expect(nodeCards).toHaveCount(0);

  const addStepButton = page.getByRole("button", { name: "添加步骤", exact: true }).first();
  await expect(addStepButton).toBeEnabled({ timeout: 20_000 });
  await addStepButton.click();
  await expect(nodeCards).toHaveCount(1, { timeout: 10_000 });
  const nodeId = await nodeCards.first().getAttribute("data-rule-node-id");
  expect(nodeId).toBeTruthy();

  await page.getByRole("button", { name: "撤销" }).click();
  await expect(nodeCards).toHaveCount(0, { timeout: 10_000 });

  await page.getByRole("button", { name: "重做" }).click();
  await expect(nodeCards).toHaveCount(1, { timeout: 10_000 });

  await page.getByPlaceholder("搜索节点").fill(String(nodeId));
  await expect(page.getByTestId("workflow-graph-search-count")).toHaveText(/1\/1/, { timeout: 10_000 });
  await expect(page.getByTestId(`rule-flow-node-${nodeId}`)).toHaveAttribute("data-search-state", "active");

  await page.getByRole("button", { name: "自动布局" }).click();
  await expect(nodeCards).toHaveCount(1, { timeout: 10_000 });
  await expect(page.getByTestId(`rule-flow-node-${nodeId}`)).toBeVisible();

  const subflowInput = page.getByTestId(`workflow-subflow-label-${nodeId}`);
  await subflowInput.fill("QC Stage");
  await page.getByRole("button", { name: "应用子流程标签" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "清除子流程标签" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toHaveCount(0);

  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toBeVisible({ timeout: 10_000 });
});
