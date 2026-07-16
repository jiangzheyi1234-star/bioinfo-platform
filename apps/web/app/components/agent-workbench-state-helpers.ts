import { LocalApiError } from "@/app/lib/local-api-client";

import type {
  AgentCommandInput,
  DecideAgentPlanInput,
} from "./agent-workbench-api";
import type {
  AgentSession,
  AgentSessionSnapshot,
  AgentWorkbenchProblem,
} from "./agent-workbench-model";
import { agentJsonEqual } from "./agent-workbench-integrity";

const SNAPSHOT_IMMUTABLE_CONFLICT = "AGENT_SESSION_SNAPSHOT_IMMUTABLE_CONFLICT";
const SNAPSHOT_INCONSISTENT = "AGENT_SESSION_SNAPSHOT_INCONSISTENT";

export function newCommandIntent(
  serverId: string,
  sessionId: string,
  expectedStateVersion: number,
  action: string
): AgentCommandInput {
  const requestId = uniqueCommandId(`agent-${action}`);
  return {
    serverId,
    sessionId,
    expectedStateVersion,
    requestId,
    idempotencyKey: requestId,
  };
}

export function sameIdentity(
  left: { serverId: string; sessionId: string },
  right: { serverId: string; sessionId: string }
): boolean {
  return left.serverId === right.serverId && left.sessionId === right.sessionId;
}

export function uniqueCommandId(prefix: string): string {
  const uuid =
    globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${uuid}`;
}

export function upsertSession(items: AgentSession[], next: AgentSession): AgentSession[] {
  const existing = items.find((candidate) => candidate.sessionId === next.sessionId);
  const selected = existing ? newerAgentSession(existing, next) : next;
  return [selected, ...items.filter((candidate) => candidate.sessionId !== next.sessionId)];
}

export function mergeAgentSessionLists(
  current: AgentSession[],
  incoming: AgentSession[]
): AgentSession[] {
  const merged = new Map(current.map((session) => [session.sessionId, session]));
  incoming.forEach((session) => {
    const existing = merged.get(session.sessionId);
    merged.set(session.sessionId, existing ? newerAgentSession(existing, session) : session);
  });
  return Array.from(merged.values());
}

export function mergeAgentSnapshots(
  current: AgentSessionSnapshot | null,
  next: AgentSessionSnapshot
): AgentSessionSnapshot {
  assertAgentSnapshotConsistent(next);
  if (!current || current.session.sessionId !== next.session.sessionId) return next;

  assertAgentSnapshotConsistent(current);
  assertImmutableSnapshotHistory(current, next);
  assertImmutableEquivalent(agentSessionLineage(current.session), agentSessionLineage(next.session));
  if (current.session.stateVersion === next.session.stateVersion) {
    assertImmutableEquivalent(
      agentSessionProjection(current.session),
      agentSessionProjection(next.session)
    );
    if (snapshotHistoryContains(next, current)) return next;
    if (snapshotHistoryContains(current, next)) return current;
    throw new Error(SNAPSHOT_INCONSISTENT);
  }
  if (next.session.stateVersion > current.session.stateVersion) {
    assertSnapshotHistoryContains(next, current);
    return next;
  }
  assertSnapshotHistoryContains(current, next);
  return current;
}

export function isUncertainCommandFailure(error: unknown): boolean {
  if (!(error instanceof LocalApiError)) return true;
  return (
    error.code === "backend_timeout" ||
    error.code === "backend_unreachable" ||
    error.status === 0 ||
    error.status >= 500
  );
}

export function approvalStillNeedsReplay(
  snapshot: AgentSessionSnapshot,
  command: DecideAgentPlanInput
): boolean {
  const recorded = snapshot.approvals.some(
    (approval) =>
      approval.requestId === command.requestId &&
      approval.idempotencyKey === command.idempotencyKey &&
      approval.planHash === command.expectedPlanHash &&
      approval.decision === command.decision
  );
  return (
    recorded &&
    snapshot.session.status === "awaiting_approval" &&
    snapshot.session.stateVersion === command.expectedStateVersion &&
    snapshot.session.activePlanHash === command.expectedPlanHash
  );
}

export function agentProblem(error: unknown, fallback: string): AgentWorkbenchProblem {
  if (error instanceof LocalApiError) {
    return {
      message: error.message || fallback,
      ...(error.status ? { status: error.status } : {}),
      ...(error.problemCode || error.code ? { code: error.problemCode || error.code } : {}),
      ...(error.reasonCode ? { reasonCode: error.reasonCode } : {}),
      ...(error.nextAction ? { nextAction: error.nextAction } : {}),
    };
  }
  const message = error instanceof Error ? error.message.trim() : String(error || "").trim();
  return {
    message: message || fallback,
    ...(message && /^[A-Z][A-Z0-9_.:-]+$/.test(message) ? { code: message } : {}),
  };
}

function newerAgentSession(left: AgentSession, right: AgentSession): AgentSession {
  assertImmutableEquivalent(agentSessionLineage(left), agentSessionLineage(right));
  if (right.stateVersion !== left.stateVersion) {
    return right.stateVersion > left.stateVersion ? right : left;
  }
  assertImmutableEquivalent(agentSessionProjection(left), agentSessionProjection(right));
  return right;
}

function agentSessionProjection(session: AgentSession): unknown {
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

function assertAgentSnapshotConsistent(snapshot: AgentSessionSnapshot): void {
  const { session } = snapshot;
  assertUniqueScopedItems(snapshot.events, session.sessionId, (item) => item.eventId);
  assertUniqueScopedItems(snapshot.plans, session.sessionId, (item) => item.planRevisionId);
  assertUniqueScopedItems(snapshot.approvals, session.sessionId, (item) => item.approvalId);

  if (
    snapshot.events.some(
      (event) =>
        event.stateVersion > session.stateVersion ||
        event.planGeneration > session.planGeneration
    ) ||
    snapshot.plans.some((plan) => plan.planGeneration > session.planGeneration) ||
    snapshot.approvals.some(
      (approval) =>
        approval.expectedStateVersion > session.stateVersion ||
        approval.planGeneration > session.planGeneration
    )
  ) {
    throw new Error(SNAPSHOT_INCONSISTENT);
  }

  const plansByGeneration = new Set<number>();
  snapshot.plans.forEach((plan) => {
    if (plansByGeneration.has(plan.planGeneration)) {
      throw new Error(SNAPSHOT_INCONSISTENT);
    }
    plansByGeneration.add(plan.planGeneration);
  });

  const activeFields = [
    session.activePlanHash,
    session.activeDraftId,
    session.activeDraftRevision,
  ];
  const hasActivePlan = activeFields.every((value) => value !== null && value !== undefined);
  const hasPartialActivePlan = activeFields.some(
    (value) => value !== null && value !== undefined
  );
  if (hasPartialActivePlan && !hasActivePlan) throw new Error(SNAPSHOT_INCONSISTENT);

  const currentGenerationPlans = snapshot.plans.filter(
    (plan) => plan.planGeneration === session.planGeneration
  );
  if (!hasActivePlan) {
    const activeRequired = [
      "awaiting_approval",
      "plan_failed",
      "changes_requested",
      "ready_to_run",
    ].includes(session.status);
    if (activeRequired || (session.status === "created" && currentGenerationPlans.length)) {
      throw new Error(SNAPSHOT_INCONSISTENT);
    }
    return;
  }
  if (
    currentGenerationPlans.length !== 1 ||
    currentGenerationPlans[0].planHash !== session.activePlanHash ||
    currentGenerationPlans[0].draftId !== session.activeDraftId ||
    currentGenerationPlans[0].draftRevision !== session.activeDraftRevision
  ) {
    throw new Error(SNAPSHOT_INCONSISTENT);
  }
}

function assertUniqueScopedItems<T extends { sessionId: string }>(
  items: T[],
  sessionId: string,
  identity: (item: T) => string
): void {
  const identities = new Set<string>();
  items.forEach((item) => {
    const itemId = identity(item);
    if (item.sessionId !== sessionId || identities.has(itemId)) {
      throw new Error(SNAPSHOT_INCONSISTENT);
    }
    identities.add(itemId);
  });
}

function assertImmutableSnapshotHistory(
  left: AgentSessionSnapshot,
  right: AgentSessionSnapshot
): void {
  assertSharedImmutableItems(left.events, right.events, (item) => item.eventId);
  assertSharedImmutableItems(left.plans, right.plans, (item) => item.planRevisionId);
  assertSharedImmutableItems(left.approvals, right.approvals, (item) => item.approvalId);
}

function assertSharedImmutableItems<T>(
  left: T[],
  right: T[],
  identity: (item: T) => string
): void {
  const leftById = new Map(left.map((item) => [identity(item), item]));
  right.forEach((item) => {
    const existing = leftById.get(identity(item));
    if (existing && !agentJsonEqual(existing, item)) {
      throw new Error(SNAPSHOT_IMMUTABLE_CONFLICT);
    }
  });
}

function assertSnapshotHistoryContains(
  container: AgentSessionSnapshot,
  expected: AgentSessionSnapshot
): void {
  if (!snapshotHistoryContains(container, expected)) throw new Error(SNAPSHOT_INCONSISTENT);
}

function snapshotHistoryContains(
  container: AgentSessionSnapshot,
  expected: AgentSessionSnapshot
): boolean {
  return (
    itemIdentitiesContain(container.events, expected.events, (item) => item.eventId) &&
    itemIdentitiesContain(container.plans, expected.plans, (item) => item.planRevisionId) &&
    itemIdentitiesContain(container.approvals, expected.approvals, (item) => item.approvalId)
  );
}

function itemIdentitiesContain<T>(
  container: T[],
  expected: T[],
  identity: (item: T) => string
): boolean {
  const identities = new Set(container.map(identity));
  return expected.every((item) => identities.has(identity(item)));
}

function assertImmutableEquivalent(left: unknown, right: unknown): void {
  if (!agentJsonEqual(left, right)) throw new Error(SNAPSHOT_IMMUTABLE_CONFLICT);
}
