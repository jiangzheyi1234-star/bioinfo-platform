import { expect, test, type Page, type Route } from "@playwright/test";

const SERVER_ID = "srv_observation_ui";
const SESSION_ID = "ags_observation_ui";
const PRIVATE_SENTINEL = "sentinel://private/request/raw-model-output";

test.describe("Agent Workbench snapshot-derived observation panel", () => {
  test("renders only the bounded client observation before the audit timeline", async ({
    page,
  }) => {
    const observedApiMethods = await installObservationRoutes(page, true);
    await openFixtureSession(page);

    const panel = page.getByTestId("agent-session-observation");
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute("data-status", "created");
    await expect(panel).toHaveAttribute("data-attention", "plan_not_started");
    await expect(panel).toHaveAttribute("data-timing-status", "client_estimate");
    await expect(panel).toContainText(
      "刷新时的客户端估算；不能据此判断 stalled、SLA 或 timeout。"
    );
    await expect(panel).toContainText("0 / 3");
    await expect(panel).toContainText("1 个 · head #1");
    await expect(panel).toContainText("Snapshot endpoint requires full-chain validation");
    await expect(panel).toContainText(
      "正式 snapshot endpoint 的成功响应要求 runner 完整 hash-chain 校验；浏览器仅验证 sequence 与 prevEventHash，不能重算已隐去 commandHash 的 eventHash。"
    );
    await expect(panel).not.toContainText(PRIVATE_SENTINEL);
    await expect(
      panel.locator(
        "button, input, textarea, select, a, [role='button'], [draggable='true'], [contenteditable='true']"
      )
    ).toHaveCount(0);

    await expect(
      page.locator(
        '[data-testid="agent-session-observation"] + [data-testid="agent-event-timeline"]'
      )
    ).toBeVisible();
    expect(observedApiMethods.length).toBeGreaterThan(0);
    expect(observedApiMethods.every((method) => method === "GET")).toBe(true);
  });

  test("shows a stable fail-closed error instead of inventing a state-entry time", async ({
    page,
  }) => {
    await installObservationRoutes(page, false);
    await openFixtureSession(page);

    const error = page.getByTestId("agent-session-observation-error");
    await expect(error).toBeVisible();
    await expect(error).toContainText("AGENT_SESSION_OBSERVATION_STATE_ENTRY_REQUIRED");
    await expect(error).not.toContainText(PRIVATE_SENTINEL);
    await expect(page.getByTestId("agent-session-observation")).toHaveCount(0);
    await expect(page.getByTestId("agent-event-timeline")).toBeVisible();
  });
});

async function openFixtureSession(page: Page): Promise<void> {
  await page.goto(
    `/workflows?server=${encodeURIComponent(SERVER_ID)}&session=${encodeURIComponent(SESSION_ID)}`
  );
  await expect(page.getByRole("heading", { level: 1, name: "Agent 工作台" })).toBeVisible();
  await expect(page.getByTestId("agent-session-summary")).toContainText(SESSION_ID);
}

async function installObservationRoutes(
  page: Page,
  realStateEntry: boolean
): Promise<string[]> {
  const snapshot = observationSnapshot(realStateEntry);
  const observedApiMethods: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    observedApiMethods.push(request.method());
    const url = new URL(request.url());
    if (request.method() !== "GET") {
      await fulfillJson(route, 405, { detail: "OBSERVATION_UI_READ_ONLY" });
      return;
    }
    if (url.pathname === "/api/v1/servers") {
      await fulfillJson(route, 200, {
        data: {
          items: [
            {
              serverId: SERVER_ID,
              label: "Observation fixture runner",
              connected: true,
              ready: true,
            },
          ],
        },
      });
      return;
    }
    if (url.pathname === "/api/v1/agent-sessions") {
      await fulfillJson(route, 200, { data: { items: [snapshot.session] } });
      return;
    }
    if (url.pathname === `/api/v1/agent-sessions/${SESSION_ID}/snapshot`) {
      await fulfillJson(route, 200, { data: snapshot });
      return;
    }
    await fulfillJson(route, 404, { detail: `UNEXPECTED_FIXTURE_READ:${url.pathname}` });
  });
  return observedApiMethods;
}

async function fulfillJson(route: Route, status: number, value: unknown): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

function observationSnapshot(realStateEntry: boolean) {
  const createdAt = "2020-01-01T00:00:00Z";
  const event = {
    schemaVersion: "agent-event.v1",
    eventId: "agev_observation_ui_1",
    sessionId: SESSION_ID,
    sequence: 1,
    eventType: "agent.session_created",
    fromStatus: realStateEntry ? null : "created",
    toStatus: "created",
    stateVersion: 1,
    planGeneration: 0,
    requestId: PRIVATE_SENTINEL,
    correlationId: null,
    idempotencyKey: PRIVATE_SENTINEL,
    actor: PRIVATE_SENTINEL,
    payload: { rawModelOutput: PRIVATE_SENTINEL },
    payloadHash: "b".repeat(64),
    eventHash: "c".repeat(64),
    prevEventHash: null,
    createdAt,
  };
  const session = {
    contractVersion: "agent-session.v1",
    sessionId: SESSION_ID,
    projectId: "project-observation-ui",
    goal: {
      summary: "Observe one durable Agent session",
      successCriteria: ["Keep the observation bounded and read-only"],
      context: {},
    },
    constraints: {
      allowedToolRevisionIds: [],
      forbiddenActions: [],
      requirements: {},
    },
    budget: {
      maxModelTurns: 8,
      maxToolCalls: 12,
      maxReplans: 3,
      maxRetries: 2,
      maxWallClockSeconds: 3600,
    },
    status: "created",
    stateVersion: 1,
    planGeneration: 0,
    activeDraftId: null,
    activeDraftRevision: null,
    activePlanHash: null,
    workflowRevisionId: null,
    planner: {
      adapterId: "fixture.observation.ui.v1",
      adapterVersion: "1",
      modelRef: null,
    },
    lastErrorCode: "",
    creationRequestId: "create-observation-ui",
    createdBy: "fixture-principal",
    createdAt,
    updatedAt: createdAt,
    cancelledAt: null,
  };
  return {
    contractVersion: "agent-session-snapshot.v1",
    session,
    events: [event],
    plans: [],
    approvals: [],
  };
}
