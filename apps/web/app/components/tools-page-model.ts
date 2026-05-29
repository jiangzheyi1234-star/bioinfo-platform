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
  inputs?: RuleSpecPort[];
  outputs?: RuleSpecPort[];
  params?: Record<string, RuleSpecParam | RuleSpecScalar>;
  resources?: Record<string, RuleSpecResource | RuleSpecScalar>;
  environment?: RuleSpecEnvironment;
  log?: string | Record<string, string>;
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
