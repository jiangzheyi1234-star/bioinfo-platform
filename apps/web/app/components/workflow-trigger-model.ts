export type WorkflowTriggerSpec = Record<string, unknown>;

export type WorkflowTriggerRunSpec = Record<string, unknown>;

export type WorkflowTriggerDefinitionSource =
  | "manual"
  | "cron"
  | "webhook"
  | "dataset"
  | "file"
  | "database_ready"
  | "backfill";

export type WorkflowTriggerWebhookProvider = "github" | "slack" | "stripe";

export type WorkflowTriggerReadinessWatchSpec = {
  enabled: boolean;
  adapter: "local_path" | "database_registry";
  path?: string;
  stabilitySeconds?: number;
};

export type WorkflowTriggerDefinitionCreateRequest = {
  name: string;
  sourceType: WorkflowTriggerDefinitionSource;
  serverId: string;
  enabled: boolean;
  runSpec: {
    pipelineId: string;
    projectId?: string;
    pipelineVersion?: string;
    workflowRevisionId?: string;
    inputs?: Array<{ uploadId: string; filename: string }>;
    params?: Record<string, string>;
  };
  triggerSpec:
    | { mode: "manual" }
    | { cron: string; timezone: string; concurrencyPolicy: "Forbid" | "Allow" }
    | {
        provider: WorkflowTriggerWebhookProvider;
        eventMatch: { eventTypes: string[]; actions?: string[] };
        signature: {
          provider: WorkflowTriggerWebhookProvider;
          required: true;
          secretRef: string;
          toleranceSeconds?: number;
        };
      }
    | { resource: { type: "dataset" | "file" | "database"; id: string; uri?: string; watch?: WorkflowTriggerReadinessWatchSpec } }
    | { partitionUnit: "hour" | "day" };
};

export type WorkflowTriggerAuthoritativeIngress =
  | "manual-event-api"
  | "cron-scheduler"
  | "webhook-inbox"
  | "readiness-api"
  | "backfill-launch"
  | "unsupported";

export type WorkflowTriggerOperatorAction = "submit-manual-event" | "preview-backfill";

export type WorkflowTriggerContractBlocker =
  | "trigger-disabled"
  | "cron-scheduler-owned"
  | "webhook-inbox-owned"
  | "readiness-api-owned"
  | "backfill-launch-owned"
  | "unknown-trigger-source";

export type WorkflowTriggerContract = {
  schemaVersion?: string;
  sourceType?: string;
  authoritativeIngress?: WorkflowTriggerAuthoritativeIngress;
  provenanceStamped?: boolean;
  immutableTriggerEventRequired?: boolean;
  rawPayloadExported?: boolean;
  supportedOperatorActions?: WorkflowTriggerOperatorAction[];
  blockers?: WorkflowTriggerContractBlocker[];
};

export type WorkflowTrigger = {
  schemaVersion?: string;
  triggerId: string;
  name?: string;
  sourceType?: string;
  serverId?: string;
  pipelineId?: string;
  enabled?: boolean;
  triggerSpec?: WorkflowTriggerSpec;
  runSpec?: WorkflowTriggerRunSpec;
  triggerContract?: WorkflowTriggerContract;
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

export type WorkflowTriggerSchedulerTickCounts = {
  checked?: number;
  skipped?: number;
  due?: number;
  submitted?: number;
  replayed?: number;
  overlapSkipped?: number;
  eventCount?: number;
  dispatchRunCount?: number;
  errorCount?: number;
  advanced?: number;
  pending?: number;
  launchCount?: number;
  errorTypes?: Record<string, number>;
  reasonCodes?: Record<string, number>;
  stateCounts?: Record<string, number>;
};

export type WorkflowTriggerSchedulerTick = {
  tickId: string;
  evidenceId?: string;
  evidenceSeq?: number;
  occurredAt?: string;
  evaluatedAt?: string;
  limit?: number;
  controlsExposed?: boolean;
  cron?: WorkflowTriggerSchedulerTickCounts;
  backfills?: WorkflowTriggerSchedulerTickCounts;
};

export type WorkflowTriggerSchedulerRunOnceResult = {
  schemaVersion?: string;
  tickId: string;
  evidenceId?: string;
  evaluatedAt?: string;
  limit?: number;
  controlsExposed?: boolean;
  cron?: WorkflowTriggerSchedulerTickCounts;
  backfills?: WorkflowTriggerSchedulerTickCounts;
};

export type WorkflowTriggerReadinessWatcherTickCounts = {
  checked?: number;
  skipped?: number;
  missing?: number;
  ready?: number;
  submitted?: number;
  unchanged?: number;
  observationCount?: number;
  errorCount?: number;
  stateCounts?: Record<string, number>;
  sourceTypeCounts?: Record<string, number>;
  resourceTypeCounts?: Record<string, number>;
  watcherAdapterCounts?: Record<string, number>;
  dispatchStateCounts?: Record<string, number>;
  errorTypes?: Record<string, number>;
  reasonCodes?: Record<string, number>;
};

export type WorkflowTriggerReadinessWatcherRunOnceResult = {
  schemaVersion?: string;
  runOnceId?: string;
  evaluatedAt?: string;
  limit?: number;
  controlsExposed?: boolean;
  readiness?: WorkflowTriggerReadinessWatcherTickCounts;
};

export type WorkflowTriggerList = {
  schemaVersion?: string;
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

export type WorkflowTriggerSchedulerTickList = {
  schemaVersion?: string;
  items: WorkflowTriggerSchedulerTick[];
};

export type WorkflowTriggerSchedulerTickListResponse = {
  data: WorkflowTriggerSchedulerTickList;
};

export type WorkflowTriggerSchedulerRunOnceResponse = {
  data: WorkflowTriggerSchedulerRunOnceResult;
};

export type WorkflowTriggerReadinessWatcherRunOnceResponse = {
  data: WorkflowTriggerReadinessWatcherRunOnceResult;
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

export type WorkflowTriggerCreateResponse = {
  data: WorkflowTrigger;
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
