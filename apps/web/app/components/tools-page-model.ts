export type ToolCandidateQualityTier = "discovered" | "draft-runnable" | "workflow-ready" | "production-enabled" | string;

export type ToolCandidateSourceRef = {
  type?: string;
  channel?: string;
  name?: string;
  profileId?: string;
  version?: string;
  profileCount?: string;
  toolId?: string;
  toolRevisionId?: string;
  repository?: string;
  ref?: string;
  path?: string;
  url?: string;
};

export type ToolSearchItem = {
  id: string;
  candidateId?: string;
  candidateKind?: string;
  qualityTier?: ToolCandidateQualityTier;
  sourceRef?: ToolCandidateSourceRef;
  toolRevisionId?: string;
  revision?: number;
  name: string;
  summary: string;
  source: "bioconda" | "conda-forge" | string;
  sourceLabel: string;
  packageSpec: string;
  version?: string;
  latestVersion?: string;
  versions?: string[];
  sourceUrl?: string;
  platforms?: string[];
  targetPlatform?: string;
  targetPlatformSupported?: boolean;
  testCommand?: string;
  ruleTemplate?: RuleSpecTemplate;
  ruleSpecDraft?: RuleSpecDraft;
  preparePayload?: ToolCandidatePreparePayload;
  capabilities?: ToolCapability[];
  snakemakeWrappers?: SnakemakeWrapperMatch[];
  snakemakeWrapperCount?: number;
  contractStatus?: ToolContractStatus;
  toolContract?: ToolContract;
  missingResources?: MissingToolResource[];
};

export type ToolCapabilitySlot = {
  name: string;
  type?: string;
  kind?: string;
  mimeType?: string;
  data?: string;
  format?: string;
  edamData?: string;
  edamFormat?: string;
  required?: boolean;
  primary?: boolean;
};

export type ToolCapability = {
  id: string;
  label?: string;
  operation?: string;
  topics?: string[];
  inputs?: ToolCapabilitySlot[];
  outputs?: ToolCapabilitySlot[];
};

export type ToolCandidatePreparePayload = {
  id?: string;
  name?: string;
  source?: string;
  sourceLabel?: string;
  packageSpec?: string;
  version?: string;
  latestVersion?: string;
  targetPlatform?: string;
  targetPlatformSupported?: boolean;
  capabilities?: ToolCapability[];
  snakemakeWrappers?: SnakemakeWrapperMatch[];
  snakemakeWrapperCount?: number;
  ruleTemplate?: RuleSpecTemplate;
  ruleSpecDraft?: RuleSpecDraft;
};

export type RuleSpecScalar = string | number | boolean;

export type RuleSpecPort = ToolCapabilitySlot & {
  path?: string;
  temp?: boolean;
  protected?: boolean;
  directory?: boolean;
};

export type RuleSpecParam = {
  type?: string;
  title?: string;
  description?: string;
  default?: RuleSpecScalar;
  enum?: RuleSpecScalar[];
  minimum?: number;
  maximum?: number;
};

export type RuleSpecCondaEnvironment = {
  channels?: string[];
  dependencies?: string[];
};

export type RuleSpecEnvironment = {
  conda?: RuleSpecCondaEnvironment;
  container?: string | { url?: string; image?: string };
};

export type RuleSpecModule = {
  name?: string;
  snakefile: string;
  rule: string;
};

export type RuleSpecResource = {
  type?: string;
  default?: RuleSpecScalar;
  required?: boolean;
  description?: string;
  configKey?: string;
  acceptedTemplates?: string[];
  acceptedCapabilities?: string[];
};

export type RuleSpecTemplate = {
  commandTemplate?: string;
  wrapper?: string;
  script?: string;
  scriptAssets?: Array<{ path: string; content: string }>;
  module?: RuleSpecModule;
  moduleAssets?: Array<{ path: string; content: string }>;
  inputs?: RuleSpecPort[];
  outputs?: RuleSpecPort[];
  params?: Record<string, RuleSpecParam | RuleSpecScalar>;
  threads?: number;
  resources?: Record<string, RuleSpecResource | RuleSpecScalar>;
  schedulerResources?: Record<string, RuleSpecResource | RuleSpecScalar>;
  runtimeResources?: Record<string, RuleSpecResource | RuleSpecScalar>;
  environment?: RuleSpecEnvironment;
  log?: string | Record<string, string>;
  smokeTest?: {
    inputs?: Record<string, { filename?: string; content?: string; contentBase64?: string; mimeType?: string }>;
    params?: Record<string, RuleSpecScalar>;
    resourceBindings?: Record<string, string | { databaseId?: string; id?: string }>;
    timeoutSeconds?: number;
  };
};

export type RuleSpecLock = {
  packageSpec?: string;
  version?: string;
  wrapperRepository?: string;
  wrapperRef?: string;
  wrapperPath?: string;
  wrapperIdentifier?: string;
  [key: string]: unknown;
};

export type SnakemakeWrapperMatch = {
  candidateId?: string;
  candidateKind?: string;
  qualityTier?: ToolCandidateQualityTier;
  sourceRef?: ToolCandidateSourceRef;
  name: string;
  toolName: string;
  wrapperRepository?: string;
  wrapperRef?: string;
  wrapperPath: string;
  wrapperIdentifier?: string;
  wrapperUrl: string;
  environmentUrl?: string;
  ruleSpecDraft?: RuleSpecDraft;
};

export type RuleSpecDraft = {
  source: "snakemake-wrapper" | "conda-package" | string;
  contractSource?: string;
  status?: string;
  reason?: string;
  requiresUserCompletion?: boolean;
  lock?: RuleSpecLock;
  ruleTemplate?: RuleSpecTemplate;
  notes?: string[];
};

export type ToolContractValidationItem = {
  status: "not_run" | "passed" | "failed" | "running" | string;
  code?: string;
  message?: string;
  checkedAt?: string;
  runId?: string;
  logPath?: string;
  artifactCount?: string;
  artifactNames?: string;
  evidenceType?: string;
  databaseId?: string;
  templateId?: string;
  role?: string;
  artifactName?: string;
};

export type MissingToolResourceCandidate = {
  id: string;
  name?: string;
  templateId?: string;
  version?: string;
  status?: string;
};

export type MissingToolResource = {
  key: string;
  resourceType?: string;
  configKey?: string;
  acceptedTemplates?: string[];
  acceptedCapabilities?: string[];
  candidates?: MissingToolResourceCandidate[];
};

export type ToolContractStatus = {
  dryRun: ToolContractValidationItem;
  smokeRun: ToolContractValidationItem;
  outputValidation: ToolContractValidationItem;
  production: ToolContractValidationItem;
};

export type ToolContractState =
  | "Discovered"
  | "AddedDependency"
  | "RuleSpecConfirmed"
  | "EnvSpecified"
  | "SnakemakeRenderable"
  | "DryRunPassed"
  | "SmokeRunPassed"
  | "WorkflowReady"
  | "ProductionEnabled"
  | "waiting_resource";

export type ToolContractPackage = {
  name?: string;
  packageSpec?: string;
  source?: string;
  version?: string;
  targetPlatform?: string;
  targetPlatformSupported?: boolean;
};

export type ToolContractRuleSpec = {
  source?: string;
  action?: string;
  inputs?: number;
  outputs?: number;
  params?: number;
  threads?: number;
  schedulerResources?: number;
  log?: number;
  wrapperLocked?: boolean;
  requiresUserCompletion?: boolean;
};

export type ToolContractEnvironment = {
  specified?: boolean;
  declared?: boolean;
  locked?: boolean;
  channelPriorityStrict?: boolean;
  channels?: string[];
  dependencies?: string[];
};

export type ToolContractSmokeTest = {
  specified?: boolean;
  inputs?: number;
  requiredInputs?: number;
  missingInputs?: string[];
};

export type ToolContract = {
  state: ToolContractState | string;
  workflowReady: boolean;
  productionEnabled?: boolean;
  package?: ToolContractPackage;
  ruleSpec?: ToolContractRuleSpec;
  environment?: ToolContractEnvironment;
  smokeTest?: ToolContractSmokeTest;
  requirements?: Record<string, boolean>;
  validation?: ToolContractStatus;
  missingResources?: MissingToolResource[];
  reasons?: string[];
};

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

export const sourceFilters = [
  { id: "all", label: "全部" },
  { id: "bioconda", label: "Bioconda" },
  { id: "conda-forge", label: "conda-forge" },
];

export const TOOL_SEARCH_PAGE_SIZE = 20;

export function toolErrorMessage(err: unknown, fallback: string) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/TOOL_PACKAGE_VERSION_REQUIRED/.test(message)) {
    return "请选择一个明确版本后再加入工具。";
  }
  if (/TOOL_PACKAGE_VERSION_MISMATCH/.test(message)) {
    return "工具版本与 packageSpec 中锁定的版本不一致，请重新选择版本。";
  }
  if (/TOOL_PACKAGE_SOURCE_MISMATCH/.test(message)) {
    return "工具来源与 packageSpec 的 channel 不一致，请重新选择来源。";
  }
  if (/TOOL_PACKAGE_NAME_MISMATCH/.test(message)) {
    return "工具名称与 packageSpec 中的包名不一致，请重新选择工具。";
  }
  if (/TOOL_RULE_SMOKE_TEST_REQUIRED|TOOL_RULE_SMOKE_INPUT_REQUIRED/.test(message)) {
    return "请补全 Smoke 测试输入后再验证工具。";
  }
  if (/WORKFLOW_TOOL_NOT_READY/.test(message)) {
    return "该工具还未通过合同验证，暂不能加入流程。";
  }
  if (/OUTPUT_ARTIFACT_MISSING/.test(message)) {
    return "Smoke run 已执行，但没有生成声明的输出产物。";
  }
  if (/SNAKEMAKE_DRY_RUN_FAILED/.test(message)) {
    return "Snakemake dry-run 失败，请检查 RuleSpec 的输入、输出和命令。";
  }
  if (/TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY/.test(message)) {
    return "工具必须先达到 WorkflowReady，才能记录生产验收。";
  }
  if (/timed out|timeout|超时/i.test(message)) {
    return "远程服务响应超时，请先确认 SSH 底部状态为已连接，并刷新远程服务后再试。";
  }
  if (/not ready|not prepared|not connected|unreachable|Remote end closed/i.test(message)) {
    return "远程服务暂不可用，请先连接 SSH 并启动远程服务。";
  }
  return message || fallback;
}

export function searchErrorMessage(err: unknown) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/timed out|timeout|超时/i.test(message)) {
    return "在线搜索超时，请稍后重试。";
  }
  if (/name resolution|Temporary failure|NetworkError|Failed to fetch|unreachable/i.test(message)) {
    return "在线搜索暂不可用，请检查本机网络后重试。";
  }
  return message || "在线搜索失败";
}

export function dependencyKey(packageSpec: string) {
  return String(packageSpec || "").trim().toLowerCase();
}

export function packageSpecLocked(packageSpec: string) {
  const spec = String(packageSpec || "").trim();
  if (!spec || /[<>*]/.test(spec)) return false;
  const packageName = spec.split("::").at(-1) || "";
  const separator = packageName.includes("==") ? "==" : packageName.includes("=") ? "=" : "";
  if (!separator) return false;
  const [name, version] = packageName.split(separator);
  return Boolean(name.trim() && version.trim());
}

export function syncRuleSpecDraftPackageLock(
  draft: RuleSpecDraft | undefined,
  {
    selectedPackageSpec,
    selectedVersion,
    source,
  }: {
    selectedPackageSpec: string;
    selectedVersion: string;
    source: string;
  }
) {
  const packageSpec = selectedPackageSpec.trim();
  if (!draft || !packageSpec) {
    return draft;
  }
  const lock = draft.lock || {};
  const nextLock: Record<string, unknown> = {
    ...lock,
    packageSpec,
    version: selectedVersion.trim(),
  };
  const lockSource = String(lock.source || source || "").trim();
  if (lockSource) {
    nextLock.source = lockSource;
  }
  return {
    ...draft,
    lock: nextLock,
  };
}

export function applySelectedPackageLock<T extends ToolSearchItem>(
  tool: T,
  selectedVersion: string,
  selectedPackageSpec: string
): T {
  const packageSpec = selectedPackageSpec.trim() || tool.packageSpec;
  const syncDraft = (draft: RuleSpecDraft | undefined) =>
    syncRuleSpecDraftPackageLock(draft, {
      selectedPackageSpec: packageSpec,
      selectedVersion,
      source: tool.source,
    });
  return {
    ...tool,
    version: selectedVersion,
    packageSpec,
    ruleSpecDraft: syncDraft(tool.ruleSpecDraft),
    snakemakeWrappers: tool.snakemakeWrappers?.map((wrapper) => ({
      ...wrapper,
      ruleSpecDraft: syncDraft(wrapper.ruleSpecDraft),
    })),
  };
}

export function uniqueDependencies(items: AddedTool[]) {
  const seen = new Set<string>();
  const unique: AddedTool[] = [];
  for (const item of items) {
    const key = dependencyKey(item.selectedPackageSpec || item.packageSpec);
    if (key && seen.has(key)) {
      continue;
    }
    if (key) {
      seen.add(key);
    }
    unique.push(item);
  }
  return unique;
}

export {
  applySelectedWrapperLock,
  buildExecutableRuleSpecForSelectedTool,
  defaultRuleSpecOutputPath,
  isExecutableRuleSpec,
  missingRuleSpecFields,
} from "./tools-page-rule-spec-completion";
