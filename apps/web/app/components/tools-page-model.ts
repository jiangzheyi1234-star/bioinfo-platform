export * from "./tools-page-core-model";
export * from "./tools-page-catalog-model";

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

export {
  applySelectedPackageLock,
  dependencyKey,
  packageSpecLocked,
  syncRuleSpecDraftPackageLock,
  uniqueDependencies,
} from "./tools-page-package-lock";

export {
  applySelectedWrapperLock,
  buildExecutableRuleSpecForSelectedTool,
  defaultRuleSpecOutputPath,
  isExecutableRuleSpec,
  missingRuleSpecFields,
} from "./tools-page-rule-spec-completion";
