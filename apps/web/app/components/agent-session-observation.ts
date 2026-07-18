import type {
  AgentSessionSnapshot,
  AgentSessionStatus,
} from "./agent-workbench-model";

export const AGENT_SESSION_OBSERVATION_ERRORS = Object.freeze({
  EVENTS_REQUIRED: "AGENT_SESSION_OBSERVATION_EVENTS_REQUIRED",
  EVENT_IDENTITY_MISMATCH: "AGENT_SESSION_OBSERVATION_EVENT_IDENTITY_MISMATCH",
  EVENT_SEQUENCE_INVALID: "AGENT_SESSION_OBSERVATION_EVENT_SEQUENCE_INVALID",
  EVENT_PREV_HASH_INVALID: "AGENT_SESSION_OBSERVATION_EVENT_PREV_HASH_INVALID",
  HEAD_STATUS_MISMATCH: "AGENT_SESSION_OBSERVATION_HEAD_STATUS_MISMATCH",
  HEAD_GENERATION_MISMATCH: "AGENT_SESSION_OBSERVATION_HEAD_GENERATION_MISMATCH",
  STATE_VERSION_MISMATCH: "AGENT_SESSION_OBSERVATION_STATE_VERSION_MISMATCH",
  STATE_ENTRY_REQUIRED: "AGENT_SESSION_OBSERVATION_STATE_ENTRY_REQUIRED",
  REPLAN_COUNT_MISMATCH: "AGENT_SESSION_OBSERVATION_REPLAN_COUNT_MISMATCH",
  REPLAN_BUDGET_EXCEEDED: "AGENT_SESSION_OBSERVATION_REPLAN_BUDGET_EXCEEDED",
  OBSERVED_AT_INVALID: "AGENT_SESSION_OBSERVATION_OBSERVED_AT_INVALID",
} as const);

export type AgentSessionObservationAttention =
  | "plan_not_started"
  | "planning_recovery_available"
  | "human_approval_required"
  | "plan_failed"
  | "typed_replan_required"
  | "run_authorization_pending"
  | "terminal";

export type AgentSessionObservationTimingStatus =
  | "client_estimate"
  | "invalid_timestamp"
  | "clock_regression";

export type AgentSessionObservationV1 = {
  contractVersion: "agent-session-observation.v1";
  source: {
    sessionId: string;
    stateVersion: number;
    planGeneration: number;
    clientObservedAt: string;
    headSequence: number;
    headEventHash: string;
    headEventAt: string;
  };
  lifecycle: {
    status: AgentSessionStatus;
    stateEnteredAt: string;
    stateAgeSeconds: number | null;
    timingStatus: AgentSessionObservationTimingStatus;
    attention: AgentSessionObservationAttention;
  };
  counters: {
    events: number;
    plans: number;
    approvals: number;
    replansUsed: number;
    replansRemaining: number;
    planFailures: number;
    changeRequests: number;
  };
  integrity: {
    runnerFullChain: "required_by_snapshot_endpoint";
    browserSequence: "verified";
    browserPrevHashLinks: "verified";
    browserEventHash: "not_verifiable_command_hash_redacted";
  };
  redactionPolicy: {
    eventPayloadsDisplayed: false;
    commandHashesExposed: false;
    requestIdentitiesDisplayed: false;
    actorsDisplayed: false;
    pathsOrUrisDisplayed: false;
    rawModelOutputDisplayed: false;
    credentialsDisplayed: false;
  };
};

const ATTENTION_BY_STATUS: Record<
  AgentSessionStatus,
  AgentSessionObservationAttention
> = {
  created: "plan_not_started",
  planning: "planning_recovery_available",
  awaiting_approval: "human_approval_required",
  plan_failed: "plan_failed",
  changes_requested: "typed_replan_required",
  ready_to_run: "run_authorization_pending",
  cancelled: "terminal",
};

const REDACTION_POLICY = Object.freeze({
  eventPayloadsDisplayed: false,
  commandHashesExposed: false,
  requestIdentitiesDisplayed: false,
  actorsDisplayed: false,
  pathsOrUrisDisplayed: false,
  rawModelOutputDisplayed: false,
  credentialsDisplayed: false,
} as const);

export function deriveAgentSessionObservation(
  snapshot: AgentSessionSnapshot,
  observedAtEpochMs: number
): AgentSessionObservationV1 {
  const events = snapshot.events;
  if (!events.length) fail(AGENT_SESSION_OBSERVATION_ERRORS.EVENTS_REQUIRED);

  const { session } = snapshot;
  let previousEventHash: string | null = null;
  let maximumStateVersion = 0;
  let replanEventCount = 0;
  let planFailures = 0;
  let changeRequests = 0;

  events.forEach((event, index) => {
    if (event.sessionId !== session.sessionId) {
      fail(AGENT_SESSION_OBSERVATION_ERRORS.EVENT_IDENTITY_MISMATCH);
    }
    if (event.sequence !== index + 1) {
      fail(AGENT_SESSION_OBSERVATION_ERRORS.EVENT_SEQUENCE_INVALID);
    }
    if ((event.prevEventHash ?? null) !== previousEventHash) {
      fail(AGENT_SESSION_OBSERVATION_ERRORS.EVENT_PREV_HASH_INVALID);
    }
    previousEventHash = event.eventHash;
    maximumStateVersion = Math.max(maximumStateVersion, event.stateVersion);
    if (event.eventType === "agent.replan_requested") replanEventCount += 1;
    if (event.eventType === "agent.plan_rejected") planFailures += 1;
    if (event.eventType === "agent.changes_requested") changeRequests += 1;
  });

  const head = events[events.length - 1];
  if (head.toStatus !== session.status) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.HEAD_STATUS_MISMATCH);
  }
  if (head.planGeneration !== session.planGeneration) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.HEAD_GENERATION_MISMATCH);
  }
  if (maximumStateVersion !== session.stateVersion) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.STATE_VERSION_MISMATCH);
  }

  const stateEntry = events
    .slice()
    .reverse()
    .find(
      (event) =>
        event.toStatus === session.status &&
        (event.fromStatus ?? null) !== event.toStatus
    );
  if (!stateEntry) fail(AGENT_SESSION_OBSERVATION_ERRORS.STATE_ENTRY_REQUIRED);

  const replansUsed = Math.max(0, session.planGeneration - 1);
  if (replansUsed !== replanEventCount) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.REPLAN_COUNT_MISMATCH);
  }
  if (replansUsed > session.budget.maxReplans) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.REPLAN_BUDGET_EXCEEDED);
  }

  const clientObservedAt = observationTimestamp(observedAtEpochMs);
  const timing = deriveTiming(
    stateEntry.createdAt,
    head.createdAt,
    observedAtEpochMs
  );

  return {
    contractVersion: "agent-session-observation.v1",
    source: {
      sessionId: session.sessionId,
      stateVersion: session.stateVersion,
      planGeneration: session.planGeneration,
      clientObservedAt,
      headSequence: head.sequence,
      headEventHash: head.eventHash,
      headEventAt: head.createdAt,
    },
    lifecycle: {
      status: session.status,
      stateEnteredAt: stateEntry.createdAt,
      stateAgeSeconds: timing.stateAgeSeconds,
      timingStatus: timing.status,
      attention: ATTENTION_BY_STATUS[session.status],
    },
    counters: {
      events: events.length,
      plans: snapshot.plans.length,
      approvals: snapshot.approvals.length,
      replansUsed,
      replansRemaining: session.budget.maxReplans - replansUsed,
      planFailures,
      changeRequests,
    },
    integrity: {
      runnerFullChain: "required_by_snapshot_endpoint",
      browserSequence: "verified",
      browserPrevHashLinks: "verified",
      browserEventHash: "not_verifiable_command_hash_redacted",
    },
    redactionPolicy: { ...REDACTION_POLICY },
  };
}

function observationTimestamp(value: number): string {
  if (!Number.isSafeInteger(value) || value < 0) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.OBSERVED_AT_INVALID);
  }
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    fail(AGENT_SESSION_OBSERVATION_ERRORS.OBSERVED_AT_INVALID);
  }
  return date.toISOString();
}

function deriveTiming(
  stateEnteredAt: string,
  headEventAt: string,
  observedAtEpochMs: number
): {
  stateAgeSeconds: number | null;
  status: AgentSessionObservationTimingStatus;
} {
  const stateEnteredAtMs = Date.parse(stateEnteredAt);
  const headEventAtMs = Date.parse(headEventAt);
  if (!Number.isFinite(stateEnteredAtMs) || !Number.isFinite(headEventAtMs)) {
    return { stateAgeSeconds: null, status: "invalid_timestamp" };
  }
  if (
    headEventAtMs < stateEnteredAtMs ||
    observedAtEpochMs < stateEnteredAtMs ||
    observedAtEpochMs < headEventAtMs
  ) {
    return { stateAgeSeconds: null, status: "clock_regression" };
  }
  return {
    stateAgeSeconds: Math.floor((observedAtEpochMs - stateEnteredAtMs) / 1_000),
    status: "client_estimate",
  };
}

function fail(
  code: (typeof AGENT_SESSION_OBSERVATION_ERRORS)[keyof typeof AGENT_SESSION_OBSERVATION_ERRORS]
): never {
  throw new Error(code);
}
