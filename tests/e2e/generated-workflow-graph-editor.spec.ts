import { test, expect, APIRequestContext, type Locator, type Page } from "@playwright/test";

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

  const outputHandle = page
    .locator(`[data-testid^="rule-graph-handle-output-"][data-rule-node-id="${cssAttributeValue(String(nodeId))}"]`)
    .first();
  const inputHandle = page
    .locator(`[data-testid^="rule-graph-handle-input-"][data-rule-node-id="${cssAttributeValue(String(nodeId))}"]`)
    .first();
  await expect(outputHandle).toBeVisible({ timeout: 10_000 });
  await expect(inputHandle).toBeVisible({ timeout: 10_000 });
  await dragConnection(page, outputHandle, inputHandle);
  const connectionNotice = page.getByTestId("workflow-graph-connection-notice");
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-code", "WORKFLOW_GRAPH_CONNECTION_SELF");
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-state", "message");
  await expect(connectionNotice).toHaveAttribute("data-converter-insert-enabled", "false");
  await expect(page.getByTestId("workflow-graph-edge-row")).toHaveCount(0);

  const subflowInput = page.getByTestId(`workflow-subflow-label-${nodeId}`);
  await subflowInput.fill("QC Stage");
  await page.getByRole("button", { name: "应用子流程标签" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "清除子流程标签" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toHaveCount(0);

  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByText("子流程 · QC Stage")).toBeVisible({ timeout: 10_000 });
});

async function dragConnection(page: Page, source: Locator, target: Locator) {
  const sourceBox = await source.boundingBox();
  const targetBox = await target.boundingBox();
  if (!sourceBox || !targetBox) {
    throw new Error("Graph handle bounding boxes are required for connection drag proof");
  }
  const sourceCenter = {
    x: sourceBox.x + sourceBox.width / 2,
    y: sourceBox.y + sourceBox.height / 2,
  };
  const targetCenter = {
    x: targetBox.x + targetBox.width / 2,
    y: targetBox.y + targetBox.height / 2,
  };
  await page.mouse.move(sourceCenter.x, sourceCenter.y);
  await page.mouse.down();
  await page.mouse.move(targetCenter.x, targetCenter.y, { steps: 12 });
  await page.mouse.up();
}

function cssAttributeValue(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
