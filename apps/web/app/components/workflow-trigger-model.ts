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

export type WorkflowTriggerDispatchRun = {
  runId?: string;
  status?: string;
  stage?: string;
  lastUpdatedAt?: string;
  admission?: WorkflowRunAdmissionSummary | null;
};

export type WorkflowTriggerDispatch = {
  dispatchId?: string;
  triggerEventId?: string;
  triggerId?: string;
  state?: string;
  runId?: string | null;
  run?: WorkflowTriggerDispatchRun | null;
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

export type WorkflowTriggerInboxEvent = {
  inboxEventId: string;
  triggerId?: string;
  sourceType?: string;
  source?: string;
  eventType?: string;
  eventId?: string;
  correlationId?: string | null;
  cursor?: string | null;
  dedupeKey?: string;
  payloadHash?: string;
  payloadSizeBytes?: number;
  signatureState?: string;
  signatureDetails?: Record<string, unknown>;
  rawBodySha256?: string;
  rawBodySizeBytes?: number;
  rawContentType?: string;
  rawHeaderNames?: string[];
  state?: string;
  deliveryCount?: number;
  triggerEventId?: string | null;
  runId?: string | null;
  failureCode?: string | null;
  error?: unknown;
  receivedAt?: string;
  updatedAt?: string;
  deadLetteredAt?: string | null;
};

export type WorkflowTriggerReadinessObservation = {
  triggerId?: string;
  sourceType?: string;
  resourceType?: string;
  resourceIdentity?: {
    type?: string;
    idPresent?: boolean;
    idLength?: number;
    idHash?: string;
  };
  watcherAdapter?: string;
  observationHash?: string;
  observedVersion?: string;
  observedChecksum?: string;
  observedState?: string;
  dispatchState?: string;
  triggerEventId?: string | null;
  runId?: string | null;
  error?: {
    errorType?: string;
    reasonCode?: string;
  } | null;
  observedAt?: string;
  createdAt?: string;
  updatedAt?: string;
  resourceUriPresent?: boolean;
};

export type WorkflowTriggerReadinessObservationEnvelope = {
  schemaVersion?: string;
  triggerId?: string;
  sourceType?: string;
  observation?: WorkflowTriggerReadinessObservation | null;
};

export type WorkflowTriggerList = {
  items: WorkflowTrigger[];
};

export type WorkflowTriggerEventList = {
  items: WorkflowTriggerEvent[];
};

export type WorkflowTriggerInboxEventList = {
  schemaVersion?: string;
  items: WorkflowTriggerInboxEvent[];
};

export type WorkflowTriggerReadinessObservationResponse = {
  data: WorkflowTriggerReadinessObservationEnvelope;
};

export type WorkflowTriggerInboxReplayResult = {
  schemaVersion?: string;
  inbox?: WorkflowTriggerInboxEvent;
  event?: WorkflowTriggerEvent;
  run?: WorkflowTriggerDispatchRun;
  replayed?: boolean;
};

export type WorkflowTriggerEventSubmitResult = {
  schemaVersion?: string;
  event?: WorkflowTriggerEvent;
  run?: WorkflowTriggerDispatchRun;
  submitted?: boolean;
};

export type WorkflowTriggerListResponse = {
  data: WorkflowTriggerList;
};

export type WorkflowTriggerEventListResponse = {
  data: WorkflowTriggerEventList;
};

export type WorkflowTriggerInboxEventListResponse = {
  data: WorkflowTriggerInboxEventList;
};

export type WorkflowTriggerInboxReplayResponse = {
  data: WorkflowTriggerInboxReplayResult;
};

export type WorkflowTriggerEventSubmitResponse = {
  data: WorkflowTriggerEventSubmitResult;
};
