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
  ruleTemplate?: Record<string, unknown>;
  capabilities?: ToolCapability[];
};

export type ToolCapabilitySlot = {
  name: string;
  data?: string;
  format?: string;
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
