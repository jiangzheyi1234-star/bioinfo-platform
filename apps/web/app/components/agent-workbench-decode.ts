import type {
  AgentApproval,
  AgentApprovalResult,
  AgentBudget,
  AgentEvent,
  AgentPlanResult,
  AgentPlanRevision,
  AgentPlanValidation,
  AgentSession,
  AgentSessionSnapshot,
  AgentSessionStatus,
  AgentUpload,
} from "./agent-workbench-model";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SESSION_STATUSES = new Set<AgentSessionStatus>([
  "created",
  "planning",
  "awaiting_approval",
  "plan_failed",
  "changes_requested",
  "ready_to_run",
  "cancelled",
]);

export function requireEnvelopeData(value: unknown, code: string): unknown {
  const envelope = requireRecord(value, code);
  if (!("data" in envelope)) throw apiContractError(code);
  return envelope.data;
}

export function requireEnvelopeItems<T>(
  value: unknown,
  code: string,
  validate: (item: unknown, code: string) => T
): T[] {
  const data = requireRecord(requireEnvelopeData(value, code), code);
  if (!Array.isArray(data.items)) throw apiContractError(code);
  return data.items.map((item) => validate(item, code));
}

export function requireAgentSessionSnapshot(
  value: unknown,
  code: string
): AgentSessionSnapshot {
  const record = requireExactRecord(
    value,
    ["contractVersion", "session", "events", "plans", "approvals"],
    code
  );
  if (record.contractVersion !== "agent-session-snapshot.v1") {
    throw apiContractError(code);
  }
  const events = requireArray(record.events, code).map((item) => requireAgentEvent(item, code));
  const plans = requireArray(record.plans, code).map((item) => requireAgentPlan(item, code));
  const approvals = requireArray(record.approvals, code).map((item) =>
    requireAgentApproval(item, code)
  );
  return {
    contractVersion: "agent-session-snapshot.v1",
    session: requireAgentSession(record.session, code),
    events,
    plans,
    approvals,
  };
}

export function requireAgentUpload(
  value: unknown,
  code: string,
  requireUploadedAt = true
): AgentUpload {
  const record = requireRecord(value, code);
  const upload: AgentUpload = {
    uploadId: requireRecordText(record, "uploadId", code),
    filename: requireRecordText(record, "filename", code),
    sizeBytes: requireRecordPositiveInteger(record, "sizeBytes", code),
    sha256: requireRecordText(record, "sha256", code),
    mimeType: requireRecordText(record, "mimeType", code),
    ...(record.uploadedAt === undefined
      ? {}
      : { uploadedAt: requireRecordText(record, "uploadedAt", code) }),
  };
  if (!SHA256_PATTERN.test(upload.sha256) || (requireUploadedAt && !upload.uploadedAt)) {
    throw apiContractError(code);
  }
  return upload;
}

export function requireAgentSession(value: unknown, code: string): AgentSession {
  const record = requireRecord(value, code);
  if (record.contractVersion !== "agent-session.v1") throw apiContractError(code);
  const status = requireRecordText(record, "status", code) as AgentSessionStatus;
  if (!SESSION_STATUSES.has(status)) throw apiContractError(code);
  const sessionId = requireRecordText(record, "sessionId", code);
  const projectId = requireRecordText(record, "projectId", code);
  const stateVersion = requireRecordPositiveInteger(record, "stateVersion", code);
  const planGeneration = requireRecordNonnegativeInteger(record, "planGeneration", code);
  const goal = requireRecord(record.goal, code);
  requireRecordText(goal, "summary", code);
  requireTextArray(goal.successCriteria, code);
  requireRecord(goal.context, code);
  const constraints = requireRecord(record.constraints, code);
  requireTextArray(constraints.allowedToolRevisionIds, code);
  requireTextArray(constraints.forbiddenActions, code);
  requireRecord(constraints.requirements, code);
  const budget = requireAgentBudget(record.budget, code);
  const planner = requireRecord(record.planner, code);
  const adapterId = requireOptionalText(planner.adapterId, code);
  const adapterVersion = requireOptionalText(planner.adapterVersion, code);
  const modelRef = requireOptionalText(planner.modelRef, code);
  const activeDraftId = requireOptionalText(record.activeDraftId, code);
  const activeDraftRevision = requireOptionalPositiveInteger(record.activeDraftRevision, code);
  const activePlanHash = requireOptionalText(record.activePlanHash, code);
  if (activePlanHash && !SHA256_PATTERN.test(activePlanHash)) throw apiContractError(code);
  const workflowRevisionId = requireOptionalText(record.workflowRevisionId, code);
  const cancelledAt = requireOptionalText(record.cancelledAt, code);
  const lastErrorCode = requireString(record.lastErrorCode, code);
  const creationRequestId = requireRecordText(record, "creationRequestId", code);
  const createdBy = requireRecordText(record, "createdBy", code);
  const createdAt = requireRecordText(record, "createdAt", code);
  const updatedAt = requireRecordText(record, "updatedAt", code);
  return {
    contractVersion: "agent-session.v1",
    sessionId,
    projectId,
    goal: goal as AgentSession["goal"],
    constraints: constraints as AgentSession["constraints"],
    budget,
    status,
    stateVersion,
    planGeneration,
    activeDraftId,
    activeDraftRevision,
    activePlanHash,
    workflowRevisionId,
    planner: { adapterId, adapterVersion, modelRef },
    lastErrorCode,
    creationRequestId,
    createdBy,
    createdAt,
    updatedAt,
    cancelledAt,
  };
}

export function requireAgentPlan(value: unknown, code: string): AgentPlanRevision {
  const record = requireRecord(value, code);
  if (record.contractVersion !== "agent-plan-revision.v1") throw apiContractError(code);
  requireRecordText(record, "planRevisionId", code);
  requireRecordText(record, "sessionId", code);
  requireRecordPositiveInteger(record, "planGeneration", code);
  requireRecordText(record, "draftId", code);
  requireRecordPositiveInteger(record, "draftRevision", code);
  const hash = requireRecordText(record, "planHash", code);
  if (!SHA256_PATTERN.test(hash)) throw apiContractError(code);
  requireRecordText(record, "canonicalPayload", code);
  const proposal = requireRecord(record.proposal, code);
  requireAgentWorkflowDraft(proposal.draft, code);
  const planner = requireRecord(proposal.planner, code);
  requireRecordText(planner, "adapterId", code);
  requireOptionalText(planner.adapterVersion, code);
  requireOptionalText(planner.modelRef, code);
  const parentPlanRevisionId = requireOptionalText(record.parentPlanRevisionId, code);
  requireAgentPlanValidation(record.validation, code);
  requireAgentBudget(record.budget, code);
  requireRecordText(record, "createdBy", code);
  requireRecordText(record, "createdAt", code);
  return { ...record, parentPlanRevisionId } as unknown as AgentPlanRevision;
}

export function requireAgentApproval(value: unknown, code: string): AgentApproval {
  const record = requireRecord(value, code);
  if (record.contractVersion !== "agent-approval.v1") throw apiContractError(code);
  requireRecordText(record, "approvalId", code);
  requireRecordText(record, "sessionId", code);
  requireRecordText(record, "planRevisionId", code);
  requireRecordPositiveInteger(record, "planGeneration", code);
  if (!SHA256_PATTERN.test(requireRecordText(record, "planHash", code))) {
    throw apiContractError(code);
  }
  requireRecordPositiveInteger(record, "expectedStateVersion", code);
  if (record.decision !== "approve" && record.decision !== "request_changes") {
    throw apiContractError(code);
  }
  if (record.scope !== "compile_workflow_revision") throw apiContractError(code);
  const reason = requireOptionalText(record.reason, code);
  requireRecordText(record, "actor", code);
  requireRecordText(record, "requestId", code);
  requireRecordText(record, "idempotencyKey", code);
  requireRecordText(record, "createdAt", code);
  return { ...record, reason } as unknown as AgentApproval;
}

export function requireAgentEvent(value: unknown, code: string): AgentEvent {
  const record = requireRecord(value, code);
  if (record.schemaVersion !== "agent-event.v1") throw apiContractError(code);
  requireRecordText(record, "eventId", code);
  requireRecordText(record, "sessionId", code);
  requireRecordPositiveInteger(record, "sequence", code);
  requireRecordText(record, "eventType", code);
  const toStatus = requireRecordText(record, "toStatus", code) as AgentSessionStatus;
  if (!SESSION_STATUSES.has(toStatus)) throw apiContractError(code);
  const fromStatus = requireOptionalText(record.fromStatus, code) as AgentSessionStatus | null;
  if (fromStatus && !SESSION_STATUSES.has(fromStatus)) throw apiContractError(code);
  requireRecordPositiveInteger(record, "stateVersion", code);
  requireRecordNonnegativeInteger(record, "planGeneration", code);
  requireRecordText(record, "requestId", code);
  requireRecordText(record, "idempotencyKey", code);
  requireRecordText(record, "actor", code);
  requireRecord(record.payload, code);
  if (!SHA256_PATTERN.test(requireRecordText(record, "payloadHash", code))) {
    throw apiContractError(code);
  }
  if (!SHA256_PATTERN.test(requireRecordText(record, "eventHash", code))) {
    throw apiContractError(code);
  }
  const previous = requireOptionalText(record.prevEventHash, code);
  if (previous && !SHA256_PATTERN.test(previous)) throw apiContractError(code);
  requireOptionalText(record.correlationId, code);
  requireRecordText(record, "createdAt", code);
  return record as unknown as AgentEvent;
}

export function requireAgentWorkflowDraft(
  value: unknown,
  code: string
): Record<string, unknown> {
  const draft = requireRecord(value, code);
  if (draft.contractVersion !== "workflow-design-draft-v1" || draft.engine !== "snakemake") {
    throw apiContractError(code);
  }
  const metadata = requireRecord(draft.metadata, code);
  requireRecordText(metadata, "name", code);
  requireString(metadata.description, code);
  requireRecordText(metadata, "projectId", code);
  requireTextArray(metadata.tags, code);
  requireArray(draft.inputs, code).forEach((value) => {
    const input = requireRecord(value, code);
    for (const key of ["id", "role", "path", "type", "mimeType"]) {
      requireRecordText(input, key, code);
    }
    for (const key of ["kind", "format", "data", "operation", "resource"]) {
      requireString(input[key], code);
    }
    requireOptionalText(input.filename, code);
    requireRecord(input.metadata, code);
  });
  requireArray(draft.nodes, code).forEach((value) => {
    const node = requireRecord(value, code);
    requireRecordText(node, "id", code);
    requireRecordText(node, "toolRevisionId", code);
    requireRecord(node.inputs, code);
    requireRecord(node.params, code);
    requireRecord(node.runtime, code);
    requireRecord(node.resources, code);
    Object.values(requireRecord(node.outputs, code)).forEach((output) => requireRecord(output, code));
    requireRecord(node.metadata, code);
    requireRecord(node.provenance, code);
  });
  requireArray(draft.edges, code).forEach((value) => {
    const edge = requireRecord(value, code);
    for (const endpoint of [requireRecord(edge.from, code), requireRecord(edge.to, code)]) {
      requireRecordText(endpoint, "nodeId", code);
      requireRecordText(endpoint, "port", code);
    }
  });
  const resources = requireRecord(draft.resources, code);
  requireRecord(resources.bindings, code);
  requireRecord(resources.metadata, code);
  requireArray(draft.outputs, code).forEach((value) => {
    const output = requireRecord(value, code);
    const source = requireRecord(output.from, code);
    requireRecordText(source, "nodeId", code);
    requireRecordText(source, "port", code);
    requireRecordText(output, "as", code);
    requireRecord(output.metadata, code);
  });
  requireRecord(draft.provenance, code);
  return draft;
}

export function requireAgentPlanResult(value: unknown): AgentPlanResult {
  const code = "AGENT_SESSION_PLAN_RESPONSE_INVALID";
  const record = requireRecord(value, code);
  const session = requireAgentSession(record.session, code);
  const plan = requireAgentPlan(record.plan, code);
  const validation = requireAgentPlanValidation(record.validation, code);
  const draft = requireRecord(record.draft, code);
  requireRecordText(draft, "draftId", code);
  requireRecordPositiveInteger(draft, "revision", code);
  const decodedDraft = requireAgentWorkflowDraft(draft.draft, code);
  if (
    plan.sessionId !== session.sessionId ||
    plan.planGeneration !== session.planGeneration ||
    plan.draftId !== draft.draftId ||
    plan.draftRevision !== draft.revision ||
    session.activeDraftId !== plan.draftId ||
    session.activeDraftRevision !== plan.draftRevision ||
    session.activePlanHash !== plan.planHash ||
    JSON.stringify(plan.validation) !== JSON.stringify(validation) ||
    JSON.stringify(plan.proposal.draft) !== JSON.stringify(decodedDraft)
  ) {
    throw apiContractError(code);
  }
  return { session, plan, validation, draft: draft as AgentPlanResult["draft"] };
}

export function requireAgentApprovalResult(value: unknown): AgentApprovalResult {
  const code = "AGENT_SESSION_APPROVAL_RESPONSE_INVALID";
  const record = requireRecord(value, code);
  const session = requireAgentSession(record.session, code);
  const plan = requireAgentPlan(record.plan, code);
  const approval = requireAgentApproval(record.approval, code);
  let compiled: AgentApprovalResult["compiled"] = null;
  if (record.compiled !== null) {
    const valueRecord = requireRecord(record.compiled, code);
    requireRecordText(valueRecord, "workflowRevisionId", code);
    const manifestHash = requireOptionalText(valueRecord.manifestHash, code);
    if (manifestHash && !SHA256_PATTERN.test(manifestHash)) throw apiContractError(code);
    requireOptionalText(valueRecord.draftId, code);
    requireOptionalPositiveInteger(valueRecord.draftRevision, code);
    compiled = valueRecord as AgentApprovalResult["compiled"];
  }
  const compiledMatches =
    approval.decision === "approve"
      ? Boolean(
          compiled &&
            session.status === "ready_to_run" &&
            session.workflowRevisionId === compiled.workflowRevisionId &&
            (!compiled.draftId || compiled.draftId === plan.draftId) &&
            (!compiled.draftRevision || compiled.draftRevision === plan.draftRevision)
        )
      : compiled === null && session.status === "changes_requested";
  if (
    plan.sessionId !== session.sessionId ||
    approval.sessionId !== session.sessionId ||
    approval.planRevisionId !== plan.planRevisionId ||
    approval.planGeneration !== plan.planGeneration ||
    approval.planHash !== plan.planHash ||
    session.planGeneration !== plan.planGeneration ||
    session.activePlanHash !== plan.planHash ||
    !compiledMatches
  ) {
    throw apiContractError(code);
  }
  return { session, plan, approval, compiled };
}

export function requireAgentPlanValidation(value: unknown, code: string): AgentPlanValidation {
  const record = requireRecord(value, code);
  if (typeof record.valid !== "boolean" || !Array.isArray(record.orderedSteps)) {
    throw apiContractError(code);
  }
  const exposedOutputs = requireRecord(record.exposedOutputs, code);
  requireRecord(record.requiredResources, code);
  requireRecord(record.requiredDatabases, code);
  if (!Array.isArray(record.validationIssues)) throw apiContractError(code);
  record.orderedSteps.forEach((value) => {
    const step = requireRecord(value, code);
    requireRecordText(step, "id", code);
    requireRecordText(step, "toolRevisionId", code);
  });
  Object.values(exposedOutputs).forEach((value) => requireRecord(value, code));
  record.validationIssues.forEach((value) => {
    const issue = requireRecord(value, code);
    requireRecordText(issue, "code", code);
    requireRecordText(issue, "message", code);
  });
  return record as unknown as AgentPlanValidation;
}

export function requireAgentBudget(value: unknown, code: string): AgentBudget {
  const record = requireRecord(value, code);
  requireRecordPositiveInteger(record, "maxModelTurns", code);
  requireRecordNonnegativeInteger(record, "maxToolCalls", code);
  requireRecordNonnegativeInteger(record, "maxReplans", code);
  requireRecordNonnegativeInteger(record, "maxRetries", code);
  requireRecordPositiveInteger(record, "maxWallClockSeconds", code);
  return record as unknown as AgentBudget;
}

export function requirePositiveInteger(value: number, code: string): number {
  if (!Number.isSafeInteger(value) || value < 1) throw apiContractError(code);
  return value;
}

export function requireInputText(value: string, code: string): string {
  const normalized = requiredText(value);
  if (!normalized) throw apiContractError(code);
  return normalized;
}

export function optionalInputText(value: string | undefined, code: string): string | undefined {
  if (value === undefined) return undefined;
  return requireInputText(value, code);
}

export function requiredText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function apiContractError(code: string): Error {
  return new Error(code);
}

function requireRecord(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw apiContractError(code);
  }
  return value as Record<string, unknown>;
}

function requireExactRecord(
  value: unknown,
  keys: readonly string[],
  code: string
): Record<string, unknown> {
  const record = requireRecord(value, code);
  const actualKeys = Object.keys(record);
  if (actualKeys.length !== keys.length || actualKeys.some((key) => !keys.includes(key))) {
    throw apiContractError(code);
  }
  return record;
}

function requireArray(value: unknown, code: string): unknown[] {
  if (!Array.isArray(value)) throw apiContractError(code);
  return value;
}

function requireTextArray(value: unknown, code: string): string[] {
  const items = requireArray(value, code);
  if (items.some((item) => typeof item !== "string" || !item.trim())) {
    throw apiContractError(code);
  }
  return items as string[];
}

function requireString(value: unknown, code: string): string {
  if (typeof value !== "string") throw apiContractError(code);
  return value;
}

function requireOptionalText(value: unknown, code: string): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string" || !value.trim()) throw apiContractError(code);
  return value;
}

function requireOptionalPositiveInteger(value: unknown, code: string): number | null {
  if (value === undefined || value === null) return null;
  if (!Number.isSafeInteger(value) || Number(value) < 1) throw apiContractError(code);
  return Number(value);
}

function requireRecordText(record: Record<string, unknown>, key: string, code: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value.trim()) throw apiContractError(code);
  return value;
}

function requireRecordPositiveInteger(
  record: Record<string, unknown>,
  key: string,
  code: string
): number {
  const value = record[key];
  if (!Number.isSafeInteger(value) || Number(value) < 1) throw apiContractError(code);
  return Number(value);
}

function requireRecordNonnegativeInteger(
  record: Record<string, unknown>,
  key: string,
  code: string
): number {
  const value = record[key];
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw apiContractError(code);
  return Number(value);
}
