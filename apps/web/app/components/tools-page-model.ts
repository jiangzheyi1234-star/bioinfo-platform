export type ToolSearchItem = {
  id: string;
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
  capabilities?: ToolCapability[];
  snakemakeWrappers?: SnakemakeWrapperMatch[];
  snakemakeWrapperCount?: number;
  contractStatus?: ToolContractStatus;
  toolContract?: ToolContract;
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
  name: string;
  toolName: string;
  wrapperRepository?: string;
  wrapperRef?: string;
  wrapperPath: string;
  wrapperIdentifier?: string;
  wrapperUrl: string;
  environmentUrl?: string;
  ruleTemplateDraft?: RuleSpecDraft;
  ruleSpecDraft?: RuleSpecDraft;
};

export type RuleSpecDraft = {
  source: "snakemake-wrapper" | "conda-package" | string;
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

export type ToolContractStatus = {
  dryRun: ToolContractValidationItem;
  smokeRun: ToolContractValidationItem;
  outputValidation: ToolContractValidationItem;
  production: ToolContractValidationItem;
};

export type ToolContractState =
  | "Discovered"
  | "AddedDependency"
  | "RuleSpecDrafted"
  | "RuleSpecConfirmed"
  | "EnvSpecified"
  | "SnakemakeRenderable"
  | "DryRunPassed"
  | "SmokeRunPassed"
  | "OutputValidated"
  | "WorkflowReady"
  | "ProductionEnabled";

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
  };
};

export type AddedTool = ToolSearchItem & {
  selectedVersion: string;
  selectedPackageSpec: string;
  status?: string;
  message?: string;
  createdAt?: string;
  updatedAt?: string;
  lastCheckedAt?: string | null;
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
      ruleTemplateDraft: syncDraft(wrapper.ruleTemplateDraft),
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
