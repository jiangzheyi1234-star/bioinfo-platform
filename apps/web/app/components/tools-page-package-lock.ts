import type { AddedTool, RuleSpecDraft, ToolSearchItem } from "./tools-page-model";

export function dependencyKey(packageSpec: string) {
  return String(packageSpec || "").trim().toLowerCase();
}

export function packageSpecLocked(packageSpec: string) {
  const spec = String(packageSpec || "").trim();
  if (!spec || /[<>*]/.test(spec)) return false;
  const packageName = spec.split("::").at(-1) || "";
  const separator = packageName.includes("==")
    ? "=="
    : packageName.includes("=")
      ? "="
      : "";
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
