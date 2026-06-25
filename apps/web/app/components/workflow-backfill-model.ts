export type WorkflowBackfillPartitionSummary = {
  partitionCount?: number;
  states?: Record<string, number>;
  submittedRunCount?: number;
  activeRunCount?: number;
  occupiedConcurrencySlotCount?: number;
  admittingPartitionCount?: number;
  blockedPartitionCount?: number;
  failedPartitionCount?: number;
  pendingPartitionCount?: number;
  replayedPartitionCount?: number;
  cancelRequestedPartitionCount?: number;
  cancellableRunCount?: number;
};

export type WorkflowBackfillConcurrency = {
  limit?: number | null;
  partitionCount?: number;
  enforced?: boolean;
  activeRunCount?: number;
  occupiedSlotCount?: number;
  availableSlots?: number;
  pendingPartitionCount?: number;
  blockedPartitionCount?: number;
  admittingPartitionCount?: number;
};

export type WorkflowBackfillRange = {
  start?: string;
  end?: string;
  timezone?: string;
  partitionUnit?: string;
  semantics?: string;
  runOrder?: string;
};

export type WorkflowBackfillPreviewRequest = {
  rangeStart: string;
  rangeEnd: string;
  partitionUnit: "hour" | "day";
  timezone: string;
  maxPartitions: number;
  concurrencyLimit: number;
  runOrder: "forward" | "backward";
  reprocessBehavior: "none" | "failed" | "completed";
  params?: Record<string, unknown>;
};

export type WorkflowRunAdmissionWaitReason = {
  code?: string;
  resource?: string;
  available?: number;
  requested?: number;
  maxActiveSlots?: number;
  slotIdPresent?: boolean;
};

export type WorkflowRunAdmissionSummary = {
  schemaVersion?: string;
  jobState?: string;
  queueName?: string;
  availableAt?: string;
  attemptCount?: number;
  maxAttempts?: number;
  waitReasonCode?: string;
  waitReason?: WorkflowRunAdmissionWaitReason | null;
  deadLetteredAt?: string | null;
  updatedAt?: string;
};

export type WorkflowBackfillLaunch = {
  schemaVersion?: string;
  launchId: string;
  triggerId: string;
  previewId?: string;
  sourceType?: string;
  rangeStart?: string;
  rangeEnd?: string;
  timezone?: string;
  partitionUnit?: string;
  runOrder?: string;
  reprocessBehavior?: string;
  partitionCount?: number;
  state?: string;
  actor?: string;
  createdAt?: string;
  updatedAt?: string;
  range?: WorkflowBackfillRange;
  launchStrategy?: string;
  concurrency?: WorkflowBackfillConcurrency;
  partitionSummary?: WorkflowBackfillPartitionSummary;
  operationCapabilities?: {
    cancel?: boolean;
    cancelReason?: string;
    replay?: boolean;
    deadLetter?: boolean;
    concurrencyEnforced?: boolean;
  };
};

export type WorkflowBackfillPreviewPartition = {
  partitionId?: string;
  partitionKey?: string;
  index?: number;
  window?: {
    start?: string;
    end?: string;
    timezone?: string;
    semantics?: string;
  };
  action?: string;
  existingState?: WorkflowBackfillPartition["existingState"];
  reprocessDecision?: WorkflowBackfillPartition["reprocessDecision"];
};

export type WorkflowBackfillPreview = {
  schemaVersion?: string;
  previewId: string;
  triggerId: string;
  sourceType?: string;
  triggerEnabled?: boolean;
  pipelineId?: string;
  launchSupported?: boolean;
  reason?: string;
  range?: WorkflowBackfillRange;
  runOrder?: string;
  reprocessBehavior?: string;
  launchStrategy?: string;
  estimatedRunCount?: number;
  returnedRunCount?: number;
  creationRunCount?: number;
  skippedRunCount?: number;
  blockedActiveRunCount?: number;
  truncated?: boolean;
  concurrency?: WorkflowBackfillConcurrency & {
    estimatedBatches?: number;
  };
  partitions?: WorkflowBackfillPreviewPartition[];
};

export type WorkflowBackfillPartition = {
  partitionId: string;
  launchId?: string;
  triggerId?: string;
  partitionKey?: string;
  index?: number;
  window?: {
    start?: string;
    end?: string;
    semantics?: string;
  };
  cursor?: string;
  idempotencyKey?: string;
  triggerEventId?: string | null;
  runId?: string | null;
  state?: string;
  action?: "create" | "skip" | string;
  blockedReason?: string | null;
  existingState?: {
    partitionId?: string;
    launchId?: string;
    partitionKey?: string;
    state?: string;
    runId?: string | null;
    runStatus?: string | null;
    runStage?: string | null;
    updatedAt?: string;
  } | null;
  reprocessDecision?: {
    behavior?: string;
    reason?: string;
  } | null;
  runSpecHash?: string;
  triggerEventType?: string | null;
  dispatch?: {
    state?: string;
    requestId?: string;
    error?: unknown;
  } | null;
  run?: {
    runId?: string;
    status?: string;
    stage?: string;
    lastUpdatedAt?: string;
    admission?: WorkflowRunAdmissionSummary | null;
  } | null;
  error?: unknown;
  createdAt?: string;
  updatedAt?: string;
};

export type WorkflowBackfillLaunchList = {
  schemaVersion?: string;
  items: WorkflowBackfillLaunch[];
};

export type WorkflowBackfillLaunchDetail = WorkflowBackfillLaunch & {
  partitions?: WorkflowBackfillPartition[];
};

export type WorkflowBackfillLaunchListResponse = {
  data: WorkflowBackfillLaunchList;
};

export type WorkflowBackfillLaunchDetailResponse = {
  data: WorkflowBackfillLaunchDetail;
};

export type WorkflowBackfillPreviewResponse = {
  data: WorkflowBackfillPreview;
};

export type WorkflowBackfillLaunchResponse = {
  data: WorkflowBackfillLaunchDetail;
};

export type WorkflowBackfillCancelResponse = {
  data: {
    schemaVersion?: string;
    launchId: string;
    triggerId?: string;
    state?: string;
    requestedCancelCount?: number;
    pendingCancelRequestedCount?: number;
    skippedPartitionCount?: number;
    requested?: Array<Record<string, unknown>>;
    pendingRequested?: Array<Record<string, unknown>>;
    skipped?: Array<Record<string, unknown>>;
    detail?: WorkflowBackfillLaunchDetail;
  };
};
