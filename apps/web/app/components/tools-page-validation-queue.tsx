import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

import { createToolPrepareJob, prepareToolValidationQueue } from "./tools-page-api";
import {
  type AddedTool,
  type ToolCatalogValidationQueueItem,
  type ToolPrepareJob,
  type ToolValidationQueuePrepareItem,
  toolErrorMessage,
} from "./tools-page-model";
import { useToolPrepareTasks } from "./tool-prepare-task-context";

export function ToolCatalogValidationQueueStrip({ items }: { items: ToolCatalogValidationQueueItem[] }) {
  const [preparingCandidateId, setPreparingCandidateId] = useState("");
  const [batchPreparing, setBatchPreparing] = useState(false);
  const [batchStatus, setBatchStatus] = useState("");
  const [error, setError] = useState("");
  const { trackToolPrepareJob } = useToolPrepareTasks();

  if (items.length === 0) {
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
      setBatchStatus(`${result.queuedCount} queued · ${result.skippedCount} skipped`);
    } catch (err) {
      setError(toolErrorMessage(err, "批量启动工具验证失败"));
    } finally {
      setBatchPreparing(false);
    }
  }

  return (
    <>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => {
          const preparing = preparingCandidateId === item.candidateId;
          return (
            <span
              key={item.candidateId}
              className="inline-flex min-h-7 max-w-full items-center gap-1 rounded-md border border-blue-100 bg-white px-2 py-1 text-[11px] text-slate-600"
              title={item.validationPlan?.readinessBoundary || (item.priority?.reasons || []).join(", ")}
            >
              <span className="truncate font-medium text-slate-800">{item.profileId}</span>
              <span className="font-mono text-blue-700">{item.priority?.score ?? 0}</span>
              <span className="text-slate-400">{item.executionGate?.nextAction || item.action}</span>
              {item.latestPrepareJob?.status ? (
                <>
                  <span className="text-slate-400">latest</span>
                  <span className="font-mono text-slate-800">{item.latestPrepareJob?.status}</span>
                  {item.latestPrepareJob?.errorCode ? (
                    <span className="max-w-[140px] truncate font-mono text-amber-700">{item.latestPrepareJob?.errorCode}</span>
                  ) : null}
                </>
              ) : null}
              <span className="font-mono text-slate-800">{item.validationPlan?.stages?.length ?? 0}</span>
              <span className="text-slate-400">prepare stages</span>
              <span className="text-slate-400">wrappers</span>
              <span className="font-mono text-slate-800">{item.evidence?.snakemakeWrapperCount ?? 0}</span>
              <span className="text-slate-400">semantics</span>
              <span className="font-mono text-slate-800">{(item.evidence?.semanticPortFields || []).join("/") || "none"}</span>
              <Button
                type="button"
                variant="outline"
                className="ml-1 h-6 bg-white px-1.5 text-[11px]"
                disabled={preparing || !item.preparePayload}
                onClick={() => void prepareValidationCandidate(item)}
              >
                {preparing ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
                验证
              </Button>
            </span>
          );
        })}
        <span className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-400">
          validation queue
        </span>
        <Button
          type="button"
          variant="outline"
          className="h-7 bg-white px-2 text-[11px]"
          disabled={batchPreparing}
          onClick={() => void prepareTopValidationCandidates()}
        >
          {batchPreparing ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
          批量验证
        </Button>
      </div>
      {batchStatus ? <div className="mt-1 text-[11px] text-slate-500">{batchStatus}</div> : null}
      {error ? <div className="mt-1 text-[11px] text-red-600">{error}</div> : null}
    </>
  );
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
