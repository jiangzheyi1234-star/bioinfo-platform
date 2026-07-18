import { expect, test } from "@playwright/test";

import {
  AGENT_SESSION_OBSERVATION_ERRORS,
  deriveAgentSessionObservation,
  type AgentSessionObservationAttention,
} from "../../apps/web/app/components/agent-session-observation";
import type {
  AgentBudget,
  AgentEvent,
  AgentSession,
  AgentSessionSnapshot,
  AgentSessionStatus,
} from "../../apps/web/app/components/agent-workbench-model";

const SESSION_ID = "ags_observation_fixture";
const OBSERVED_AT = Date.parse("2026-07-18T00:12:00Z");
const DEFAULT_BUDGET: AgentBudget = {
  maxModelTurns: 8,
  maxToolCalls: 12,
  maxReplans: 3,
  maxRetries: 2,
  maxWallClockSeconds: 3_600,
};

type EventSpec = {
  eventType: string;
  fromStatus: AgentSessionStatus | null;
  toStatus: AgentSessionStatus;
  stateVersion: number;
  planGeneration: number;
  createdAt: string;
};

const HISTORIES: Record<AgentSessionStatus, EventSpec[]> = {
  created: [spec("agent.session_created", null, "created", 1, 0, "00:00")],
  planning: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
  ],
  awaiting_approval: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_validated", "planning", "awaiting_approval", 3, 1, "00:02"),
  ],
  plan_failed: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
  ],
  changes_requested: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_validated", "planning", "awaiting_approval", 3, 1, "00:02"),
    spec("agent.changes_requested", "awaiting_approval", "changes_requested", 4, 1, "00:03"),
  ],
  ready_to_run: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_validated", "planning", "awaiting_approval", 3, 1, "00:02"),
    spec("agent.approval_granted", "awaiting_approval", "awaiting_approval", 3, 1, "00:03"),
    spec("agent.workflow_revision_compiled", "awaiting_approval", "ready_to_run", 4, 1, "00:04"),
  ],
  cancelled: [
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.session_cancelled", "created", "cancelled", 2, 0, "00:01"),
  ],
};

const ATTENTION: Record<AgentSessionStatus, AgentSessionObservationAttention> = {
  created: "plan_not_started",
  planning: "planning_recovery_available",
  awaiting_approval: "human_approval_required",
  plan_failed: "plan_failed",
  changes_requested: "typed_replan_required",
  ready_to_run: "run_authorization_pending",
  cancelled: "terminal",
};

for (const status of Object.keys(HISTORIES) as AgentSessionStatus[]) {
  test(`${status} maps to its exact attention state`, () => {
    const snapshot = snapshotFrom(HISTORIES[status]);
    const observation = deriveAgentSessionObservation(snapshot, OBSERVED_AT);

    expect(observation.lifecycle).toMatchObject({
      status,
      attention: ATTENTION[status],
      timingStatus: "client_estimate",
    });
    expect(observation.source).toMatchObject({
      sessionId: SESSION_ID,
      stateVersion: snapshot.session.stateVersion,
      planGeneration: snapshot.session.planGeneration,
      headSequence: snapshot.events.length,
      headEventHash: snapshot.events.at(-1)?.eventHash,
    });
  });
}

test("same-status approval does not reset awaiting-approval age", () => {
  const history = [
    ...HISTORIES.awaiting_approval,
    spec(
      "agent.approval_granted",
      "awaiting_approval",
      "awaiting_approval",
      3,
      1,
      "00:08"
    ),
  ];
  const observation = deriveAgentSessionObservation(snapshotFrom(history), OBSERVED_AT);

  expect(observation.lifecycle).toEqual({
    status: "awaiting_approval",
    stateEnteredAt: "2026-07-18T00:02:00Z",
    stateAgeSeconds: 600,
    timingStatus: "client_estimate",
    attention: "human_approval_required",
  });
});

test("invalid timestamps and regressed client clocks stay explicitly unmeasured", () => {
  const invalid = snapshotFrom([
    spec("agent.session_created", null, "created", 1, 0, "not-a-timestamp"),
  ]);
  const invalidObservation = deriveAgentSessionObservation(invalid, OBSERVED_AT);
  expect(invalidObservation.lifecycle).toMatchObject({
    stateAgeSeconds: null,
    timingStatus: "invalid_timestamp",
  });

  const planning = snapshotFrom(HISTORIES.planning);
  const regressedObservation = deriveAgentSessionObservation(
    planning,
    Date.parse("2026-07-17T23:59:00Z")
  );
  expect(regressedObservation.lifecycle).toMatchObject({
    stateAgeSeconds: null,
    timingStatus: "clock_regression",
  });
});

test("replan and failure counters are derived only from stable event fields", () => {
  const snapshot = snapshotFrom(
    [
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
      spec("agent.replan_requested", "plan_failed", "planning", 4, 2, "00:03"),
      spec("agent.plan_rejected", "planning", "plan_failed", 5, 2, "00:04"),
    ],
    { budget: { ...DEFAULT_BUDGET, maxReplans: 2 } }
  );
  const observation = deriveAgentSessionObservation(snapshot, OBSERVED_AT);

  expect(observation.counters).toEqual({
    events: 5,
    plans: 0,
    approvals: 0,
    replansUsed: 1,
    replansRemaining: 1,
    planFailures: 2,
    changeRequests: 0,
  });
});

test("head generation mismatch and over-budget history fail closed", () => {
  const mismatch = snapshotFrom(HISTORIES.planning, { planGeneration: 2 });
  expectStableError(
    () => deriveAgentSessionObservation(mismatch, OBSERVED_AT),
    AGENT_SESSION_OBSERVATION_ERRORS.HEAD_GENERATION_MISMATCH
  );

  const overBudget = snapshotFrom(
    [
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
      spec("agent.replan_requested", "plan_failed", "planning", 4, 2, "00:03"),
    ],
    { budget: { ...DEFAULT_BUDGET, maxReplans: 0 } }
  );
  expectStableError(
    () => deriveAgentSessionObservation(overBudget, OBSERVED_AT),
    AGENT_SESSION_OBSERVATION_ERRORS.REPLAN_BUDGET_EXCEEDED
  );

});

test("the latest valid replan transition defines the current planning age", () => {
  const snapshot = snapshotFrom([
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
    spec("agent.replan_requested", "plan_failed", "planning", 4, 2, "00:03"),
  ]);

  const observation = deriveAgentSessionObservation(snapshot, OBSERVED_AT);

  expect(observation.lifecycle).toMatchObject({
    status: "planning",
    stateEnteredAt: "2026-07-18T00:03:00Z",
    stateAgeSeconds: 540,
  });
  expect(observation.counters.replansUsed).toBe(1);
});

test("runner-impossible event semantics fail closed", () => {
  const cases = [
    snapshotFrom([
      spec("agent.plan_requested", null, "planning", 1, 1, "00:00"),
    ]),
    snapshotFrom([
      ...HISTORIES.awaiting_approval,
      spec(
        "agent.plan_validated",
        "awaiting_approval",
        "awaiting_approval",
        3,
        1,
        "00:03"
      ),
    ]),
    snapshotFrom([
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.approval_granted", "planning", "planning", 2, 1, "00:02"),
    ]),
    snapshotFrom([
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.draft_created", "planning", "planning", 2, 1, "00:02"),
    ]),
    snapshotFrom([
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.replan_requested", "planning", "planning", 3, 2, "00:02"),
    ]),
    snapshotFrom([
      spec("agent.session_created", null, "created", 1, 0, "00:00"),
      spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
      spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
      spec("agent.replan_requested", "plan_failed", "planning", 4, 3, "00:03"),
    ]),
  ];

  for (const snapshot of cases) {
    expectStableError(
      () => deriveAgentSessionObservation(snapshot, OBSERVED_AT),
      AGENT_SESSION_OBSERVATION_ERRORS.EVENT_SEMANTICS_INVALID
    );
  }
});

test("sequence, hash linkage, status chain, scope, and head projection mismatches fail closed", () => {
  const cases: Array<{
    mutate: (snapshot: AgentSessionSnapshot) => void;
    code: string;
  }> = [
    {
      mutate: (snapshot) => {
        snapshot.events[1].sequence = 3;
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_SEQUENCE_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[1].prevEventHash = "sentinel-prev-hash";
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_PREV_HASH_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[0].fromStatus = "created";
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATUS_CHAIN_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[1].fromStatus = "awaiting_approval";
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATUS_CHAIN_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[1].stateVersion = 1;
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATE_VERSION_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[1].stateVersion = 3;
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATE_VERSION_INVALID,
    },
    {
      mutate: (snapshot) => {
        snapshot.events[0].sessionId = "sentinel-wrong-session";
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.EVENT_IDENTITY_MISMATCH,
    },
    {
      mutate: (snapshot) => {
        snapshot.session.status = "created";
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.HEAD_STATUS_MISMATCH,
    },
    {
      mutate: (snapshot) => {
        snapshot.session.planGeneration = 2;
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.HEAD_GENERATION_MISMATCH,
    },
    {
      mutate: (snapshot) => {
        snapshot.session.stateVersion = 9;
      },
      code: AGENT_SESSION_OBSERVATION_ERRORS.STATE_VERSION_MISMATCH,
    },
  ];

  for (const { mutate, code } of cases) {
    const snapshot = snapshotFrom(HISTORIES.planning);
    mutate(snapshot);
    expectStableError(() => deriveAgentSessionObservation(snapshot, OBSERVED_AT), code);
  }
});

test("same-status events cannot advance state version", () => {
  const snapshot = snapshotFrom(HISTORIES.ready_to_run);
  snapshot.events[3].stateVersion = 4;
  expectStableError(
    () => deriveAgentSessionObservation(snapshot, OBSERVED_AT),
    AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATE_VERSION_INVALID
  );

  const replan = snapshotFrom([
    spec("agent.session_created", null, "created", 1, 0, "00:00"),
    spec("agent.plan_requested", "created", "planning", 2, 1, "00:01"),
    spec("agent.plan_rejected", "planning", "plan_failed", 3, 1, "00:02"),
    spec("agent.replan_requested", "plan_failed", "planning", 4, 2, "00:03"),
  ]);
  replan.events[3].stateVersion = 3;
  expectStableError(
    () => deriveAgentSessionObservation(replan, OBSERVED_AT),
    AGENT_SESSION_OBSERVATION_ERRORS.EVENT_STATE_VERSION_INVALID
  );
});

test("invalid observation epochs fail closed", () => {
  expectStableError(
    () => deriveAgentSessionObservation(snapshotFrom(HISTORIES.created), Number.NaN),
    AGENT_SESSION_OBSERVATION_ERRORS.OBSERVED_AT_INVALID
  );
});

test("observation is immutable, redacted, and excludes event content identities", () => {
  const snapshot = snapshotFrom(HISTORIES.awaiting_approval);
  const sentinel = "sentinel://private/path?credential=raw-model-output";
  snapshot.events.at(-1)!.payload = { rawModelOutput: sentinel };
  snapshot.events.at(-1)!.actor = sentinel;
  snapshot.events.at(-1)!.requestId = sentinel;
  snapshot.events.at(-1)!.idempotencyKey = sentinel;
  const before = JSON.stringify(snapshot);

  const observation = deriveAgentSessionObservation(snapshot, OBSERVED_AT);
  const serialized = JSON.stringify(observation);

  expect(JSON.stringify(snapshot)).toBe(before);
  expect(serialized).not.toContain(sentinel);
  for (const forbiddenKey of [
    "payload",
    "actor",
    "requestId",
    "idempotencyKey",
    "path",
    "uri",
    "rawModelOutput",
    "credential",
  ]) {
    expect(serialized).not.toContain(`"${forbiddenKey}":`);
  }
  expect(observation.integrity).toEqual({
    runnerFullChain: "required_by_snapshot_endpoint",
    browserSequence: "verified",
    browserPrevHashLinks: "verified",
    browserEventHash: "not_verifiable_command_hash_redacted",
  });
  expect(Object.values(observation.redactionPolicy)).toEqual([
    false,
    false,
    false,
    false,
    false,
    false,
    false,
  ]);
});

function spec(
  eventType: string,
  fromStatus: AgentSessionStatus | null,
  toStatus: AgentSessionStatus,
  stateVersion: number,
  planGeneration: number,
  time: string
): EventSpec {
  return {
    eventType,
    fromStatus,
    toStatus,
    stateVersion,
    planGeneration,
    createdAt: time.includes("T") ? time : `2026-07-18T${time}:00Z`,
  };
}

function snapshotFrom(
  specs: EventSpec[],
  sessionOverrides: Partial<AgentSession> = {}
): AgentSessionSnapshot {
  const events = specs.map((item, index): AgentEvent => {
    const sequence = index + 1;
    return {
      schemaVersion: "agent-event.v1",
      eventId: `agev_observation_${sequence}`,
      sessionId: SESSION_ID,
      sequence,
      eventType: item.eventType,
      fromStatus: item.fromStatus,
      toStatus: item.toStatus,
      stateVersion: item.stateVersion,
      planGeneration: item.planGeneration,
      requestId: `request-observation-${sequence}`,
      correlationId: null,
      idempotencyKey: `idempotency-observation-${sequence}`,
      actor: "fixture.observation.v1",
      payload: { ignored: `payload-${sequence}` },
      payloadHash: `payload-hash-${sequence}`,
      eventHash: `event-hash-${sequence}`,
      prevEventHash: sequence === 1 ? null : `event-hash-${sequence - 1}`,
      createdAt: item.createdAt,
    };
  });
  const head = events.at(-1)!;
  const session: AgentSession = {
    contractVersion: "agent-session.v1",
    sessionId: SESSION_ID,
    projectId: "project-observation",
    goal: {
      summary: "Observe a durable Agent session",
      successCriteria: ["Expose no sensitive event content"],
      context: {},
    },
    constraints: {
      allowedToolRevisionIds: [],
      forbiddenActions: [],
      requirements: {},
    },
    budget: { ...DEFAULT_BUDGET },
    status: head.toStatus,
    stateVersion: Math.max(...events.map((event) => event.stateVersion)),
    planGeneration: head.planGeneration,
    activeDraftId: null,
    activeDraftRevision: null,
    activePlanHash: null,
    workflowRevisionId: null,
    planner: {
      adapterId: "fixture.observation.v1",
      adapterVersion: "1",
      modelRef: null,
    },
    lastErrorCode: "",
    creationRequestId: "create-observation",
    createdBy: "fixture-principal",
    createdAt: events[0].createdAt,
    updatedAt: head.createdAt,
    cancelledAt: head.toStatus === "cancelled" ? head.createdAt : null,
    ...sessionOverrides,
  };
  return {
    contractVersion: "agent-session-snapshot.v1",
    session,
    events,
    plans: [],
    approvals: [],
  };
}

function expectStableError(action: () => unknown, code: string): void {
  let caught: unknown;
  try {
    action();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(Error);
  expect((caught as Error).message).toBe(code);
  expect((caught as Error).message).toMatch(/^AGENT_SESSION_OBSERVATION_[A-Z0-9_]+$/);
  expect((caught as Error).message).not.toContain("sentinel");
}
