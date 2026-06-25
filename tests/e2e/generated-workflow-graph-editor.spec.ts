import { test, expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

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
  await mockGraphEditorCapabilityTools(page);

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

  await page.getByPlaceholder("搜索节点").fill("");
  await addGraphTool(page, GRAPH_TOOL_REVISIONS.incompatibleTarget);
  await addGraphTool(page, GRAPH_TOOL_REVISIONS.source);
  await expect(nodeCards).toHaveCount(3, { timeout: 10_000 });
  await expect(page.getByTestId("workflow-graph-edge-row")).toHaveCount(0);
  await page.getByRole("button", { name: "自动布局" }).click();

  const sourceNodeId = await nodeIdForTool(page, "E2E BAM source");
  const incompatibleTargetNodeId = await nodeIdForTool(page, "E2E VCF target");
  const sourceBamHandle = graphHandle(page, "output", sourceNodeId, "bam");
  const incompatibleVcfHandle = graphHandle(page, "input", incompatibleTargetNodeId, "variants_vcf");
  await expect(sourceBamHandle).toBeVisible({ timeout: 10_000 });
  await expect(incompatibleVcfHandle).toBeVisible({ timeout: 10_000 });
  await dragConnection(page, sourceBamHandle, incompatibleVcfHandle);
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-code", "WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE");
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-state", "message");
  await expect(connectionNotice).toHaveAttribute("data-converter-insert-enabled", "false");
  await expect(page.getByTestId("workflow-graph-edge-row")).toHaveCount(0);

  await expect(inputHandle).toBeVisible({ timeout: 10_000 });
  await dragConnection(page, sourceBamHandle, inputHandle);
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-code", "");
  await expect(connectionNotice).toHaveAttribute("data-connection-notice-state", "message");
  const edgeRows = page.getByTestId("workflow-graph-edge-row");
  await expect(edgeRows).toHaveCount(1, { timeout: 10_000 });
  await expect(edgeRows.first()).toHaveAttribute("data-workflow-edge-audit-source", "manual");
  await expect(edgeRows.first().getByTestId("workflow-graph-edge-audit")).toContainText("手动连接");
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

const GRAPH_TOOL_REVISIONS = {
  incompatibleTarget: "e2e-vcf-target-rev",
  source: "e2e-bam-source-rev",
  target: "e2e-bam-target-rev",
};

async function mockGraphEditorCapabilityTools(page: Page) {
  await page.route("**/api/v1/tool-capabilities/capability-graph?**", async (route) => {
    await route.fulfill({
      json: {
        data: {
          agentSelectableProfileIds: [],
          agentSelectableTools: [
            workflowReadyTool({
              id: "e2e-bam-target",
              input: {
                data: "data_0863",
                format: "format_2572",
                kind: "file",
                name: "bam",
              },
              name: "E2E BAM target",
              output: {
                data: "data_3671",
                format: "format_3464",
                kind: "file",
                name: "metrics_json",
              },
              revisionId: GRAPH_TOOL_REVISIONS.target,
            }),
            workflowReadyTool({
              id: "e2e-vcf-target",
              input: {
                data: "data_3498",
                format: "format_3016",
                kind: "file",
                name: "variants_vcf",
              },
              name: "E2E VCF target",
              output: {
                data: "data_3671",
                format: "format_3475",
                kind: "file",
                name: "summary_tsv",
              },
              revisionId: GRAPH_TOOL_REVISIONS.incompatibleTarget,
            }),
            workflowReadyTool({
              id: "e2e-bam-source",
              input: {
                data: "data_2044",
                format: "format_1930",
                kind: "file",
                name: "reads_fastq",
              },
              name: "E2E BAM source",
              output: {
                data: "data_0863",
                format: "format_2572",
                kind: "file",
                name: "bam",
              },
              revisionId: GRAPH_TOOL_REVISIONS.source,
            }),
          ],
          capabilityBundleGate: {},
          capabilityBundles: [],
          capabilityBundleVersion: "capability-bundle-v1",
          catalog: {
            addableTotal: 0,
            hasMore: false,
            items: [],
            page: 1,
            pageSize: 100,
            qualityCounts: {},
            query: "",
            total: 0,
          },
          contractVersion: "capability-graph-snapshot-v1",
          packIds: [],
          profileCount: 0,
          query: "",
          registeredToolCounts: {
            productionEnabled: 0,
            total: 3,
            workflowReady: 3,
          },
          registeredTools: [],
          selectionPolicy: {
            agentSelectableOnly: false,
            targetPlatform: "linux-64",
          },
          semanticGraph: {
            agentSelectableProfileIds: [],
            contractVersion: "semantic-capability-graph-v1",
            edges: [],
            nodes: [],
          },
          targetPlatform: "linux-64",
        },
      },
    });
  });
}

function workflowReadyTool({
  id,
  input,
  name,
  output,
  revisionId,
}: {
  id: string;
  input: GraphPortFixture;
  name: string;
  output: GraphPortFixture;
  revisionId: string;
}) {
  const version = "1.0.0";
  const packageSpec = `${id}=${version}`;
  const ruleTemplate = {
    commandTemplate: `mkdir -p results logs && cp {input.${input.name}} {output.${output.name}}`,
    environment: {
      channels: ["conda-forge", "bioconda"],
      conda: {
        channels: ["conda-forge", "bioconda"],
        dependencies: [packageSpec],
      },
      dependencies: [packageSpec],
    },
    inputs: [{ ...input, path: `inputs/${input.name}` }],
    log: `logs/${id}.log`,
    outputs: [{ ...output, path: `results/${output.name}` }],
    params: {},
    schedulerResources: { mem_mb: 128 },
    smokeTest: {
      inputs: {
        [input.name]: { content: "fixture\n", filename: `${input.name}.txt` },
      },
      timeoutSeconds: 30,
    },
    threads: 1,
  };
  return {
    id,
    name,
    packageSpec,
    platforms: ["linux-64"],
    qualityTier: "workflow-ready",
    ruleTemplate,
    selectedPackageSpec: packageSpec,
    selectedVersion: version,
    source: "bioconda",
    sourceLabel: "Bioconda",
    summary: "E2E graph editor workflow-ready tool",
    targetPlatform: "linux-64",
    targetPlatformSupported: true,
    toolContract: {
      environment: {
        channelPriorityStrict: true,
        channels: ["conda-forge", "bioconda"],
        dependencies: [packageSpec],
        declared: true,
        locked: true,
        specified: true,
      },
      package: {
        name: id,
        packageSpec,
        source: "bioconda",
        targetPlatform: "linux-64",
        targetPlatformSupported: true,
        version,
      },
      ruleSpec: {
        action: "commandTemplate",
        inputs: 1,
        log: 1,
        outputs: 1,
        params: 0,
        requiresUserCompletion: false,
        schedulerResources: 1,
        source: "e2e",
        threads: 1,
      },
      smokeTest: {
        inputs: 1,
        missingInputs: [],
        requiredInputs: 1,
        specified: true,
      },
      state: "WorkflowReady",
      workflowReady: true,
    },
    toolRevisionId: revisionId,
    version,
  };
}

type GraphPortFixture = {
  data: string;
  format: string;
  kind: string;
  name: string;
};

async function addGraphTool(page: Page, toolRevisionId: string) {
  const toolButton = page.locator(`[data-workflow-tool-revision-id="${cssAttributeValue(toolRevisionId)}"]`);
  await expect(toolButton).toBeVisible({ timeout: 10_000 });
  await toolButton.click();
}

async function nodeIdForTool(page: Page, toolName: string) {
  const nodeCard = page.getByTestId("rule-graph-node-card").filter({ hasText: toolName });
  await expect(nodeCard).toHaveCount(1, { timeout: 10_000 });
  const nodeId = await nodeCard.first().getAttribute("data-rule-node-id");
  expect(nodeId).toBeTruthy();
  return String(nodeId);
}

function graphHandle(page: Page, direction: "input" | "output", nodeId: string, portName: string) {
  return page.locator(
    `[data-testid="rule-graph-handle-${direction}-${cssAttributeValue(nodeId)}-${cssAttributeValue(portName)}"]`
  );
}
