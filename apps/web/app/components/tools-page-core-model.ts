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
  operation?: string;
  resource?: string;
  edamData?: string;
  edamFormat?: string;
  edamOperation?: string;
  edamResource?: string;
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
  profileId?: string;
  profileVersion?: number;
  packId?: string;
  packageName?: string;
  validationTarget?: string;
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

export type CapabilityBundleValidationEvidence = {
  status?: string;
  validationResultId?: string;
  evidenceId?: string;
  jobId?: string;
  checkedAt?: string;
  stages?: Array<{ id?: string; status?: string; code?: string; checkedAt?: string; logPath?: string }>;
  fixture?: {
    inputs?: Array<{ name?: string; filename?: string; mimeType?: string }>;
    expectedArtifacts?: Array<{ name?: string; path?: string; mimeType?: string }>;
  };
};

export type CapabilityAdmissionEvidence = {
  policyVersion?: string;
  databaseResources?: Array<{
    resourceKey?: string;
    configKey?: string;
    databaseId?: string;
    databaseIds?: string[];
    name?: string;
    templateId?: string;
    status?: string;
    version?: string;
    lastCheckedAt?: string;
    pathMode?: string;
    availableReadLengths?: number[];
    candidateCount?: number;
    availableCount?: number;
  }>;
  missingResources?: Array<{
    resourceKey?: string;
    configKey?: string;
    acceptedTemplates?: string[];
    acceptedCapabilities?: string[];
    nextAction?: string;
  }>;
};

export type CapabilityBundleSummary = {
  capabilityBundleVersion: "capability-bundle-v1" | string;
  capabilityId: string;
  toolId?: string;
  toolName?: string;
  profileId?: string;
  packId?: string;
  toolRevisionId: string;
  source?: string;
  version?: string;
  inputs?: RuleSpecPort[];
  outputs?: RuleSpecPort[];
  parameters?: Record<string, RuleSpecParam | RuleSpecScalar>;
  environmentLock?: {
    manager?: string;
    targetPlatform?: string;
    channels?: string[];
    dependencies?: string[];
    packageSpec?: string;
  };
  risk?: { level?: string; reasons?: string[] };
  permissions?: { network?: boolean; filesystem?: string[]; databases?: string[] };
  approval?: { required?: boolean; approved?: boolean; policyVersion?: string; reason?: string };
  admissionEvidence?: CapabilityAdmissionEvidence;
  validationEvidence?: CapabilityBundleValidationEvidence;
  selectionSummary?: {
    label?: string;
    workflowStage?: string;
    operation?: string;
    reason?: string;
  };
  agentSelectable?: boolean;
  blockedReasons?: string[];
  nextAction?: string;
};

export type CapabilityBundleStatus = {
  version?: string;
  agentSelectable?: boolean;
  blockedReasons?: string[];
  nextAction?: string;
};

export type CapabilityBundleGate = {
  capabilityBundleVersion?: "capability-bundle-v1" | string;
  total?: number;
  selectable?: number;
  blocked?: number;
  blockedTools?: Array<{
    toolId?: string;
    toolRevisionId?: string;
    capabilityId?: string;
    blockedReasons?: string[];
    nextAction?: string;
    admissionEvidence?: CapabilityAdmissionEvidence;
  }>;
};
