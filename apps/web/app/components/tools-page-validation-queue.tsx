import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { createToolPrepareJob, prepareToolValidationQueue } from "./tools-page-api";
import { ToolProductionEvidencePanel } from "./tools-page-production-evidence";
import {
  type AddedTool,
  type ToolPrepareJobQueue,
  type ToolCatalogProductionQueue,
  type ToolCatalogValidationQueueItem,
  type ToolPrepareJob,
  type ToolValidationQueuePrepareItem,
  toolErrorMessage,
} from "./tools-page-model";
import { useToolPrepareTasks } from "./tool-prepare-task-context";

export function ToolCatalogValidationQueueStrip({
  items,
  productionQueue,
  prepareJobQueue,
  onQueueChanged,
}: {
  items: ToolCatalogValidationQueueItem[];
  productionQueue?: ToolCatalogProductionQueue;
  prepareJobQueue?: ToolPrepareJobQueue;
  onQueueChanged?: () => Promise<void> | void;
}) {
  const [preparingCandidateId, setPreparingCandidateId] = useState("");
  const [batchPreparing, setBatchPreparing] = useState(false);
  const [batchStatus, setBatchStatus] = useState("");
  const [error, setError] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(10);
  const { trackToolPrepareJob } = useToolPrepareTasks();
  const visibleItems = items.slice(0, visibleLimit);
  const hiddenItemCount = Math.max(0, items.length - visibleItems.length);
  const prepareQueueActive = Boolean((prepareJobQueue?.total ?? 0) > 0 || prepareJobQueue?.items?.length);

  if (items.length === 0 && !productionQueue?.items?.length && !prepareQueueActive) {
    return null;
  }

  async function prepareValidationCandidate(item: ToolCatalogValidationQueueItem) {
    const tool = addedToolFromValidationQueueItem(item);
    if (!tool) {
      setError("验证队列缺少可提交的工具草案。");
      return;
    }
    setPreparingCandidateId(item.candidateId);
    setError("");
    try {
      const job = await createToolPrepareJob(tool);
      trackToolPrepareJob(job);
      await onQueueChanged?.();
    } catch (err) {
      setError(toolErrorMessage(err, "启动工具验证失败"));
    } finally {
      setPreparingCandidateId((current) => current === item.candidateId ? "" : current);
    }
  }

  async function prepareTopValidationCandidates() {
    setBatchPreparing(true);
    setBatchStatus("");
    setError("");
    try {
      const result = await prepareToolValidationQueue(Math.min(items.length, 30));
      result.queued.forEach((item) => trackToolPrepareJob(queueJobToPrepareTask(item)));
      setBatchStatus(
        `${result.batchPlan?.status || "queued"} · ${result.batchPlan?.jobIds.length ?? result.queuedCount} jobs · ${result.skippedCount} skipped`
      );
      await onQueueChanged?.();
    } catch (err) {
      setError(toolErrorMessage(err, "批量启动工具验证失败"));
    } finally {
      setBatchPreparing(false);
    }
  }

  return (
    <>
      {prepareQueueActive ? (
        <div aria-label="prepare job queue" className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-200 pb-2 text-xs">
          <span className="font-medium text-slate-800">验证任务</span>
          {prepareQueueMetricItems(prepareJobQueue).map(([label, value]) => (
            <span key={label} className="text-slate-500">
              <span className="font-mono text-slate-900">{value}</span> {prepareQueueLabel(label)}
            </span>
          ))}
        </div>
      ) : null}
      {items.length > 0 ? (
        <div aria-label="validation queue" className={prepareQueueActive ? "mt-3" : ""}>
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-xs font-medium text-slate-800">
              待验证候选
              <span className="ml-2 font-mono text-slate-500">{visibleItems.length}/{items.length}</span>
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-7 bg-white px-2 text-[11px]"
              data-testid="tool-validation-queue-batch-validate"
              disabled={batchPreparing}
              onClick={() => void prepareTopValidationCandidates()}
            >
              {batchPreparing ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
              批量验证
            </Button>
          </div>
          <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
            {visibleItems.map((item) => {
              const preparing = preparingCandidateId === item.candidateId;
              const activePrepareJob = isActivePrepareJob(item);
              return (
                <div
                  key={item.candidateId}
                  data-testid={`tool-validation-queue-item-${item.candidateId}`}
                  className="grid gap-3 border-b border-slate-100 px-3 py-2 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_minmax(220px,0.9fr)_auto]"
                  title={item.validationPlan?.readinessBoundary || (item.priority?.reasons || []).join(", ")}
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900">{item.profileId}</div>
                    <div className="mt-0.5 flex min-w-0 flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
                      <span>优先级 <span className="font-mono text-blue-700">{item.priority?.score ?? 0}</span></span>
                      <span>{item.executionGate?.nextAction || item.action}</span>
                    </div>
                  </div>
                  <div className="min-w-0 text-[11px] text-slate-500">
                    <div className="truncate">
                      {item.latestPrepareJob?.status ? (
                        <>
                          最近 <span className="font-mono text-slate-800">{item.latestPrepareJob.status}</span>
                          {item.latestPrepareJob?.errorCode ? (
                            <span className="ml-1 font-mono text-amber-700">{item.latestPrepareJob?.errorCode}</span>
                          ) : null}
                        </>
                      ) : (
                        "尚未验证"
                      )}
                    </div>
                    <div className="mt-1 truncate">{validationEvidenceSummary(item)}</div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 bg-white px-2 text-xs"
                    data-testid={`tool-validation-queue-validate-${item.candidateId}`}
                    disabled={preparing || activePrepareJob || !item.preparePayload}
                    onClick={() => void prepareValidationCandidate(item)}
                  >
                    {preparing || activePrepareJob ? <Loader2 strokeWidth={1.5} className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                    {activePrepareJob ? "验证中" : "验证"}
                  </Button>
                </div>
              );
            })}
          </div>
          {hiddenItemCount > 0 || visibleLimit > 10 ? (
            <button
              type="button"
              className="mt-1 text-[11px] font-medium text-blue-700 hover:text-blue-900"
              onClick={() => setVisibleLimit((current) => (hiddenItemCount > 0 ? current + 10 : 10))}
            >
              {hiddenItemCount > 0 ? `再显示 10 个 · 还有 ${hiddenItemCount} 个` : "收起验证候选"}
            </button>
          ) : null}
        </div>
      ) : null}
      <ToolProductionEvidencePanel productionQueue={productionQueue} onQueueChanged={onQueueChanged} />
      {batchStatus ? <div className="mt-1 text-[11px] text-slate-500">{batchStatus}</div> : null}
      {error ? <div className="mt-1 text-[11px] text-red-600">{error}</div> : null}
    </>
  );
}

function prepareQueueMetricItems(queue?: ToolPrepareJobQueue): [string, number][] {
  const counts = queue?.statusCounts ?? {};
  return [
    ["queued", counts.queued ?? 0],
    ["running", counts.running ?? 0],
    ["waiting", counts.waiting_resource ?? 0],
    ["exhausted", counts.exhausted ?? 0],
    ["succeeded", counts.succeeded ?? 0],
  ];
}

function prepareQueueLabel(label: string) {
  switch (label) {
    case "queued":
      return "排队";
    case "running":
      return "运行";
    case "waiting":
      return "等待资源";
    case "exhausted":
      return "耗尽";
    case "succeeded":
      return "成功";
    default:
      return label;
  }
}

function validationEvidenceSummary(item: ToolCatalogValidationQueueItem): string {
  const evidence = item.evidence || {};
  const parts = [
    `${item.validationPlan?.stages?.length ?? 0} prepare stages`,
    `${evidence.snakemakeWrapperCount ?? 0} wrappers`,
  ];
  if (evidence.wrapperContractHintCount) {
    parts.push(`${evidence.wrapperContractHintCount} metadata`);
  }
  if (evidence.wrapperContractHintFields?.length) {
    parts.push(evidence.wrapperContractHintFields.slice(0, 2).join("/"));
  }
  if (evidence.wrapperCondaDependencies?.length) {
    parts.push(`${evidence.wrapperCondaDependencies.length} env`);
  }
  const semanticFields = (evidence.semanticPortFields || []).join("/");
  if (semanticFields) {
    parts.push(semanticFields);
  }
  const resourceSummary = validationResourceSummary(evidence as unknown as ValidationResourceEvidence);
  if (resourceSummary) {
    parts.push(resourceSummary);
  }
  return parts.join(" · ");
}

type ValidationResourceEvidence = {
  requiredResources?: Array<{
    resourceKey?: string;
    acceptedTemplates?: string[];
    acceptedCapabilities?: string[];
    nextAction?: string;
  }>;
  requiredResourceKeys?: string[];
};

function validationResourceSummary(evidence: ValidationResourceEvidence): string {
  const resources = Array.isArray(evidence.requiredResources) ? evidence.requiredResources : [];
  if (resources.length) {
    return resources
      .slice(0, 2)
      .map((resource) => {
        const templates = resource.acceptedTemplates?.filter(Boolean).join("|") || resource.acceptedCapabilities?.filter(Boolean).join("|");
        return templates ? `${resource.resourceKey}:${templates}` : String(resource.resourceKey || "");
      })
      .filter(Boolean)
      .join(" ");
  }
  const keys = Array.isArray(evidence.requiredResourceKeys) ? evidence.requiredResourceKeys : [];
  return keys.length ? `resources ${keys.slice(0, 2).join(" ")}` : "";
}

function isActivePrepareJob(item: ToolCatalogValidationQueueItem): boolean {
  const status = String(item.latestPrepareJob?.status || "").trim();
  return status === "queued" || status === "running";
}

function addedToolFromValidationQueueItem(item: ToolCatalogValidationQueueItem): AddedTool | null {
  const payload = item.preparePayload;
  const id = String(payload?.id || "").trim();
  const name = String(payload?.name || item.toolNames[0] || item.profileId || "").trim();
  const packageSpec = String(payload?.packageSpec || "").trim();
  if (!id || !name || !packageSpec) {
    return null;
  }
  const source = String(payload?.source || "bioconda").trim() || "bioconda";
  const version = String(payload?.version || "").trim();
  return {
    id,
    name,
    summary: item.toolNames.join(", ") || item.profileId,
    source,
    sourceLabel: String(payload?.sourceLabel || source).trim() || source,
    packageSpec,
    selectedPackageSpec: packageSpec,
    selectedVersion: version,
    version,
    latestVersion: String(payload?.latestVersion || version).trim(),
    versions: version ? [version] : [],
    targetPlatform: payload?.targetPlatform || "linux-64",
    targetPlatformSupported: payload?.targetPlatformSupported !== false,
    ruleTemplate: payload?.ruleTemplate,
    ruleSpecDraft: payload?.ruleSpecDraft,
    capabilities: payload?.capabilities || [],
    snakemakeWrappers: payload?.snakemakeWrappers || [],
    snakemakeWrapperCount: payload?.snakemakeWrapperCount || 0,
  };
}

function queueJobToPrepareTask(item: ToolValidationQueuePrepareItem): ToolPrepareJob {
  const now = new Date().toISOString();
  return {
    jobId: item.jobId,
    status: item.status,
    stage: item.stage,
    message: item.message || "Prepare job queued.",
    toolId: item.toolId,
    createdAt: item.createdAt || now,
    updatedAt: item.updatedAt || now,
    events: [],
  };
}
