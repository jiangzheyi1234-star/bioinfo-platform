export type WorkflowTriggerSpec = Record<string, unknown>;

export type WorkflowTriggerRunSpec = Record<string, unknown>;

export type WorkflowTrigger = {
  triggerId: string;
  name?: string;
  sourceType?: string;
  serverId?: string;
  pipelineId?: string;
  enabled?: boolean;
  triggerSpec?: WorkflowTriggerSpec;
  runSpec?: WorkflowTriggerRunSpec;
  createdBy?: string;
  createdAt?: string;
  updatedAt?: string;
};

export type WorkflowTriggerEventPayload = {
  scheduledAt?: string;
  schedule?: {
    cron?: string;
    timezone?: string;
  };
  scheduleVersion?: string;
  backfill?: Record<string, unknown>;
  eventContext?: Record<string, unknown>;
  resource?: Record<string, unknown>;
  state?: string;
  observedAt?: string;
  payload?: unknown;
};

export type WorkflowTriggerDispatch = {
  dispatchId?: string;
  triggerEventId?: string;
  triggerId?: string;
  state?: string;
  runId?: string | null;
  requestId?: string;
  idempotencyKey?: string;
  error?: unknown;
  createdAt?: string;
  updatedAt?: string;
};

export type WorkflowTriggerEvent = {
  triggerEventId: string;
  triggerId?: string;
  sourceType?: string;
  eventType?: string;
  externalEventId?: string;
  idempotencyKey?: string;
  payloadHash?: string;
  payload?: WorkflowTriggerEventPayload;
  cursor?: string;
  createdAt?: string;
  dispatch?: WorkflowTriggerDispatch | null;
  created?: boolean;
};

export type WorkflowTriggerList = {
  items: WorkflowTrigger[];
};

export type WorkflowTriggerEventList = {
  items: WorkflowTriggerEvent[];
};

export type WorkflowTriggerListResponse = {
  data: WorkflowTriggerList;
};

export type WorkflowTriggerEventListResponse = {
  data: WorkflowTriggerEventList;
};
