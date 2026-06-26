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

export type WorkflowArtifactLifecycleControllerRunOnceRequest = {
  serverId?: string;
  retentionDays?: number;
  eligibleRunStatuses?: string[];
  quotaBytes?: number;
  maxDeleteBytesPerTick?: number;
  actor?: string;
  reason?: string;
};

export type WorkflowArtifactLifecycleControllerRunOnceResult = WorkflowArtifactLifecycleControllerTick & {
  schemaVersion?: string;
  controlsExposed?: boolean;
  deleteExecutionAuthorized?: boolean;
};

export type WorkflowArtifactLifecycleControllerRunOnceResponse = {
  data: WorkflowArtifactLifecycleControllerRunOnceResult;
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

export type WorkflowResultPackageByteGcPreviewRequest = {
  serverId?: string;
  retentionDays?: number;
  maxDeleteBytes?: number;
  scanLimit?: number;
  actor?: string;
  reason?: string;
};

export type WorkflowResultPackageByteGcPolicy = {
  retentionDays?: number;
  maxDeleteBytes?: number | null;
  reasonProvided?: boolean;
  reasonRedacted?: boolean;
  scanLimit?: number;
  deletionAuthorized?: boolean;
  deleteConfirmationAccepted?: boolean;
};

export type WorkflowResultPackageByteGcItem = {
  itemIndex?: number;
  classification?: string;
  reason?: string;
  artifactPayloadMode?: string;
  lifecycleState?: string;
  packageBytesState?: string;
  sizeBytes?: number;
  retiredAtPresent?: boolean;
  checksumVerified?: boolean;
  packageFileDeleted?: boolean;
  evidenceId?: string;
  errorCode?: string;
};

export type WorkflowResultPackageByteGcPlan = {
  schemaVersion?: string;
  previewedAt?: string;
  cutoffAt?: string;
  planFingerprint?: string;
  policy?: WorkflowResultPackageByteGcPolicy;
  scannedCount?: number;
  candidateCount?: number;
  deleteBytes?: number;
  protectedCount?: number;
  protectedBytes?: number;
  reasonCounts?: Record<string, number>;
  candidates?: WorkflowResultPackageByteGcItem[];
  protected?: WorkflowResultPackageByteGcItem[];
  redactionPolicy?: Record<string, boolean>;
};

export type WorkflowResultPackageByteGcRunRequest = WorkflowResultPackageByteGcPreviewRequest & {
  confirmation: string;
  planFingerprint: string;
};

export type WorkflowResultPackageByteGcRunResult = {
  schemaVersion?: string;
  executedAt?: string;
  status?: string;
  planFingerprint?: string;
  deletedCount?: number;
  deletedBytes?: number;
  errorCount?: number;
  evidenceId?: string;
  deleteConfirmationAccepted?: boolean;
  deleted?: WorkflowResultPackageByteGcItem[];
  errors?: WorkflowResultPackageByteGcItem[];
  plan?: WorkflowResultPackageByteGcPlan;
  redactionPolicy?: Record<string, boolean>;
};
