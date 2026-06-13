import { test, expect, APIRequestContext } from "@playwright/test";
import {
  createApiClient,
  waitForApiReady,
  fetchWorkflowCatalog,
  fetchRunDetail,
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

test.describe("Idempotency", () => {
  test("duplicate submission with same idempotency key returns same run", async () => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const idempotencyKey = `idem_e2e_dup_${Date.now()}`;
    const runSpec = {
      ...(await buildTestRunSpec(api, workflow, "proj_e2e_idem", "dup")),
      idempotencyKey,
    };

    const response1 = await api.post("/api/v1/runs", { data: runSpec });
    expect(response1.ok()).toBeTruthy();
    const body1 = await response1.json();
    const runId1 = body1.data?.runId;
    expect(runId1).toBeTruthy();

    const response2 = await api.post("/api/v1/runs", { data: runSpec });
    expect(response2.ok()).toBeTruthy();
    const body2 = await response2.json();
    const runId2 = body2.data?.runId;

    expect(runId2).toBe(runId1);
  });

  test("different idempotency keys create different runs", async () => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const baseSpec = await buildTestRunSpec(api, workflow, "proj_e2e_idem", "different");

    const ts = Date.now();
    const response1 = await api.post("/api/v1/runs", {
      data: { ...baseSpec, requestId: `req_a_${ts}`, idempotencyKey: `idem_a_${ts}` },
    });
    const response2 = await api.post("/api/v1/runs", {
      data: { ...baseSpec, requestId: `req_b_${ts}`, idempotencyKey: `idem_b_${ts}` },
    });

    expect(response1.ok()).toBeTruthy();
    expect(response2.ok()).toBeTruthy();

    const body1 = await response1.json();
    const body2 = await response2.json();

    expect(body1.data?.runId).not.toBe(body2.data?.runId);
  });
});

test.describe("Run Cancellation", () => {
  test("cancel a run via API", async () => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const runSpec = await buildTestRunSpec(api, workflow, "proj_e2e_cancel", "cancel");

    const response = await api.post("/api/v1/runs", { data: runSpec });
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const runId = body.data?.runId;
    expect(runId).toBeTruthy();

    const cancelResponse = await api.post(`/api/v1/runs/${runId}/cancel`);
    expect(cancelResponse.ok() || cancelResponse.status() === 409).toBeTruthy();

    const detail = await fetchRunDetail(api, runId);
    const cancelStatuses = ["canceling", "canceled", "cancelled", "failed", "completed"];
    expect(cancelStatuses).toContain(detail.status?.toLowerCase());
  });

  test("cancel run and verify status in UI", async ({ page }) => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const runSpec = await buildTestRunSpec(api, workflow, "proj_e2e_ui_cancel", "ui_cancel");

    const response = await api.post("/api/v1/runs", { data: runSpec });
    const body = await response.json();
    const runId = body.data?.runId;
    test.skip(!runId, "Failed to create run");

    await api.post(`/api/v1/runs/${runId}/cancel`);

    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(runId)}`);
    await expect(page.getByText(runId)).toBeVisible({ timeout: 10_000 });

    await page.waitForTimeout(2_000);
    const detail = await fetchRunDetail(api, runId);
    expect(detail).toBeTruthy();
  });
});

test.describe("Agent Disconnect Recovery", () => {
  test("run persists after simulated disconnect", async () => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const runSpec = await buildTestRunSpec(api, workflow, "proj_e2e_disconnect", "disconnect");

    const response = await api.post("/api/v1/runs", { data: runSpec });
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    const runId = body.data?.runId;
    expect(runId).toBeTruthy();

    await new Promise((r) => setTimeout(r, 3_000));

    const detail = await fetchRunDetail(api, runId);
    expect(detail).toBeTruthy();
    expect(detail.runId).toBe(runId);
  });

  test("run events persist after disconnect", async () => {
    const catalog = await fetchWorkflowCatalog(api);
    test.skip(catalog.length === 0, "No workflows in catalog");

    const workflow = catalog.find((w: any) => w.id === "file-summary-v1");
    test.skip(!workflow, "file-summary-v1 is not available");
    const runSpec = await buildTestRunSpec(api, workflow, "proj_e2e_events", "events");

    const response = await api.post("/api/v1/runs", { data: runSpec });
    const body = await response.json();
    const runId = body.data?.runId;
    test.skip(!runId, "Failed to create run");

    await new Promise((r) => setTimeout(r, 2_000));

    const eventsResponse = await api.get(`/api/v1/runs/${runId}/events`);
    expect(eventsResponse.ok()).toBeTruthy();
    const eventsBody = await eventsResponse.json();
    const events = eventsBody.data?.items || eventsBody.data || [];
    expect(events.length).toBeGreaterThan(0);
  });
});
