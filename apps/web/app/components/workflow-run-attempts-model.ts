import type {
  WorkflowRunExecutionAttempt,
  WorkflowRunExecutionJob,
  WorkflowRunExecutionLease,
} from "./workflows-page-model";

export type WorkflowRunExecutionSlot = {
  workerId?: string;
  sessionId?: string;
  slotId?: string;
  state?: string;
  currentAttemptId?: string | null;
  heartbeatAt?: string | null;
  startedAt?: string | null;
  stoppedAt?: string | null;
  updatedAt?: string;
};

export type WorkflowRunAttemptSummary = {
  attemptCount?: number;
  attemptsByState?: Record<string, number>;
  slotCount?: number;
  slotsByState?: Record<string, number>;
  activeLeasePresent?: boolean;
  latestAttempt?: WorkflowRunExecutionAttempt | null;
};

export type WorkflowRunAttemptsRedactionPolicy = {
  workDirExposed?: boolean;
  processIdentifiersExposed?: boolean;
  commandPayloadExposed?: boolean;
  runSpecExposed?: boolean;
  slotErrorDetailsExposed?: boolean;
};

export type WorkflowRunAttemptsReadModel = {
  schemaVersion?: string;
  runId?: string;
  run?: {
    status?: string;
    stage?: string;
    message?: string;
    startedAt?: string;
    finishedAt?: string;
    lastUpdatedAt?: string;
  };
  job?: WorkflowRunExecutionJob | null;
  attempts?: WorkflowRunExecutionAttempt[];
  activeLease?: WorkflowRunExecutionLease | null;
  slots?: WorkflowRunExecutionSlot[];
  summary?: WorkflowRunAttemptSummary;
  redactionPolicy?: WorkflowRunAttemptsRedactionPolicy;
};

export type WorkflowRunAttemptsResponse = {
  data: WorkflowRunAttemptsReadModel;
};
