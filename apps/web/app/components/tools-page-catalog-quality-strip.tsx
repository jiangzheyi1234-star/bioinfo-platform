import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

import type {
  CapabilityGraphSnapshot,
  SnakemakeWrapperCatalog,
  ToolCandidateCatalog,
  ToolCatalogTargetAcceptance,
  ToolCatalogTargetResult,
} from "./tools-page-model";
import { CapabilityBundleGatePanel } from "./tools-page-capability-gate";
import { ToolCatalogValidationQueueStrip } from "./tools-page-validation-queue";

export function ToolCatalogQualityStrip({
  candidateCatalog,
  candidateCatalogError = "",
  candidateCatalogLoading = false, capabilityGraph, error, loading,
  targetAcceptance,
  targetAcceptanceError = "",
  targetAcceptanceLoading = false,
  onQueueChanged,
  wrapperCatalog,
}: {
  candidateCatalog?: ToolCandidateCatalog | null;
  candidateCatalogError?: string;
  candidateCatalogLoading?: boolean; capabilityGraph?: CapabilityGraphSnapshot | null;
  error: string; loading: boolean;
  targetAcceptance?: ToolCatalogTargetAcceptance | null;
  targetAcceptanceError?: string;
  targetAcceptanceLoading?: boolean;
  onQueueChanged?: () => Promise<void> | void;
  wrapperCatalog: SnakemakeWrapperCatalog | null;
}) {
  const showingCandidates = Boolean(candidateCatalog || candidateCatalogLoading || candidateCatalogError);
  const qualityCounts = showingCandidates ? candidateCatalog?.qualityCounts : wrapperCatalog?.qualityCounts;
  const metrics = [
    ["discovered", candidateCatalog?.total ?? (!showingCandidates ? wrapperCatalog?.total : undefined) ?? qualityCounts?.discovered ?? 0],
    ["addable drafts", candidateCatalog?.addableDraftCounts?.total ?? (!showingCandidates ? wrapperCatalog?.addableTotal : undefined) ?? 0],
    ["draft-runnable", qualityCounts?.draftRunnable ?? (!showingCandidates ? wrapperCatalog?.addableTotal : undefined) ?? 0],
    ["workflow-ready", qualityCounts?.workflowReady ?? 0],
    ["production-enabled", qualityCounts?.productionEnabled ?? 0],
  ] as const;
  const sourceCounts = candidateCatalog?.sourceCounts;
  const sourceMetrics = sourceCounts
    ? ([
        ["conda packages", sourceCounts.condaPackages],
        ["wrappers", sourceCounts.snakemakeWrappers],
        ["profiles", sourceCounts.toolProfiles],
      ] as const)
    : [];
  const statusText = candidateCatalogLoading
    ? "正在搜索 candidate catalog"
    : candidateCatalogError
      ? candidateCatalogError
      : candidateCatalog
        ? `${candidateCatalog.total} candidates · page ${candidateCatalog.page}`
        : loading
          ? "正在读取 catalog"
          : error || wrapperCatalog?.sourceRef?.ref || "source pending";
  const targetMetrics = targetAcceptance ? catalogTargetMetrics(targetAcceptance) : [];
  const validationQueueItems = targetAcceptance?.validationQueue?.items ?? [];
  const productionQueueItems = targetAcceptance?.productionQueue?.items ?? [];
  const prepareQueueTotal = targetAcceptance?.prepareJobQueue?.total ?? targetAcceptance?.prepareJobQueue?.items?.length ?? 0;
  const queueTotal = validationQueueItems.length + productionQueueItems.length + prepareQueueTotal;
  const blockedCount = targetAcceptance?.blockedTargets.length ?? 0;
  const targetStatusText = targetAcceptanceLoading
    ? "正在读取 Catalog v1 targets"
    : targetAcceptanceError || (
        targetAcceptance
          ? `${blockedCount} 个目标未达成`
          : "targets pending"
      );
  return (
    <section
      aria-label={showingCandidates ? "Tool candidate catalog" : "Snakemake wrapper catalog"}
      className="rounded-md border border-slate-200 bg-white"
    >
      <div className="grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0 space-y-3">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <div className="text-sm font-medium text-slate-900">
              {showingCandidates ? "候选工具索引" : "Wrapper catalog"}
            </div>
            <div className="min-w-0 truncate text-xs text-slate-500">{statusText}</div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {metrics.map(([label, value]) => (
              <CatalogMetric key={label} label={catalogMetricLabel(label)} value={value} />
            ))}
          </div>
        </div>
        <div className="flex min-w-[190px] flex-col justify-between gap-3 rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
          <div>
            <div className="text-[11px] font-medium uppercase text-slate-400">来源</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {sourceMetrics.length > 0 ? (
                sourceMetrics.map(([label, value]) => (
                  <span key={label} className="text-xs text-slate-600">
                    <span className="font-mono text-slate-900">{value}</span> {catalogMetricLabel(label)}
                  </span>
                ))
              ) : (
                <span className="text-xs text-slate-500">{showingCandidates ? "candidate catalog" : "snakemake wrappers"}</span>
              )}
            </div>
          </div>
          <div className={cn("text-xs", blockedCount > 0 || targetAcceptanceError ? "text-amber-700" : "text-emerald-700")}>
            {targetStatusText}
          </div>
        </div>
      </div>

      <div className="border-t border-slate-100 px-4 py-3">
        <div className="grid gap-2 lg:grid-cols-5">
          {targetMetrics.map(([label, result]) => (
            <CatalogTargetProgress key={label} label={catalogMetricLabel(label)} result={result} />
          ))}
        </div>
        {queueTotal > 0 ? (
          <details data-testid="tool-processing-queue" className="group mt-3 rounded-md border border-slate-200 bg-slate-50">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs">
              <span className="font-medium text-slate-800">处理队列</span>
              <span className="flex min-w-0 items-center gap-2 text-slate-500">
                <span className="truncate">
                  {validationQueueItems.length} 待验证 · {productionQueueItems.length} 生产证据 · {prepareQueueTotal} 任务
                </span>
                <ChevronDown strokeWidth={1.5} className="h-4 w-4 shrink-0 transition group-open:rotate-180" />
              </span>
            </summary>
            <div className="border-t border-slate-200 px-3 pb-3 pt-2">
              <ToolCatalogValidationQueueStrip
                items={validationQueueItems}
                productionQueue={targetAcceptance?.productionQueue}
                prepareJobQueue={targetAcceptance?.prepareJobQueue}
                onQueueChanged={onQueueChanged}
              />
            </div>
          </details>
        ) : null}
        <CapabilityBundleGatePanel gate={capabilityGraph?.capabilityBundleGate} />
      </div>
    </section>
  );
}

function CatalogMetric({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="font-mono text-sm font-semibold text-slate-950">{value ?? 0}</div>
      <div className="mt-0.5 truncate text-[11px] text-slate-500">{label}</div>
    </div>
  );
}

function CatalogTargetProgress({ label, result }: { label: string; result: ToolCatalogTargetResult }) {
  const target = Math.max(1, result.target || 0);
  const percent = Math.max(0, Math.min(100, Math.round(((result.actual || 0) / target) * 100)));
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2 text-[11px]">
        <span className="truncate text-slate-600">{label}</span>
        <span className={cn("font-mono", result.passed ? "text-emerald-700" : "text-amber-700")}>
          {result.actual}/{result.target}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className={cn("h-full rounded-full", result.passed ? "bg-emerald-500" : "bg-amber-400")} style={{ width: `${percent}%` }} />
      </div>
      {!result.passed ? <div className="mt-1 text-[11px] text-slate-400">还差 {result.remaining}</div> : null}
    </div>
  );
}

function catalogMetricLabel(label: string) {
  switch (label) {
    case "discovered":
      return "已发现";
    case "addable drafts":
    case "addable":
      return "可添加";
    case "draft-runnable":
      return "草稿可运行";
    case "workflow-ready":
      return "流程就绪";
    case "production-enabled":
      return "生产可用";
    case "conda packages":
      return "Conda";
    case "wrappers":
      return "Wrappers";
    case "profiles":
      return "Profiles";
    case "renderable":
      return "可渲染";
    default:
      return label;
  }
}

function catalogTargetMetrics(acceptance: ToolCatalogTargetAcceptance): [string, ToolCatalogTargetResult][] {
  return [
    ["discovered", acceptance.targets.discovered],
    ["addable", acceptance.targets.addableDraft],
    ["renderable", acceptance.targets.snakemakeRenderable],
    ["workflow-ready", acceptance.targets.workflowReady],
    ["production-enabled", acceptance.targets.productionEnabled],
  ];
}
