import { expect, test } from "@playwright/test";

import { assertAgentApprovalDurableProof } from "../../apps/web/app/components/agent-workbench-durable-proof";
import type {
  AgentApproval,
  AgentApprovalResult,
  AgentEvent,
  AgentPlanRevision,
  AgentSession,
  AgentSessionSnapshot,
} from "../../apps/web/app/components/agent-workbench-model";

const SESSION_ID = "ags_durable_proof";
const PLAN_ID = "agp_durable_proof";
const APPROVAL_ID = "aga_durable_proof";
const REQUEST_ID = "approve-durable-proof";
const WORKFLOW_REVISION_ID = "wfr_durable_proof";
const CREATED_AT = "2026-07-16T00:00:00Z";

function session(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    contractVersion: "agent-session.v1",
    sessionId: SESSION_ID,
    projectId: "project-durable-proof",
    goal: {
      summary: "Run deterministic FASTQ QC",
      successCriteria: ["Produce a MultiQC report"],
      context: { sample: "reads.fastq" },
    },
    constraints: {
      allowedToolRevisionIds: [],
      forbiddenActions: [],
      requirements: {},
    },
    budget: {
      maxModelTurns: 1,
      maxToolCalls: 2,
      maxReplans: 1,
      maxRetries: 0,
      maxWallClockSeconds: 900,
    },
    status: "ready_to_run",
    stateVersion: 4,
    planGeneration: 1,
    activeDraftId: "wfd_durable_proof",
    activeDraftRevision: 1,
    activePlanHash: "a".repeat(64),
    workflowRevisionId: WORKFLOW_REVISION_ID,
    planner: {
      adapterId: "fastq-qc",
      adapterVersion: "1",
      modelRef: null,
    },
    lastErrorCode: "",
    creationRequestId: "create-durable-proof",
    createdBy: "runner-principal",
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
    cancelledAt: null,
    ...overrides,
  };
}

function plan(overrides: Partial<AgentPlanRevision> = {}): AgentPlanRevision {
  return {
    contractVersion: "agent-plan-revision.v1",
    planRevisionId: PLAN_ID,
    sessionId: SESSION_ID,
    planGeneration: 1,
    parentPlanRevisionId: null,
    draftId: "wfd_durable_proof",
    draftRevision: 1,
    planHash: "a".repeat(64),
    canonicalPayload: "{\"bound\":true}",
    proposal: {} as AgentPlanRevision["proposal"],
    validation: {} as AgentPlanRevision["validation"],
    budget: session().budget,
    createdBy: "runner-principal",
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function approval(overrides: Partial<AgentApproval> = {}): AgentApproval {
  return {
    contractVersion: "agent-approval.v1",
    approvalId: APPROVAL_ID,
    sessionId: SESSION_ID,
    planRevisionId: PLAN_ID,
    planGeneration: 1,
    planHash: "a".repeat(64),
    expectedStateVersion: 3,
    decision: "approve",
    scope: "compile_workflow_revision",
    actor: "runner-principal",
    reason: null,
    requestId: REQUEST_ID,
    idempotencyKey: REQUEST_ID,
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function outcomeEvent(
  approvalValue: AgentApproval,
  sessionValue: AgentSession,
  overrides: Partial<AgentEvent> = {}
): AgentEvent {
  const approved = approvalValue.decision === "approve";
  return {
    schemaVersion: "agent-event.v1",
    eventId: `event-${approved ? "compiled" : "changes"}`,
    sessionId: SESSION_ID,
    sequence: 5,
    eventType: approved
      ? "agent.workflow_revision_compiled"
      : "agent.changes_requested",
    fromStatus: "awaiting_approval",
    toStatus: approved ? "ready_to_run" : "changes_requested",
    stateVersion: sessionValue.stateVersion,
    planGeneration: approvalValue.planGeneration,
    requestId: approvalValue.requestId,
    correlationId: approved ? approvalValue.requestId : null,
    idempotencyKey: `${approved ? "compile" : "apply"}:${approvalValue.idempotencyKey}`,
    actor: approvalValue.actor,
    payload: {
      approvalId: approvalValue.approvalId,
      planRevisionId: approvalValue.planRevisionId,
      ...(approved
        ? { workflowRevisionId: sessionValue.workflowRevisionId }
        : { reason: approvalValue.reason ?? null }),
    },
    payloadHash: "b".repeat(64),
    eventHash: "c".repeat(64),
    prevEventHash: "d".repeat(64),
    createdAt: CREATED_AT,
    ...overrides,
  };
}

function fixture(
  decision: AgentApproval["decision"] = "approve"
): { result: AgentApprovalResult; snapshot: AgentSessionSnapshot } {
  const sessionValue = session(
    decision === "request_changes"
      ? { status: "changes_requested", workflowRevisionId: null }
      : {}
  );
  const planValue = plan();
  const approvalValue = approval({
    decision,
    ...(decision === "request_changes" ? { reason: "Use a different input" } : {}),
  });
  const result: AgentApprovalResult = {
    session: sessionValue,
    plan: planValue,
    approval: approvalValue,
    compiled:
      decision === "approve"
        ? { workflowRevisionId: WORKFLOW_REVISION_ID }
        : null,
  };
  return {
    result,
    snapshot: {
      contractVersion: "agent-session-snapshot.v1",
      session: sessionValue,
      events: [outcomeEvent(approvalValue, sessionValue)],
      plans: [planValue],
      approvals: [approvalValue],
    },
  };
}

test("known nullable omissions do not break an exact durable approval proof", () => {
  const { result, snapshot } = fixture();
  const durableSession = { ...snapshot.session };
  delete durableSession.cancelledAt;
  durableSession.planner = {
    adapterId: durableSession.planner.adapterId,
    adapterVersion: durableSession.planner.adapterVersion,
  };
  const durablePlan = { ...snapshot.plans[0] };
  delete durablePlan.parentPlanRevisionId;
  const durableApproval = { ...snapshot.approvals[0] };
  delete durableApproval.reason;

  expect(() =>
    assertAgentApprovalDurableProof(
      {
        ...snapshot,
        session: durableSession,
        plans: [durablePlan],
        approvals: [durableApproval],
      },
      result
    )
  ).not.toThrow();
});

test("request-changes durable proof requires its exact outcome event", () => {
  const { result, snapshot } = fixture("request_changes");
  expect(() => assertAgentApprovalDurableProof(snapshot, result)).not.toThrow();

  const altered = {
    ...snapshot,
    events: [{ ...snapshot.events[0], payload: { ...snapshot.events[0].payload, reason: "other" } }],
  };
  expect(() => assertAgentApprovalDurableProof(altered, result)).toThrow(
    "AGENT_SESSION_APPROVAL_DURABLE_PROOF_MISMATCH"
  );
});

test("a newer replan projection still proves the original compiled approval", () => {
  const { result, snapshot } = fixture();
  const descendant = session({
    status: "awaiting_approval",
    stateVersion: 7,
    planGeneration: 2,
    activeDraftId: "wfd_descendant",
    activeDraftRevision: 2,
    activePlanHash: "e".repeat(64),
    workflowRevisionId: null,
    planner: { adapterId: "fastq-qc", adapterVersion: "2", modelRef: null },
    updatedAt: "2026-07-16T00:01:00Z",
  });

  expect(() =>
    assertAgentApprovalDurableProof({ ...snapshot, session: descendant }, result)
  ).not.toThrow();
});

test("older projections, changed lineage, and altered outcome identity fail closed", () => {
  const { result, snapshot } = fixture();
  const variants: AgentSessionSnapshot[] = [
    { ...snapshot, session: session({ stateVersion: 3 }) },
    {
      ...snapshot,
      session: session({
        stateVersion: 5,
        goal: { ...snapshot.session.goal, summary: "Changed goal" },
      }),
    },
    {
      ...snapshot,
      events: [
        {
          ...snapshot.events[0],
          payload: { ...snapshot.events[0].payload, approvalId: "aga_other" },
        },
      ],
    },
  ];

  for (const variant of variants) {
    expect(() => assertAgentApprovalDurableProof(variant, result)).toThrow(
      "AGENT_SESSION_APPROVAL_DURABLE_PROOF_MISMATCH"
    );
  }
});
