"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  AgentApprovalResult,
  AgentBudget,
  AgentEvent,
  AgentFastqGoalContext,
  AgentPlanResult,
  AgentSession,
  AgentSessionSnapshot,
  AgentUpload,
} from "./agent-workbench-model";
import {
  apiContractError,
  optionalInputText,
  requiredText,
  requireAgentApprovalResult,
  requireAgentPlanResult,
  requireAgentSession,
  requireAgentSessionSnapshot,
  requireAgentUpload,
  requireEnvelopeData,
  requireEnvelopeItems,
  requireInputText,
  requirePositiveInteger,
} from "./agent-workbench-decode";
import {
  agentJsonEqual,
  assertAgentPlanHash,
  sha256Hex,
} from "./agent-workbench-integrity";
import { assertAgentApprovalDurableProof } from "./agent-workbench-durable-proof";
import { fetchWorkflowServer, fileToBase64 } from "./workflows-page-api";
import type { WorkflowServer } from "./workflows-page-model";

export const AGENT_FASTQ_MAX_BYTES = 32 * 1024 * 1024;

const AGENT_COMMAND_TIMEOUT_MS = 150_000;
const AGENT_READ_TIMEOUT_MS = 30_000;
const FASTQ_FILENAME_PATTERN = /\.(?:fastq|fq)$/i;
const FORBIDDEN_FILENAME_PATTERN = /[\\/:*?"<>|\u0000-\u001f]/;

export type LoadAgentServerInput = {
  forceRefresh?: boolean;
  serverId?: string;
  preferredServerId?: string;
};

export type UploadAndVerifyAgentFastqInput = {
  serverId: string;
  files: readonly File[] | FileList;
};

export type CreateAgentSessionInput = {
  serverId: string;
  projectId: string;
  creationRequestId: string;
  goal: Omit<AgentSession["goal"], "context"> & { context: AgentFastqGoalContext };
  constraints: AgentSession["constraints"];
  budget: AgentBudget;
};

export type AgentReadInput = {
  serverId: string;
  refresh?: boolean;
};

export type AgentSessionReadInput = AgentReadInput & {
  sessionId: string;
};

export type AgentCommandInput = {
  serverId: string;
  sessionId: string;
  requestId: string;
  idempotencyKey: string;
  expectedStateVersion: number;
};

export type PlanAgentSessionInput = AgentCommandInput;

export type DecideAgentPlanInput = AgentCommandInput & {
  decision: "approve" | "request_changes";
  expectedPlanHash: string;
  reason?: string;
};

export type CancelAgentSessionInput = AgentCommandInput & {
  reason?: string;
};

export async function loadAgentServer(
  input: LoadAgentServerInput = {}
): Promise<WorkflowServer> {
  const serverId = optionalInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED");
  const preferredServerId = optionalInputText(
    input.preferredServerId,
    "AGENT_WORKBENCH_SERVER_ID_REQUIRED"
  );
  if (serverId && preferredServerId && serverId !== preferredServerId) {
    throw apiContractError("AGENT_WORKBENCH_SERVER_IDENTITY_CONFLICT");
  }
  const expectedServerId = preferredServerId || serverId;
  const server = await fetchWorkflowServer({
    forceRefresh: Boolean(input.forceRefresh || expectedServerId),
    ...(expectedServerId ? { serverId: expectedServerId } : {}),
  });
  if (!requiredText(server.serverId) || server.connected !== true || server.ready !== true) {
    throw apiContractError("AGENT_WORKBENCH_READY_SERVER_REQUIRED");
  }
  if (expectedServerId && server.serverId !== expectedServerId) {
    throw apiContractError("AGENT_WORKBENCH_SERVER_IDENTITY_MISMATCH");
  }
  return server;
}

export async function uploadAndVerifyAgentFastq(
  input: UploadAndVerifyAgentFastqInput
): Promise<AgentUpload> {
  const serverId = requireInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED");
  const files = Array.from(input.files);
  if (files.length !== 1) {
    throw apiContractError("INPUT_FASTQ_QC_EXACTLY_ONE_FILE_REQUIRED");
  }
  const file = files[0];
  validateFastqFile(file);
  const localSha256 = await sha256Hex(await file.arrayBuffer());

  const createdResponse = await requestLocalApiJson<unknown>("POST", "/api/v1/uploads", {
    body: {
      serverId,
      filename: file.name,
      contentBase64: await fileToBase64(file),
      mimeType: "text/plain",
    },
    cache: "no-store",
    timeoutMs: AGENT_COMMAND_TIMEOUT_MS,
  });
  const created = requireAgentUpload(
    requireEnvelopeData(createdResponse, "AGENT_UPLOAD_CREATE_RESPONSE_INVALID"),
    "AGENT_UPLOAD_CREATE_RESPONSE_INVALID"
  );
  if (
    created.filename !== file.name ||
    created.sizeBytes !== file.size ||
    created.mimeType !== "text/plain" ||
    created.sha256 !== localSha256
  ) {
    throw apiContractError("INPUT_FASTQ_QC_UPLOAD_MANIFEST_MISMATCH");
  }

  const verifiedResponse = await requestLocalApiJson<unknown>(
    "GET",
    `/api/v1/uploads/${encodeURIComponent(created.uploadId)}?${readQuery(serverId, true, false)}`,
    { cache: "no-store", timeoutMs: AGENT_READ_TIMEOUT_MS }
  );
  const verified = requireAgentUpload(
    requireEnvelopeData(verifiedResponse, "AGENT_UPLOAD_READ_RESPONSE_INVALID"),
    "AGENT_UPLOAD_READ_RESPONSE_INVALID"
  );
  assertUploadManifestEqual(created, verified);
  if (verified.sha256 !== localSha256) {
    throw apiContractError("INPUT_FASTQ_QC_UPLOAD_DIGEST_MISMATCH");
  }
  return verified;
}

export async function createAgentSession(input: CreateAgentSessionInput): Promise<AgentSession> {
  const serverId = requireInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED");
  const goalContext = requireFastqGoalContext(input.goal.context);
  const body = {
    contractVersion: "agent-session.v1",
    serverId,
    projectId: requireInputText(input.projectId, "AGENT_SESSION_PROJECT_ID_REQUIRED"),
    creationRequestId: requireInputText(
      input.creationRequestId,
      "AGENT_SESSION_CREATION_REQUEST_ID_REQUIRED"
    ),
    goal: {
      summary: requireInputText(input.goal.summary, "AGENT_SESSION_GOAL_SUMMARY_REQUIRED"),
      successCriteria: input.goal.successCriteria,
      context: goalContext,
    },
    constraints: input.constraints,
    budget: input.budget,
  };
  const response = await requestLocalApiJson<unknown>("POST", "/api/v1/agent-sessions", {
    body,
    cache: "no-store",
    timeoutMs: AGENT_READ_TIMEOUT_MS,
  });
  const session = requireAgentSession(
    requireEnvelopeData(response, "AGENT_SESSION_CREATE_RESPONSE_INVALID"),
    "AGENT_SESSION_CREATE_RESPONSE_INVALID"
  );
  if (
    session.creationRequestId !== body.creationRequestId ||
    session.projectId !== body.projectId ||
    !agentJsonEqual(session.goal, body.goal) ||
    !agentJsonEqual(session.constraints, body.constraints) ||
    !agentJsonEqual(session.budget, body.budget)
  ) {
    throw apiContractError("AGENT_SESSION_CREATE_RESPONSE_IDENTITY_MISMATCH");
  }
  return session;
}

export async function fetchAgentSessions(input: AgentReadInput): Promise<AgentSession[]> {
  const response = await requestLocalApiJson<unknown>(
    "GET",
    `/api/v1/agent-sessions?${readQuery(input.serverId, input.refresh)}`,
    { cache: "no-store", timeoutMs: AGENT_READ_TIMEOUT_MS }
  );
  return requireEnvelopeItems(
    response,
    "AGENT_SESSION_LIST_RESPONSE_INVALID",
    requireAgentSession
  );
}

export async function fetchAgentSessionSnapshot(
  input: AgentSessionReadInput
): Promise<AgentSessionSnapshot> {
  const serverId = requireInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED");
  const expectedSessionId = requireInputText(input.sessionId, "AGENT_SESSION_ID_REQUIRED");
  const response = await requestLocalApiJson<unknown>(
    "GET",
    `${sessionPath(expectedSessionId)}/snapshot?${readQuery(serverId, input.refresh)}`,
    { cache: "no-store", timeoutMs: AGENT_READ_TIMEOUT_MS }
  );
  const snapshot = requireAgentSessionSnapshot(
    requireEnvelopeData(response, "AGENT_SESSION_SNAPSHOT_RESPONSE_INVALID"),
    "AGENT_SESSION_SNAPSHOT_RESPONSE_INVALID"
  );
  const { session, events, plans, approvals } = snapshot;
  await Promise.all(plans.map((plan) => assertAgentPlanHash(plan)));
  const sessionId = session.sessionId;
  if (
    sessionId !== expectedSessionId ||
    events.some((item) => item.sessionId !== sessionId) ||
    plans.some((item) => item.sessionId !== sessionId) ||
    approvals.some((item) => item.sessionId !== sessionId)
  ) {
    throw apiContractError("AGENT_SESSION_SNAPSHOT_IDENTITY_MISMATCH");
  }
  assertUniqueSnapshotItems(events, (item) => item.eventId);
  assertUniqueSnapshotItems(plans, (item) => item.planRevisionId);
  assertUniqueSnapshotItems(approvals, (item) => item.approvalId);
  const activeFields = [
    session.activePlanHash,
    session.activeDraftId,
    session.activeDraftRevision,
  ];
  const hasActivePlan = activeFields.every((value) => value !== null && value !== undefined);
  if (
    activeFields.some((value) => value !== null && value !== undefined) !== hasActivePlan
  ) {
    throw apiContractError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH");
  }
  const currentGenerationPlans = plans.filter(
    (plan) => plan.planGeneration === session.planGeneration
  );
  if (hasActivePlan) {
    const active = currentGenerationPlans.filter(
      (plan) =>
        plan.planHash === session.activePlanHash &&
        plan.draftId === session.activeDraftId &&
        plan.draftRevision === session.activeDraftRevision
    );
    if (active.length !== 1 || currentGenerationPlans.length !== 1) {
      throw apiContractError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH");
    }
  } else {
    const activeRequired = [
      "awaiting_approval",
      "plan_failed",
      "changes_requested",
      "ready_to_run",
    ].includes(session.status);
    if (activeRequired || (session.status === "created" && currentGenerationPlans.length)) {
      throw apiContractError("AGENT_SESSION_SNAPSHOT_ACTIVE_PLAN_MISMATCH");
    }
  }
  for (const approval of approvals) {
    const plan = plans.find((candidate) => candidate.planRevisionId === approval.planRevisionId);
    if (
      !plan ||
      plan.planHash !== approval.planHash ||
      plan.planGeneration !== approval.planGeneration
    ) {
      throw apiContractError("AGENT_SESSION_SNAPSHOT_APPROVAL_PLAN_MISMATCH");
    }
  }
  return snapshot;
}

export async function planAgentSession(input: PlanAgentSessionInput): Promise<AgentPlanResult> {
  const planningStateVersion = addSafeStateVersion(
    input.expectedStateVersion,
    1,
    "AGENT_SESSION_PLAN_RESPONSE_VERSION_MISMATCH"
  );
  const completedStateVersion = addSafeStateVersion(
    input.expectedStateVersion,
    2,
    "AGENT_SESSION_PLAN_RESPONSE_VERSION_MISMATCH"
  );
  const command = commandBody(input);
  const response = await requestLocalApiJson<unknown>("POST", `${sessionPath(input.sessionId)}/plan`, {
    body: command,
    cache: "no-store",
    timeoutMs: AGENT_COMMAND_TIMEOUT_MS,
  });
  const result = requireAgentPlanResult(
    requireEnvelopeData(response, "AGENT_SESSION_PLAN_RESPONSE_INVALID")
  );
  assertSessionIdentity(result.session.sessionId, input.sessionId);
  await assertAgentPlanHash(result.plan);
  const commandEvent = await requireDurableCommandEvent(
    input,
    "agent.plan_requested",
    planningStateVersion,
    "AGENT_SESSION_PLAN_RESPONSE_IDENTITY_MISMATCH"
  );
  if (
    commandEvent.toStatus !== "planning" ||
    commandEvent.planGeneration !== result.session.planGeneration ||
    result.session.stateVersion !== completedStateVersion
  ) {
    throw apiContractError("AGENT_SESSION_PLAN_RESPONSE_VERSION_MISMATCH");
  }
  return result;
}

export async function decideAgentPlan(input: DecideAgentPlanInput): Promise<AgentApprovalResult> {
  const decidedStateVersion = addSafeStateVersion(
    input.expectedStateVersion,
    1,
    "AGENT_SESSION_APPROVAL_RESPONSE_IDENTITY_MISMATCH"
  );
  const reason = optionalInputText(input.reason, "AGENT_SESSION_APPROVAL_REASON_REQUIRED");
  if (input.decision === "request_changes" && !reason) {
    throw apiContractError("AGENT_SESSION_CHANGE_REASON_REQUIRED");
  }
  const response = await requestLocalApiJson<unknown>(
    "POST",
    `${sessionPath(input.sessionId)}/approval`,
    {
      body: {
        ...commandBody(input),
        decision: input.decision,
        expectedPlanHash: requireInputText(
          input.expectedPlanHash,
          "AGENT_SESSION_EXPECTED_PLAN_HASH_REQUIRED"
        ),
        ...(reason ? { reason } : {}),
      },
      cache: "no-store",
      timeoutMs: AGENT_COMMAND_TIMEOUT_MS,
    }
  );
  const result = requireAgentApprovalResult(
    requireEnvelopeData(response, "AGENT_SESSION_APPROVAL_RESPONSE_INVALID")
  );
  assertSessionIdentity(result.session.sessionId, input.sessionId);
  await assertAgentPlanHash(result.plan);
  if (
    result.approval.requestId !== input.requestId ||
    result.approval.idempotencyKey !== input.idempotencyKey ||
    result.approval.expectedStateVersion !== input.expectedStateVersion ||
    result.approval.decision !== input.decision ||
    result.approval.planHash !== input.expectedPlanHash ||
    (result.approval.reason || undefined) !== reason ||
    result.session.stateVersion !== decidedStateVersion
  ) {
    throw apiContractError("AGENT_SESSION_APPROVAL_RESPONSE_IDENTITY_MISMATCH");
  }
  const snapshot = await fetchAgentSessionSnapshot({
    serverId: input.serverId,
    sessionId: input.sessionId,
    refresh: true,
  });
  assertAgentApprovalDurableProof(snapshot, result);
  return result;
}

export async function cancelAgentSession(input: CancelAgentSessionInput): Promise<AgentSession> {
  const cancelledStateVersion = addSafeStateVersion(
    input.expectedStateVersion,
    1,
    "AGENT_SESSION_CANCEL_RESPONSE_IDENTITY_MISMATCH"
  );
  const reason = optionalInputText(input.reason, "AGENT_SESSION_CANCEL_REASON_REQUIRED");
  const response = await requestLocalApiJson<unknown>(
    "POST",
    `${sessionPath(input.sessionId)}/cancel`,
    {
      body: {
        ...commandBody(input),
        ...(reason ? { reason } : {}),
      },
      cache: "no-store",
      timeoutMs: AGENT_COMMAND_TIMEOUT_MS,
    }
  );
  const session = requireAgentSession(
    requireEnvelopeData(response, "AGENT_SESSION_CANCEL_RESPONSE_INVALID"),
    "AGENT_SESSION_CANCEL_RESPONSE_INVALID"
  );
  assertSessionIdentity(session.sessionId, input.sessionId);
  const commandEvent = await requireDurableCommandEvent(
    input,
    "agent.session_cancelled",
    cancelledStateVersion,
    "AGENT_SESSION_CANCEL_RESPONSE_IDENTITY_MISMATCH"
  );
  const eventReason = optionalEventText(commandEvent.payload.reason);
  if (
    session.status !== "cancelled" ||
    commandEvent.toStatus !== "cancelled" ||
    commandEvent.planGeneration !== session.planGeneration ||
    session.stateVersion !== commandEvent.stateVersion ||
    eventReason !== reason
  ) {
    throw apiContractError("AGENT_SESSION_CANCEL_RESPONSE_IDENTITY_MISMATCH");
  }
  return session;
}

async function requireDurableCommandEvent(
  input: AgentCommandInput,
  eventType: "agent.plan_requested" | "agent.session_cancelled",
  expectedNewStateVersion: number,
  code: string
): Promise<AgentEvent> {
  const sessionId = requireInputText(input.sessionId, "AGENT_SESSION_ID_REQUIRED");
  const requestId = requireInputText(input.requestId, "AGENT_SESSION_REQUEST_ID_REQUIRED");
  const idempotencyKey = requireInputText(
    input.idempotencyKey,
    "AGENT_SESSION_IDEMPOTENCY_KEY_REQUIRED"
  );
  const { events } = await fetchAgentSessionSnapshot({
    serverId: requireInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED"),
    sessionId,
    refresh: true,
  });
  const matches = events.filter(
    (event) =>
      event.eventType === eventType &&
      event.sessionId === sessionId &&
      event.requestId === requestId &&
      event.idempotencyKey === idempotencyKey &&
      event.stateVersion === expectedNewStateVersion
  );
  if (matches.length !== 1) throw apiContractError(code);
  return matches[0];
}

function optionalEventText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function commandBody(input: AgentCommandInput) {
  return {
    serverId: requireInputText(input.serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED"),
    requestId: requireInputText(input.requestId, "AGENT_SESSION_REQUEST_ID_REQUIRED"),
    idempotencyKey: requireInputText(
      input.idempotencyKey,
      "AGENT_SESSION_IDEMPOTENCY_KEY_REQUIRED"
    ),
    expectedStateVersion: requirePositiveInteger(
      input.expectedStateVersion,
      "AGENT_SESSION_EXPECTED_STATE_VERSION_INVALID"
    ),
  };
}

function addSafeStateVersion(value: number, delta: number, code: string): number {
  const current = requirePositiveInteger(value, code);
  if (!Number.isSafeInteger(delta) || delta < 1) throw apiContractError(code);
  const next = current + delta;
  if (!Number.isSafeInteger(next)) throw apiContractError(code);
  return next;
}

function assertUniqueSnapshotItems<T>(items: readonly T[], identity: (item: T) => string): void {
  const identities = new Set(items.map(identity));
  if (identities.size !== items.length) {
    throw apiContractError("AGENT_SESSION_SNAPSHOT_IDENTITY_MISMATCH");
  }
}

function readQuery(serverId: string, refresh = true, includeRefresh = true): string {
  const query = new URLSearchParams({
    serverId: requireInputText(serverId, "AGENT_WORKBENCH_SERVER_ID_REQUIRED"),
  });
  if (includeRefresh) query.set("refresh", String(refresh));
  return query.toString();
}

function sessionPath(sessionId: string): string {
  return `/api/v1/agent-sessions/${encodeURIComponent(
    requireInputText(sessionId, "AGENT_SESSION_ID_REQUIRED")
  )}`;
}

function assertSessionIdentity(actual: string, expected: string): void {
  if (actual !== requireInputText(expected, "AGENT_SESSION_ID_REQUIRED")) {
    throw apiContractError("AGENT_SESSION_RESPONSE_IDENTITY_MISMATCH");
  }
}

function validateFastqFile(file: File): void {
  if (!file || typeof file.name !== "string" || !Number.isSafeInteger(file.size)) {
    throw apiContractError("INPUT_FASTQ_QC_FILE_INVALID");
  }
  const filename = file.name.trim();
  if (
    filename !== file.name ||
    !filename ||
    filename === "." ||
    filename === ".." ||
    FORBIDDEN_FILENAME_PATTERN.test(filename)
  ) {
    throw apiContractError("INPUT_FASTQ_QC_FILENAME_INVALID");
  }
  if (!FASTQ_FILENAME_PATTERN.test(filename)) {
    throw apiContractError("INPUT_FASTQ_QC_FILE_TYPE_UNSUPPORTED");
  }
  if (file.size <= 0) {
    throw apiContractError("INPUT_FASTQ_QC_FILE_EMPTY");
  }
  if (file.size > AGENT_FASTQ_MAX_BYTES) {
    throw apiContractError("UPLOAD_TOO_LARGE");
  }
}

function requireFastqGoalContext(value: AgentFastqGoalContext): AgentFastqGoalContext {
  if (
    value.schemaVersion !== "agent-fastq-qc-goal.v1" ||
    value.analysis !== "fastq-qc" ||
    value.reportFormat !== "multiqc-html" ||
    !Array.isArray(value.inputs) ||
    value.inputs.length !== 1
  ) {
    throw apiContractError("INPUT_FASTQ_QC_GOAL_CONTEXT_INVALID");
  }
  const upload = requireAgentUpload(value.inputs[0], "INPUT_FASTQ_QC_GOAL_CONTEXT_INVALID", false);
  return {
    schemaVersion: "agent-fastq-qc-goal.v1",
    analysis: "fastq-qc",
    inputs: [publicGoalUpload(upload)],
    reportFormat: "multiqc-html",
  };
}

function publicGoalUpload(upload: AgentUpload): AgentUpload {
  return {
    uploadId: upload.uploadId,
    filename: upload.filename,
    sizeBytes: upload.sizeBytes,
    sha256: upload.sha256,
    mimeType: upload.mimeType,
  };
}

function assertUploadManifestEqual(left: AgentUpload, right: AgentUpload): void {
  const keys: Array<keyof AgentUpload> = [
    "uploadId",
    "filename",
    "sizeBytes",
    "sha256",
    "mimeType",
    "uploadedAt",
  ];
  if (keys.some((key) => left[key] !== right[key])) {
    throw apiContractError("INPUT_FASTQ_QC_UPLOAD_MANIFEST_MISMATCH");
  }
}
