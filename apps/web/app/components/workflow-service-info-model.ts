export type WorkflowProductionGovernanceCheckStatus =
  | "pass"
  | "pending"
  | "partial"
  | "blocked"
  | "not_applicable"
  | string;

export type WorkflowProductionGovernanceCheck = {
  id?: string;
  status?: WorkflowProductionGovernanceCheckStatus;
  reasonCode?: string;
  blocksCurrentMode?: boolean;
  requiredFor?: string;
  evidence?: string[];
};

export type WorkflowProductionGovernanceReadiness = {
  schemaVersion?: string;
  currentModeStatus?: string;
  publicMultiUserStatus?: string;
  publicMultiUserReady?: boolean;
  currentModeBlockingCheckIds?: string[];
  publicMultiUserBlockingCheckIds?: string[];
  checks?: WorkflowProductionGovernanceCheck[];
};

export type WorkflowLocalExecutionReadinessQueue = {
  queuedJobs?: number;
  totalQueuedJobs?: number;
  scheduledQueuedJobs?: number;
  claimedJobs?: number;
  activeLeases?: number;
  resourceWaitJobs?: number;
  oldestQueuedAgeSeconds?: number | null;
  waitReasons?: Record<string, number>;
};

export type WorkflowLocalExecutionReadinessWorkers = {
  workerCount?: number;
  totalSlots?: number;
  runningSlots?: number;
  idleSlots?: number;
  queueDepth?: number;
  claimedJobs?: number;
  workerStates?: Record<string, number>;
  slotStates?: Record<string, number>;
};

export type WorkflowLocalExecutionReadiness = {
  schemaVersion?: string;
  connected?: boolean;
  diagnosticsAvailable?: boolean;
  ready?: boolean;
  status?: string;
  reasonCode?: string;
  serverId?: string;
  generatedAt?: string;
  queue?: WorkflowLocalExecutionReadinessQueue;
  workers?: WorkflowLocalExecutionReadinessWorkers;
  checks?: Record<string, boolean>;
};

export type WorkflowLocalServiceInfo = {
  deployment?: {
    mode?: string;
  };
  executionReadiness?: WorkflowLocalExecutionReadiness;
  productionGovernance?: WorkflowProductionGovernanceReadiness;
};

export type WorkflowLocalServiceInfoResponse = {
  item?: unknown;
};
