export type ArtifactLifecycleBackendUsage = {
  storageObjectCount?: number;
  bytes?: number;
};

export type ArtifactLifecycleQuota = {
  quotaBytes?: number;
  usedBytes?: number;
  remainingBytes?: number;
  overageBytes?: number;
  usedPercent?: number | null;
};

export type WorkflowArtifactLifecycleUsage = {
  schemaVersion?: string;
  checkedAt?: string;
  artifactCount?: number;
  activeArtifactCount?: number;
  deletedArtifactCount?: number;
  activeStorageObjectCount?: number;
  activeBytes?: number;
  deletedBytes?: number;
  ledgerOnlyMaterializationCount?: number;
  ledgerOnlyActiveBytes?: number;
  byBackend?: Record<string, ArtifactLifecycleBackendUsage>;
  quota?: ArtifactLifecycleQuota;
};

export type WorkflowArtifactLifecycleControllerPolicy = {
  retentionDays?: number;
  eligibleRunStatuses?: string[];
  quotaBytes?: number | null;
  maxDeleteBytesPerTick?: number | null;
};

export type WorkflowArtifactLifecycleControllerUsage = {
  activeBytes?: number;
  activeStorageObjectCount?: number;
  quotaOverageBytes?: number;
};

export type WorkflowArtifactLifecyclePolicyDecision = {
  decision?: string;
  reasonCode?: string;
  message?: string;
  deletionAuthorized?: boolean;
  deleteConfirmationRequired?: boolean;
  candidateCount?: number;
  deleteBytes?: number;
};

export type WorkflowArtifactLifecycleRetentionReason = {
  reason?: string;
  groupCount?: number;
  artifactCount?: number;
  runCount?: number;
  bytes?: number;
};

export type WorkflowArtifactLifecycleRetentionHolds = {
  schemaVersion?: string;
  protectedGroupCount?: number;
  protectedBytes?: number;
  reasonCount?: number;
  reasons?: WorkflowArtifactLifecycleRetentionReason[];
};

export type WorkflowArtifactLifecycleBatchSafety = {
  schemaVersion?: string;
  maxDeleteBytes?: number | null;
  maxDeleteBytesApplied?: boolean;
  candidateCount?: number;
  candidateBytes?: number;
  candidateArtifactCount?: number;
  candidateRunCount?: number;
  limitedGroupCount?: number;
  limitedBytes?: number;
};

export type WorkflowArtifactLifecycleGcPreviewSummary = {
  planId?: string;
  planFingerprint?: string;
  candidateCount?: number;
  deleteBytes?: number;
  protectedCount?: number;
  protectedBytes?: number;
  candidateArtifactCount?: number;
  candidateRunCount?: number;
};

export type WorkflowArtifactLifecycleControllerTick = {
  tickId?: string;
  evidenceId?: string;
  evidenceSeq?: number;
  occurredAt?: string;
  evaluatedAt?: string;
  executionMode?: string;
  deleteConfirmationRequired?: boolean;
  policy?: WorkflowArtifactLifecycleControllerPolicy;
  usage?: WorkflowArtifactLifecycleControllerUsage;
  policyDecision?: WorkflowArtifactLifecyclePolicyDecision;
  retentionHolds?: WorkflowArtifactLifecycleRetentionHolds;
  batchSafety?: WorkflowArtifactLifecycleBatchSafety;
  gcPreview?: WorkflowArtifactLifecycleGcPreviewSummary;
};

export type WorkflowArtifactLifecycleControllerTickList = {
  schemaVersion?: string;
  items: WorkflowArtifactLifecycleControllerTick[];
};

export type WorkflowArtifactGcPreviewRequest = {
  serverId?: string;
  retentionDays?: number;
  eligibleRunStatuses?: string[];
  maxDeleteBytes?: number;
  reason?: string;
  actor?: string;
};

export type WorkflowArtifactGcPlanPolicy = {
  retentionDays?: number;
  eligibleRunStatuses?: string[];
  maxDeleteBytes?: number | null;
  reason?: string;
};

export type WorkflowArtifactGcPlanItem = {
  storageBackend?: string;
  sizeBytes?: number;
  artifactCount?: number;
  runCount?: number;
  materializationCount?: number;
  terminalAt?: string;
  retentionUntil?: string;
  reason?: string;
  reasons?: string[];
  payloadDeleted?: boolean;
};

export type WorkflowArtifactGcPlan = {
  schemaVersion?: string;
  planId?: string;
  planFingerprint?: string;
  plannedAt?: string;
  cutoffAt?: string;
  policy?: WorkflowArtifactGcPlanPolicy;
  candidateCount?: number;
  deleteBytes?: number;
  protectedCount?: number;
  protectedBytes?: number;
  candidates?: WorkflowArtifactGcPlanItem[];
  protected?: WorkflowArtifactGcPlanItem[];
};

export type WorkflowArtifactGcRunRequest = WorkflowArtifactGcPreviewRequest & {
  confirmation: string;
  planFingerprint: string;
};

export type WorkflowArtifactGcRunError = {
  storageBackend?: string;
  errorCode?: string;
};

export type WorkflowArtifactGcRunResult = {
  schemaVersion?: string;
  planId?: string;
  executedAt?: string;
  status?: string;
  deletedCount?: number;
  deletedBytes?: number;
  errorCount?: number;
  evidenceId?: string;
  deleted?: WorkflowArtifactGcPlanItem[];
  errors?: WorkflowArtifactGcRunError[];
  plan?: WorkflowArtifactGcPlan;
};
