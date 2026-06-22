import type {
  CapabilityBundleGate,
  CapabilityBundleStatus,
  CapabilityBundleSummary,
  MissingToolResource,
  SnakemakeWrapperMatch,
  ToolCandidatePreparePayload,
  ToolCandidateQualityTier,
  ToolCandidateSourceRef,
  ToolContract,
  ToolContractState,
  ToolSearchItem,
} from "./tools-page-core-model";

export type ToolSearchResponse = {
  data: {
    items: ToolSearchItem[];
    query: string;
    online: boolean;
    cached?: boolean;
    total?: number;
    page?: number;
    pageSize?: number;
    hasMore?: boolean;
    complete?: boolean;
    localIndexAvailable?: boolean;
    onlineUnavailableReason?: string;
  };
};

export type ToolCatalogQualityCounts = {
  discovered: number;
  draftRunnable: number;
  workflowReady: number;
  productionEnabled: number;
};

export type ToolCandidateSourceCounts = {
  condaPackages: number;
  snakemakeWrappers: number;
  toolProfiles: number;
  registeredToolIndex?: number;
};

export type ToolCandidateAddableDraftCounts = ToolCandidateSourceCounts & {
  total: number;
};

export type RegisteredToolIndexCandidate = {
  candidateId: string;
  candidateKind: "registered-tool-index" | string;
  toolId: string;
  toolRevisionId?: string;
  name: string;
  source?: string;
  packageSpec?: string;
  sourceRef?: ToolCandidateSourceRef;
  qualityTier?: ToolCandidateQualityTier;
  toolContract?: ToolContract;
  validationSummary?: Record<string, unknown>;
  qualityScore?: number;
  upgradeAvailable?: boolean;
};

export type ToolCandidateCatalogItem = ToolSearchItem | SnakemakeWrapperMatch | ToolProfileCandidate | RegisteredToolIndexCandidate;

export type ToolCandidateCatalog = {
  items: ToolCandidateCatalogItem[];
  query: string;
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
  sourceCounts: ToolCandidateSourceCounts;
  addableDraftCounts: ToolCandidateAddableDraftCounts;
  qualityCounts: ToolCatalogQualityCounts;
};

export type ToolCandidateCatalogResponse = {
  data: ToolCandidateCatalog;
};

export type ToolCatalogTargetResult = {
  target: number;
  actual: number;
  passed: boolean;
  remaining: number;
};

export type ToolCatalogValidationPriority = {
  score: number;
  reasons?: string[];
};

export type ToolCatalogValidationEvidence = {
  snakemakeWrapperCount?: number;
  snakemakeWrapperPaths?: string[];
  wrapperContractHintCount?: number;
  wrapperContractHintFields?: string[];
  wrapperCondaDependencies?: string[];
  semanticPortFields?: string[];
  semanticData?: string[];
  semanticFormats?: string[];
};

export type ToolCatalogExecutionGate = {
  currentState: string;
  requiredState: string;
  canAddStep: boolean;
  nextAction: string;
  reason?: string;
  sourceOfTruth?: string;
  toolRevisionId?: string;
  toolId?: string;
};

export type ToolCatalogValidationPlan = {
  planVersion: string;
  requiredState: string;
  submit?: {
    method: string;
    path: string;
    payloadRef: string;
  };
  poll?: {
    method: string;
    pathTemplate: string;
    jobIdField: string;
  };
  terminalStatuses?: {
    success?: string[];
    waiting?: string[];
    failure?: string[];
  };
  stages?: Array<{
    id: string;
    contractStatusKey?: string;
    evidence?: string;
  }>;
  successCriteria?: Array<Record<string, string | boolean>>;
  readinessBoundary?: string;
};

export type ToolCatalogLatestPrepareJob = {
  jobId: string;
  toolId: string;
  status: string;
  stage: string;
  message?: string;
  errorCode?: string;
  updatedAt?: string;
  resultState?: string;
  workflowReady?: boolean;
  productionEnabled?: boolean;
  validationResultId?: string;
  evidenceId?: string;
  createdAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  cancelledAt?: string | null;
};

export type ToolCatalogValidationQueueItem = {
  candidateId: string;
  candidateKind: string;
  profileId: string;
  profileVersion: number;
  toolNames: string[];
  currentState: string;
  requiredState: string;
  action: string;
  priority?: ToolCatalogValidationPriority;
  evidence?: ToolCatalogValidationEvidence;
  executionGate?: ToolCatalogExecutionGate;
  validationPlan?: ToolCatalogValidationPlan;
  latestPrepareJob?: ToolCatalogLatestPrepareJob;
  preparePayload?: ToolCandidatePreparePayload;
};

export type ToolCatalogValidationQueue = {
  target: string;
  requiredState: string;
  remaining: number;
  available: number;
  items: ToolCatalogValidationQueueItem[];
};

export type ToolCatalogProductionQueueItem = {
  toolId: string; toolRevisionId?: string; toolName: string; currentState: string; requiredState: string; action: string;
  executionGate?: ToolCatalogExecutionGate & { canPromote?: boolean };
  productionPlan?: { acceptedEvidenceTypes?: string[]; requiredEvidenceFields?: string[]; submit?: { pathTemplate?: string } };
};

export type ToolCatalogProductionQueue = { target: string; requiredState: string; remaining: number; available: number; items: ToolCatalogProductionQueueItem[] };

export type ToolPrepareJobStatusCounts = Partial<Record<ToolPrepareJobStatus, number>> & {
  queued?: number;
  running?: number;
  succeeded?: number;
  failed?: number;
  waiting_resource?: number;
  cancelled?: number;
  exhausted?: number;
};

export type ToolPrepareJobQueue = {
  items: ToolPrepareJob[];
  total: number;
  limit: number;
  offset: number;
  statusCounts: ToolPrepareJobStatusCounts;
};

export type ToolCatalogTargetAcceptance = {
  targetName: string;
  targetPlatform: string;
  complete: boolean;
  blockedTargets: string[];
  targets: {
    discovered: ToolCatalogTargetResult;
    addableDraft: ToolCatalogTargetResult;
    snakemakeRenderable: ToolCatalogTargetResult;
    workflowReady: ToolCatalogTargetResult;
    productionEnabled: ToolCatalogTargetResult;
  };
  catalog?: {
    registeredToolCounts?: {
      total: number;
      workflowReady: number;
      productionEnabled: number;
    };
  };
  validationQueue?: ToolCatalogValidationQueue;
  productionQueue?: ToolCatalogProductionQueue;
  prepareJobQueue?: ToolPrepareJobQueue;
};

export type ToolCatalogTargetAcceptanceResponse = {
  data: ToolCatalogTargetAcceptance;
};

export type CapabilityGraphSelectionPolicy = {
  sourceOfTruth?: string;
  readinessSourceOfTruth?: string;
  canAddStepStates?: string[];
  blockedReason?: string;
};

export type CapabilityGraphSemanticNode = {
  id: string;
  kind: string;
  profileId?: string;
  packId?: string;
  workflowStage?: string;
  operation?: string;
  agentSelectable?: boolean;
  toolRevisionId?: string;
  name?: string;
  value?: string;
  type?: string;
  kindLabel?: string;
  mimeType?: string;
  data?: string;
  format?: string;
  resource?: string;
  required?: boolean;
  capabilityId?: string;
  capabilityBundle?: CapabilityBundleSummary;
  resourceRequirements?: Array<{
    resourceKey?: string;
    type?: string;
    required?: boolean;
    configKey?: string;
    acceptedTemplates?: string[];
    acceptedCapabilities?: string[];
  }>;
};

export type CapabilityGraphSnapshot = {
  contractVersion: "capability-graph-snapshot-v1" | string;
  query: string;
  targetPlatform: string;
  profileCount: number;
  packIds: string[];
  capabilityBundleVersion?: "capability-bundle-v1" | string;
  catalog: ToolCandidateCatalog;
  semanticGraph: {
    contractVersion?: string;
    nodes: CapabilityGraphSemanticNode[];
    edges: Array<{ from: string; to: string; kind: string }>;
    agentSelectableProfileIds: string[];
  };
  capabilityBundles?: CapabilityBundleSummary[];
  capabilityBundleGate?: CapabilityBundleGate;
  registeredTools: AddedTool[];
  registeredToolCounts: {
    total: number;
    workflowReady: number;
    productionEnabled: number;
  };
  agentSelectableTools: AddedTool[];
  agentSelectableProfileIds: string[];
  selectionPolicy: CapabilityGraphSelectionPolicy;
  targetAcceptance?: ToolCatalogTargetAcceptance;
  targetSummary?: {
    complete?: boolean;
    blockedTargets?: string[];
    targets?: ToolCatalogTargetAcceptance["targets"];
  };
  validationQueue?: ToolCatalogValidationQueue;
  productionQueue?: ToolCatalogProductionQueue;
  prepareJobQueue?: ToolPrepareJobQueue;
};

export type CapabilityGraphSnapshotResponse = {
  data: CapabilityGraphSnapshot;
};

export type SnakemakeWrapperCatalog = {
  items: SnakemakeWrapperMatch[];
  query: string;
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
  addableTotal: number;
  qualityCounts: ToolCatalogQualityCounts;
  sourceRef?: {
    type?: string;
    repository?: string;
    ref?: string;
  };
};

export type SnakemakeWrapperCatalogResponse = {
  data: SnakemakeWrapperCatalog;
};

export type ToolProfileWrapperEvidence = {
  wrapperRepository?: string;
  wrapperRef?: string;
  wrapperPath: string;
  wrapperIdentifier?: string;
  wrapperUrl?: string;
  environmentUrl?: string;
  sourceRef?: ToolCandidateSourceRef;
};

export type ToolProfileCandidate = {
  candidateId?: string;
  candidateKind?: string;
  contractState?: ToolContractState | string;
  qualityTier?: ToolCandidateQualityTier;
  sourceRef?: ToolCandidateSourceRef;
  profileId: string;
  profileVersion: number;
  toolNames: string[];
  preferredWrapperPaths: string[];
  snakemakeWrappers?: ToolProfileWrapperEvidence[];
  snakemakeWrapperCount?: number;
  preparePayload?: ToolCandidatePreparePayload;
};

export type ToolProfileCatalog = {
  items: ToolProfileCandidate[];
  query: string;
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
  addableTotal: number;
  qualityCounts: ToolCatalogQualityCounts;
  sourceRef?: ToolCandidateSourceRef;
};

export type ToolProfileCatalogResponse = {
  data: ToolProfileCatalog;
};

export type AddedTool = ToolSearchItem & {
  selectedVersion: string;
  selectedPackageSpec: string;
  status?: string;
  message?: string;
  createdAt?: string;
  updatedAt?: string;
  publishedAt?: string | null;
  lastCheckedAt?: string | null;
  capabilityBundle?: CapabilityBundleSummary;
  capabilityBundleStatus?: CapabilityBundleStatus;
};

export type ToolPrepareJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "waiting_resource" | "exhausted" | string;

export type ToolPrepareJobEvent = {
  eventId: string;
  stage: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
  details?: Record<string, unknown>;
  createdAt: string;
};

export type ToolPrepareJob = {
  jobId: string;
  status: ToolPrepareJobStatus;
  stage: string;
  message: string;
  toolId: string;
  request?: { id?: string; name?: string; packageSpec?: string } & Record<string, unknown>;
  result?: (AddedTool & { validationResultId?: string; evidenceId?: string }) | null;
  errorCode?: string | null;
  validationResultId?: string;
  evidenceId?: string;
  missingResources?: MissingToolResource[];
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  cancelledAt?: string | null;
  events?: ToolPrepareJobEvent[];
};

export type ToolPrepareJobResponse = {
  data: ToolPrepareJob;
};

export type ToolValidationQueuePrepareItem = {
  candidateId: string;
  profileId: string;
  toolId: string;
  jobId: string;
  status: ToolPrepareJobStatus;
  stage: string;
  message?: string;
  createdAt?: string;
  updatedAt?: string;
  pollPath?: string;
  resultState?: string;
  workflowReady?: boolean;
};

export type ToolValidationBatchPlan = {
  planVersion: string;
  status: "queued" | "blocked" | "empty" | string;
  targetPlatform: string;
  requested: number;
  queuedCount: number;
  skippedCount: number;
  jobIds: string[];
  poll: {
    method: string;
    path: string;
    query: {
      status: string;
      limit: number;
      offset: number;
    };
  };
  terminalStatuses: ToolPrepareJobStatus[];
  activeStatuses: ToolPrepareJobStatus[];
};

export type ToolValidationQueuePrepareResult = {
  targetPlatform: string;
  requested: number;
  consideredCount: number;
  queuedCount: number;
  skippedCount: number;
  queued: ToolValidationQueuePrepareItem[];
  skipped: Array<Record<string, unknown>>;
  batchPlan?: ToolValidationBatchPlan;
  remainingWorkflowReady: number;
};

export type ToolValidationQueuePrepareResponse = {
  data: ToolValidationQueuePrepareResult;
};

export type ToolsResponse = {
  data: {
    items: AddedTool[];
  };
};
