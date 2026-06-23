export type WorkflowBackfillPartitionSummary = {
  partitionCount?: number;
  states?: Record<string, number>;
  submittedRunCount?: number;
  failedPartitionCount?: number;
  pendingPartitionCount?: number;
  replayedPartitionCount?: number;
};

export type WorkflowBackfillConcurrency = {
  limit?: number | null;
  partitionCount?: number;
  enforced?: boolean;
};

export type WorkflowBackfillRange = {
  start?: string;
  end?: string;
  timezone?: string;
  partitionUnit?: string;
  semantics?: string;
  runOrder?: string;
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
