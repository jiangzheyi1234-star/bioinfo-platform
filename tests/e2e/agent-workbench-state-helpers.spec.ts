import { expect, test } from "@playwright/test";

import type {
  AgentApproval,
  AgentBudget,
  AgentEvent,
  AgentPlanRevision,
  AgentSession,
  AgentSessionSnapshot,
  AgentSessionStatus,
} from "../../apps/web/app/components/agent-workbench-model";

type MergeAgentSnapshots = (
  current: AgentSessionSnapshot | null,
  next: AgentSessionSnapshot
) => AgentSessionSnapshot;

const { mergeAgentSnapshots } = require(
  "../../apps/web/app/components/agent-workbench-state-helpers"
) as { mergeAgentSnapshots: MergeAgentSnapshots };

const IMMUTABLE_CONFLICT = "AGENT_SESSION_SNAPSHOT_IMMUTABLE_CONFLICT";
const INCONSISTENT = "AGENT_SESSION_SNAPSHOT_INCONSISTENT";
const SESSION_ID = "ags_state_helper_fixture";
const CREATED_AT = "2026-07-16T00:00:00Z";

const BUDGET: AgentBudget = {
  maxModelTurns: 1,
  maxToolCalls: 2,
  maxReplans: 1,
  maxRetries: 0,
  maxWallClockSeconds: 900,
};

function agentSession(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    contractVersion: "agent-session.v1",
    sessionId: SESSION_ID,
    projectId: "project-state-helper",
    goal: {
      summary: "Run deterministic FASTQ QC",
      successCriteria: ["Produce a MultiQC report"],
      context: {},
    },
    constraints: {
      allowedToolRevisionIds: [],
      forbiddenActions: [],
      requirements: {},
    },
    budget: { ...BUDGET },
    status: "planning",
    stateVersion: 2,
    planGeneration: 1,
    activeDraftId: null,
    activeDraftRevision: null,
    activePlanHash: null,
    workflowRevisionId: null,
    planner: {
      adapterId: "fastq-qc",
      adapterVersion: "1",
      modelRef: null,
    },
    lastErrorCode: "",
    creationRequestId: "create-state-helper",
    createdBy: "runner-principal",
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
    cancelledAt: null,
    ...overrides,
  };
}

function planRevision(overrides: Partial<AgentPlanRevision> = {}): AgentPlanRevision {
  return {
    contractVersion: "agent-plan-revision.v1",
    planRevisionId: "plan-state-helper-1",
    sessionId: SESSION_ID,
    planGeneration: 1,
    parentPlanRevisionId: null,
    draftId: "draft-state-helper-1",
    draftRevision: 1,
    planHash: "a".repeat(64),
    canonicalPayload: "{}",
    proposal: {
      draft: {
        contractVersion: "workflow-design-draft-v1",
        engine: "snakemake",
        metadata: {
          name: "FASTQ QC",
          description: "Fixture plan",
          projectId: "project-state-helper",
          tags: [],
        },
        inputs: [],
        nodes: [],
        edges: [],
        resources: { bindings: {}, metadata: {} },
        outputs: [],
        provenance: {},
      },
      planner: {
        adapterId: "fastq-qc",
        adapterVersion: "1",
        modelRef: "deterministic",
      },
    },
    validation: {
      valid: true,
      orderedSteps: [],
      exposedOutputs: {},
      requiredResources: {},
      requiredDatabases: {},
      validationIssues: [],
    },
    budget: { ...BUDGET },
    createdBy: "runner-principal",
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function approval(overrides: Partial<AgentApproval> = {}): AgentApproval {
  return {
    contractVersion: "agent-approval.v1",
    approvalId: "approval-state-helper-1",
    sessionId: SESSION_ID,
    planRevisionId: "plan-state-helper-1",
    planGeneration: 1,
    planHash: "a".repeat(64),
    expectedStateVersion: 3,
    decision: "approve",
    scope: "compile_workflow_revision",
    actor: "runner-principal",
    reason: null,
    requestId: "approve-state-helper-1",
    idempotencyKey: "approve-state-helper-1",
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function event(eventId: string, overrides: Partial<AgentEvent> = {}): AgentEvent {
  return {
    schemaVersion: "agent-event.v1",
    eventId,
    sessionId: SESSION_ID,
    sequence: 1,
    eventType: "agent.plan_requested",
    fromStatus: "created",
    toStatus: "planning",
    stateVersion: 2,
    planGeneration: 1,
    requestId: `request-${eventId}`,
    correlationId: null,
    idempotencyKey: `request-${eventId}`,
    actor: "runner-principal",
    payload: {},
    payloadHash: "b".repeat(64),
    eventHash: "c".repeat(64),
    prevEventHash: null,
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function snapshot(
  session: AgentSession,
  history: {
    events?: AgentEvent[];
    plans?: AgentPlanRevision[];
    approvals?: AgentApproval[];
  } = {}
): AgentSessionSnapshot {
  return {
    contractVersion: "agent-session-snapshot.v1",
    session,
    events: history.events ?? [],
    plans: history.plans ?? [],
    approvals: history.approvals ?? [],
  };
}

function expectMergeError(
  current: AgentSessionSnapshot | null,
  next: AgentSessionSnapshot,
  code: string
): void {
  expect(() => mergeAgentSnapshots(current, next)).toThrow(code);
}

test("same-version planning snapshots select a newly observed inactive current-generation plan", () => {
  const session = agentSession();
  const withoutPlan = snapshot(session);
  const withPlan = snapshot(agentSession(), { plans: [planRevision()] });

  expect(mergeAgentSnapshots(withoutPlan, withPlan)).toBe(withPlan);
  expect(mergeAgentSnapshots(withPlan, withoutPlan)).toBe(withPlan);
});

test("same-version awaiting-approval snapshots select monotonically added approvals", () => {
  const awaitingApproval = {
    status: "awaiting_approval" as const,
    stateVersion: 3,
    activeDraftId: "draft-state-helper-1",
    activeDraftRevision: 1,
    activePlanHash: "a".repeat(64),
  };
  const current = snapshot(agentSession(awaitingApproval), { plans: [planRevision()] });
  const next = snapshot(agentSession(awaitingApproval), {
    plans: [planRevision()],
    approvals: [approval()],
  });

  expect(mergeAgentSnapshots(current, next)).toBe(next);
});

test("shared history IDs are immutable", () => {
  const original = snapshot(agentSession(), {
    events: [event("event-shared")],
  });
  const mutated = snapshot(agentSession(), {
    events: [event("event-shared", { payload: { changed: true } })],
  });

  expectMergeError(original, mutated, IMMUTABLE_CONFLICT);
});

test("same-version snapshots cannot each introduce independent history", () => {
  const left = snapshot(agentSession(), { events: [event("event-left")] });
  const right = snapshot(agentSession(), { events: [event("event-right")] });

  expectMergeError(left, right, INCONSISTENT);
});

test("same-version sessions treat only known optional nulls and omissions as equivalent", () => {
  const explicitNulls = agentSession();
  const omitted = { ...agentSession() };
  delete omitted.activeDraftId;
  delete omitted.activeDraftRevision;
  delete omitted.activePlanHash;
  delete omitted.workflowRevisionId;
  delete omitted.cancelledAt;
  omitted.planner = {
    adapterId: omitted.planner.adapterId,
    adapterVersion: omitted.planner.adapterVersion,
  };

  const current = snapshot(explicitNulls);
  const next = snapshot(omitted);
  expect(mergeAgentSnapshots(current, next)).toBe(next);
});

test("same-version sessions preserve null versus omission inside arbitrary goal context", () => {
  const current = snapshot(
    agentSession({ goal: { ...agentSession().goal, context: { sample: null } } })
  );
  const next = snapshot(
    agentSession({ goal: { ...agentSession().goal, context: {} } })
  );

  expectMergeError(current, next, IMMUTABLE_CONFLICT);
});

const lineageMutations: Array<[string, Partial<AgentSession>]> = [
  [
    "goal",
    {
      goal: {
        summary: "A different goal",
        successCriteria: ["Produce a MultiQC report"],
        context: {},
      },
    },
  ],
  ["budget", { budget: { ...BUDGET, maxToolCalls: BUDGET.maxToolCalls + 1 } }],
  ["creation request", { creationRequestId: "create-state-helper-mutated" }],
];

for (const [lineageName, mutation] of lineageMutations) {
  test(`cross-version snapshots reject changed ${lineageName} lineage`, () => {
    const current = snapshot(agentSession({ stateVersion: 1, planGeneration: 0 }));
    const next = snapshot(
      agentSession({
        stateVersion: 2,
        planGeneration: 0,
        ...mutation,
      })
    );

    expectMergeError(current, next, IMMUTABLE_CONFLICT);
  });
}

test("created snapshots reject current-generation plans without active-plan identity", () => {
  const invalid = snapshot(agentSession({ status: "created" }), {
    plans: [planRevision()],
  });

  expectMergeError(null, invalid, INCONSISTENT);
});

for (const status of ["planning", "cancelled"] satisfies AgentSessionStatus[]) {
  test(`${status} snapshots accept an inactive current-generation plan`, () => {
    const valid = snapshot(
      agentSession({
        status,
        ...(status === "cancelled" ? { cancelledAt: CREATED_AT } : {}),
      }),
      { plans: [planRevision()] }
    );

    expect(mergeAgentSnapshots(null, valid)).toBe(valid);
  });
}

test("plan-failed snapshots require an active-plan identity", () => {
  const invalid = snapshot(agentSession({ status: "plan_failed" }), {
    plans: [planRevision()],
  });

  expectMergeError(null, invalid, INCONSISTENT);
});
