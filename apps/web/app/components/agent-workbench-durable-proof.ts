import type {
  AgentApproval,
  AgentApprovalResult,
  AgentPlanRevision,
  AgentSession,
  AgentSessionSnapshot,
} from "./agent-workbench-model";
import { agentJsonEqual } from "./agent-workbench-integrity";

const DURABLE_PROOF_MISMATCH = "AGENT_SESSION_APPROVAL_DURABLE_PROOF_MISMATCH";

export function assertAgentApprovalDurableProof(
  snapshot: AgentSessionSnapshot,
  result: AgentApprovalResult
): void {
  const approvals = snapshot.approvals.filter(
    (approval) => approval.approvalId === result.approval.approvalId
  );
  const plan = snapshot.plans.find(
    (candidate) => candidate.planRevisionId === result.plan.planRevisionId
  );
  if (
    approvals.length !== 1 ||
    !plan ||
    !agentJsonEqual(agentApprovalProof(approvals[0]), agentApprovalProof(result.approval)) ||
    !agentJsonEqual(agentPlanProof(plan), agentPlanProof(result.plan))
  ) {
    mismatch();
  }
  assertApprovalOutcomeEvent(snapshot, result);

  const durable = snapshot.session;
  const response = result.session;
  if (durable.stateVersion < response.stateVersion) mismatch();
  if (durable.stateVersion === response.stateVersion) {
    if (!agentJsonEqual(agentSessionProof(durable), agentSessionProof(response))) mismatch();
    return;
  }

  if (
    !agentJsonEqual(agentSessionLineage(durable), agentSessionLineage(response)) ||
    durable.planGeneration < response.planGeneration
  ) {
    mismatch();
  }
  if (
    durable.planGeneration === response.planGeneration &&
    (!agentJsonEqual(durable.planner, response.planner) ||
      !sameNullable(durable.activeDraftId, response.activeDraftId) ||
      !sameNullable(durable.activeDraftRevision, response.activeDraftRevision) ||
      !sameNullable(durable.activePlanHash, response.activePlanHash))
  ) {
    mismatch();
  }
}

function assertApprovalOutcomeEvent(
  snapshot: AgentSessionSnapshot,
  result: AgentApprovalResult
): void {
  const { approval, plan, session } = result;
  const approved = approval.decision === "approve";
  const eventType = approved
    ? "agent.workflow_revision_compiled"
    : "agent.changes_requested";
  const expectedIdempotencyKey = `${approved ? "compile" : "apply"}:${approval.idempotencyKey}`;
  const matches = snapshot.events.filter(
    (event) =>
      event.eventType === eventType &&
      event.sessionId === session.sessionId &&
      event.requestId === approval.requestId &&
      event.idempotencyKey === expectedIdempotencyKey &&
      event.stateVersion === session.stateVersion &&
      event.planGeneration === approval.planGeneration &&
      event.actor === approval.actor &&
      event.payload.approvalId === approval.approvalId &&
      event.payload.planRevisionId === plan.planRevisionId &&
      event.toStatus === (approved ? "ready_to_run" : "changes_requested")
  );
  if (matches.length !== 1) mismatch();
  const payload = matches[0].payload;
  if (approved) {
    if (
      !session.workflowRevisionId ||
      payload.workflowRevisionId !== session.workflowRevisionId ||
      matches[0].correlationId !== approval.requestId
    ) {
      mismatch();
    }
  } else if ((payload.reason ?? null) !== (approval.reason ?? null)) {
    mismatch();
  }
}

function agentApprovalProof(approval: AgentApproval): unknown {
  return {
    contractVersion: approval.contractVersion,
    approvalId: approval.approvalId,
    sessionId: approval.sessionId,
    planRevisionId: approval.planRevisionId,
    planGeneration: approval.planGeneration,
    planHash: approval.planHash,
    expectedStateVersion: approval.expectedStateVersion,
    decision: approval.decision,
    scope: approval.scope,
    actor: approval.actor,
    reason: approval.reason ?? null,
    requestId: approval.requestId,
    idempotencyKey: approval.idempotencyKey,
    createdAt: approval.createdAt,
  };
}

function agentPlanProof(plan: AgentPlanRevision): unknown {
  return {
    contractVersion: plan.contractVersion,
    planRevisionId: plan.planRevisionId,
    sessionId: plan.sessionId,
    planGeneration: plan.planGeneration,
    parentPlanRevisionId: plan.parentPlanRevisionId ?? null,
    draftId: plan.draftId,
    draftRevision: plan.draftRevision,
    planHash: plan.planHash,
    canonicalPayload: plan.canonicalPayload,
    createdBy: plan.createdBy,
    createdAt: plan.createdAt,
  };
}

function agentSessionProof(session: AgentSession): unknown {
  return {
    ...agentSessionLineage(session),
    status: session.status,
    stateVersion: session.stateVersion,
    planGeneration: session.planGeneration,
    activeDraftId: session.activeDraftId ?? null,
    activeDraftRevision: session.activeDraftRevision ?? null,
    activePlanHash: session.activePlanHash ?? null,
    workflowRevisionId: session.workflowRevisionId ?? null,
    planner: {
      adapterId: session.planner.adapterId ?? null,
      adapterVersion: session.planner.adapterVersion ?? null,
      modelRef: session.planner.modelRef ?? null,
    },
    lastErrorCode: session.lastErrorCode,
    updatedAt: session.updatedAt,
    cancelledAt: session.cancelledAt ?? null,
  };
}

function agentSessionLineage(session: AgentSession): Record<string, unknown> {
  return {
    contractVersion: session.contractVersion,
    sessionId: session.sessionId,
    projectId: session.projectId,
    goal: session.goal,
    constraints: session.constraints,
    budget: session.budget,
    creationRequestId: session.creationRequestId,
    createdBy: session.createdBy,
    createdAt: session.createdAt,
  };
}

function sameNullable(left: unknown, right: unknown): boolean {
  return (left ?? null) === (right ?? null);
}

function mismatch(): never {
  throw new Error(DURABLE_PROOF_MISMATCH);
}
