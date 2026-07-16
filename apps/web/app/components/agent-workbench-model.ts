export type AgentSessionStatus =
  | "created"
  | "planning"
  | "awaiting_approval"
  | "plan_failed"
  | "changes_requested"
  | "ready_to_run"
  | "cancelled";

export type AgentBudget = {
  maxModelTurns: number;
  maxToolCalls: number;
  maxReplans: number;
  maxRetries: number;
  maxWallClockSeconds: number;
};

export type AgentUpload = {
  uploadId: string;
  filename: string;
  sizeBytes: number;
  sha256: string;
  mimeType: string;
  uploadedAt?: string;
};

export type AgentFastqGoalContext = {
  schemaVersion: "agent-fastq-qc-goal.v1";
  analysis: "fastq-qc";
  inputs: AgentUpload[];
  reportFormat: "multiqc-html";
};

export type AgentSession = {
  contractVersion: "agent-session.v1";
  sessionId: string;
  projectId: string;
  goal: {
    summary: string;
    successCriteria: string[];
    context: Record<string, unknown>;
  };
  constraints: {
    allowedToolRevisionIds: string[];
    forbiddenActions: string[];
    requirements: Record<string, unknown>;
  };
  budget: AgentBudget;
  status: AgentSessionStatus;
  stateVersion: number;
  planGeneration: number;
  activeDraftId?: string | null;
  activeDraftRevision?: number | null;
  activePlanHash?: string | null;
  workflowRevisionId?: string | null;
  planner: {
    adapterId?: string | null;
    adapterVersion?: string | null;
    modelRef?: string | null;
  };
  lastErrorCode: string;
  creationRequestId: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  cancelledAt?: string | null;
};

export type AgentWorkflowNode = {
  id: string;
  toolRevisionId: string;
  inputs: Record<string, { fromInput?: string }>;
  params: Record<string, unknown>;
  runtime: {
    threads?: number;
    resources?: Record<string, unknown>;
    schedulerResources?: Record<string, unknown>;
    log?: string | Record<string, string>;
  };
  resources: Record<string, unknown>;
  outputs: Record<
    string,
    { expose?: boolean; alias?: string | null; metadata?: Record<string, unknown> }
  >;
  metadata: Record<string, unknown>;
  provenance: Record<string, unknown>;
};

export type AgentWorkflowDraft = {
  contractVersion: "workflow-design-draft-v1";
  engine: "snakemake";
  metadata: {
    name: string;
    description: string;
    projectId: string;
    tags: string[];
  };
  inputs: Array<{
    id: string;
    role: string;
    path: string;
    filename?: string | null;
    type: string;
    kind: string;
    mimeType: string;
    format: string;
    data: string;
    operation: string;
    resource: string;
    metadata: Record<string, unknown>;
  }>;
  nodes: AgentWorkflowNode[];
  edges: Array<{
    id?: string | null;
    from: { nodeId: string; port: string };
    to: { nodeId: string; port: string };
    audit?: Record<string, unknown>;
  }>;
  resources: {
    bindings: Record<string, Record<string, string>>;
    metadata: Record<string, unknown>;
  };
  outputs: Array<{
    from: { nodeId: string; port: string };
    as: string;
    metadata: Record<string, unknown>;
  }>;
  provenance: Record<string, unknown>;
};

export type AgentPlanValidation = {
  valid: boolean;
  orderedSteps: Array<{
    id: string;
    rule?: string;
    toolId?: string;
    toolRevisionId: string;
    toolName?: string;
    params?: Record<string, unknown>;
    runtime?: Record<string, unknown>;
  }>;
  exposedOutputs: Record<string, Record<string, unknown>>;
  requiredResources: Record<string, unknown>;
  requiredDatabases: Record<string, unknown>;
  validationIssues: Array<{ code: string; message: string }>;
};

export type AgentPlanRevision = {
  contractVersion: "agent-plan-revision.v1";
  planRevisionId: string;
  sessionId: string;
  planGeneration: number;
  parentPlanRevisionId?: string | null;
  draftId: string;
  draftRevision: number;
  planHash: string;
  canonicalPayload: string;
  proposal: {
    draft: AgentWorkflowDraft;
    planner: {
      adapterId: string;
      adapterVersion?: string;
      modelRef?: string;
    };
  };
  validation: AgentPlanValidation;
  budget: AgentBudget;
  createdBy: string;
  createdAt: string;
};

export type AgentApproval = {
  contractVersion: "agent-approval.v1";
  approvalId: string;
  sessionId: string;
  planRevisionId: string;
  planGeneration: number;
  planHash: string;
  expectedStateVersion: number;
  decision: "approve" | "request_changes";
  scope: "compile_workflow_revision";
  actor: string;
  reason?: string | null;
  requestId: string;
  idempotencyKey: string;
  createdAt: string;
};

export type AgentEvent = {
  schemaVersion: "agent-event.v1";
  eventId: string;
  sessionId: string;
  sequence: number;
  eventType: string;
  fromStatus?: AgentSessionStatus | null;
  toStatus: AgentSessionStatus;
  stateVersion: number;
  planGeneration: number;
  requestId: string;
  correlationId?: string | null;
  idempotencyKey: string;
  actor: string;
  payload: Record<string, unknown>;
  payloadHash: string;
  eventHash: string;
  prevEventHash?: string | null;
  createdAt: string;
};

export type AgentPlanResult = {
  session: AgentSession;
  plan: AgentPlanRevision;
  validation: AgentPlanValidation;
  draft: {
    draftId: string;
    revision: number;
    parentDraftId?: string;
    draft: AgentWorkflowDraft;
  };
};

export type AgentApprovalResult = {
  session: AgentSession;
  plan: AgentPlanRevision;
  approval: AgentApproval;
  compiled: null | {
    workflowRevisionId: string;
    manifestHash?: string;
    draftId?: string;
    draftRevision?: number;
  };
};

export type AgentSessionSnapshot = {
  contractVersion: "agent-session-snapshot.v1";
  session: AgentSession;
  events: AgentEvent[];
  plans: AgentPlanRevision[];
  approvals: AgentApproval[];
};

export type AgentWorkbenchProblem = {
  message: string;
  status?: number;
  code?: string;
  reasonCode?: string;
  nextAction?: string;
};

export const DEFAULT_AGENT_BUDGET: AgentBudget = {
  maxModelTurns: 1,
  maxToolCalls: 2,
  maxReplans: 0,
  maxRetries: 0,
  maxWallClockSeconds: 900,
};

const STATUS_LABELS: Record<AgentSessionStatus, string> = {
  created: "目标已记录",
  planning: "规划可恢复",
  awaiting_approval: "等待审批",
  plan_failed: "方案受阻",
  changes_requested: "已请求修改",
  ready_to_run: "已编译，待运行审批",
  cancelled: "已取消",
};

const EVENT_LABELS: Record<string, string> = {
  "agent.session_created": "会话已创建",
  "agent.plan_requested": "规划命令已持久化",
  "agent.draft_created": "设计草案已创建",
  "agent.draft_revised": "设计草案已修订",
  "agent.plan_validated": "方案验证通过",
  "agent.plan_rejected": "方案验证失败",
  "agent.approval_granted": "编译审批已记录",
  "agent.changes_requested": "已请求修改",
  "agent.workflow_revision_compiled": "不可变工作流已编译",
  "agent.replan_requested": "重规划命令已记录",
  "agent.session_cancelled": "会话已取消",
};

export function agentStatusLabel(status: AgentSessionStatus): string {
  return STATUS_LABELS[status] || status;
}

export function agentEventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] || eventType;
}

export function latestAgentPlan(plans: AgentPlanRevision[]): AgentPlanRevision | null {
  return plans.slice().sort((left, right) => right.planGeneration - left.planGeneration)[0] || null;
}

export function agentFastqContext(session: AgentSession): AgentFastqGoalContext | null {
  const context = session.goal.context as Partial<AgentFastqGoalContext>;
  if (
    context.schemaVersion !== "agent-fastq-qc-goal.v1" ||
    context.analysis !== "fastq-qc" ||
    !Array.isArray(context.inputs)
  ) {
    return null;
  }
  return context as AgentFastqGoalContext;
}

export function formatAgentBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

export function shortAgentIdentity(value?: string, length = 12): string {
  const normalized = String(value || "");
  return normalized.length > length ? `${normalized.slice(0, length)}…` : normalized || "—";
}
