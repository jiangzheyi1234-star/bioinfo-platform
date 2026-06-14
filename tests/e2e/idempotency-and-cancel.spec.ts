import { test, expect, APIRequestContext } from "@playwright/test";
import {
  createApiClient,
  waitForApiReady,
  prepareE2EFixture,
  fetchRunDetail,
  fetchRunEvents,
  buildTestRunSpec,
  cancelRun,
  submitRun,
  waitForCompletedRun,
  type E2EFixture,
} from "./api-helpers";

let api: APIRequestContext;
let fixture: E2EFixture;

test.beforeAll(async () => {
  api = await createApiClient();
  await waitForApiReady(api);
  fixture = await prepareE2EFixture(api);
});

test.afterAll(async () => {
  await api?.dispose();
});

test.describe("Idempotency", () => {
  test("duplicate submission with same idempotency key returns same run", async () => {
    const idempotencyKey = `idem_e2e_dup_${Date.now()}`;
    const runSpec = {
      ...(await buildTestRunSpec(api, fixture, "proj_e2e_idem", "dup")),
      idempotencyKey,
    };

    const body1 = await submitRun(api, runSpec);
    const body2 = await submitRun(api, runSpec);

    expect(body1.runId).toBeTruthy();
    expect(body2.runId).toBe(body1.runId);
    const completed = await waitForCompletedRun(api, body1.runId);
    expect(completed.status).toBe("completed");
  });

  test("different idempotency keys create different runs", async () => {
    const baseSpec = await buildTestRunSpec(api, fixture, "proj_e2e_idem", "different");
    const ts = Date.now();

    const body1 = await submitRun(api, {
      ...baseSpec,
      requestId: `req_a_${ts}`,
      idempotencyKey: `idem_a_${ts}`,
    });
    const body2 = await submitRun(api, {
      ...baseSpec,
      requestId: `req_b_${ts}`,
      idempotencyKey: `idem_b_${ts}`,
    });

    expect(body1.runId).toBeTruthy();
    expect(body2.runId).toBeTruthy();
    expect(body1.runId).not.toBe(body2.runId);
  });
});

test.describe("Run Cancellation", () => {
  test("cancel a run via API records cancel command and event", async () => {
    const runSpec = await buildTestRunSpec(api, fixture, "proj_e2e_cancel", "cancel");
    const submitted = await submitRun(api, runSpec);
    const runId = String(submitted.runId || "");
    expect(runId).toBeTruthy();

    const canceled = await cancelRun(api, runId);
    expect(canceled.runId).toBe(runId);
    expect(canceled.commandId).toBeTruthy();
    expect(canceled.stage).toBe("cancel");

    const detail = await fetchRunDetail(api, runId);
    expect(["canceling", "canceled", "cancelled", "completed"]).toContain(String(detail.status || "").toLowerCase());
    const events = await fetchRunEvents(api, runId);
    const cancelEvent = events.find((event) => event.eventType === "run_cancel_requested");
    expect(cancelEvent).toBeTruthy();
    expect(cancelEvent.commandId).toBe(canceled.commandId);
  });

  test("cancel request is visible in UI detail", async ({ page }) => {
    const runSpec = await buildTestRunSpec(api, fixture, "proj_e2e_ui_cancel", "ui_cancel");
    const submitted = await submitRun(api, runSpec);
    const runId = String(submitted.runId || "");
    expect(runId).toBeTruthy();

    const canceled = await cancelRun(api, runId);
    await page.goto(`/workflows/results/detail?run=${encodeURIComponent(runId)}`);
    await expect(page.getByText(runId).first()).toBeVisible({ timeout: 10_000 });
    const events = await fetchRunEvents(api, runId);
    expect(events.some((event) => event.commandId === canceled.commandId)).toBeTruthy();
  });
});

test.describe("Agent Disconnect Recovery", () => {
  test("run detail and events persist after polling gap", async () => {
    const runSpec = await buildTestRunSpec(api, fixture, "proj_e2e_disconnect", "disconnect");
    const submitted = await submitRun(api, runSpec);
    const runId = String(submitted.runId || "");
    expect(runId).toBeTruthy();

    await new Promise((r) => setTimeout(r, 3_000));

    const detail = await fetchRunDetail(api, runId);
    expect(detail.runId).toBe(runId);
    const events = await fetchRunEvents(api, runId);
    expect(events.length).toBeGreaterThan(0);
    expect(events.some((event) => event.runId === runId)).toBeTruthy();
  });
});
