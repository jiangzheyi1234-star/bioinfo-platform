"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { createToolPrepareJob } from "./tools-page-api";
import { type AddedTool, toolErrorMessage } from "./tools-page-model";
import { useToolPrepareTasks } from "./tool-prepare-task-context";
import { describePortSpec, workflowToolRevisionId } from "./generated-workflow-model";
import type { GeneratedWorkflowOutputCandidate } from "./generated-workflow-port-bindings-editor";
import {
  fetchWorkflowToolRecommendations,
  type WorkflowToolRecommendationItem,
} from "./workflows-page-api";

export function GeneratedWorkflowToolRecommendations({
  onAddTool,
  outputCandidates,
  tools,
}: {
  onAddTool: (toolRevisionId: string) => void;
  outputCandidates: GeneratedWorkflowOutputCandidate[];
  tools: AddedTool[];
}) {
  const [selectedOutputValue, setSelectedOutputValue] = useState("");
  const outputCandidateValues = outputCandidates.map((candidate) => candidate.value).join("|");
  const selectedOutputCandidate = useMemo(
    () => outputCandidates.find((candidate) => candidate.value === selectedOutputValue) || outputCandidates[0],
    [outputCandidates, selectedOutputValue]
  );
  const [recommendations, setRecommendations] = useState<WorkflowToolRecommendationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preparingCandidateId, setPreparingCandidateId] = useState("");
  const { trackToolPrepareJob } = useToolPrepareTasks();

  useEffect(() => {
    const values = outputCandidateValues ? outputCandidateValues.split("|") : [];
    setSelectedOutputValue((current) => values.includes(current) ? current : values[0] || "");
  }, [outputCandidateValues]);

  useEffect(() => {
    if (!selectedOutputCandidate) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    void fetchWorkflowToolRecommendations({ outputPort: selectedOutputCandidate.port })
      .then((catalog) => {
        if (!cancelled) setRecommendations(catalog.items || []);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "读取工具推荐失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    selectedOutputCandidate?.value,
    selectedOutputCandidate?.port.type,
    selectedOutputCandidate?.port.kind,
    selectedOutputCandidate?.port.mimeType,
    selectedOutputCandidate?.port.data,
    selectedOutputCandidate?.port.format,
  ]);

  async function handlePrepareRecommendation(recommendation: WorkflowToolRecommendationItem) {
    const tool = addedToolFromRecommendation(recommendation);
    if (!tool) {
      setError("推荐缺少可验证工具草案");
      return;
    }
    const key = recommendationKey(recommendation);
    setPreparingCandidateId(key);
    setError("");
    try {
      const job = await createToolPrepareJob(tool);
      trackToolPrepareJob(job);
    } catch (err) {
      setError(toolErrorMessage(err, "启动工具验证失败"));
    } finally {
      setPreparingCandidateId((current) => current === key ? "" : current);
    }
  }

  if (outputCandidates.length === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <Sparkles strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            下一步工具推荐
          </div>
          <div className="mt-1 text-xs text-slate-500">按当前输出端口匹配可接入的候选工具。</div>
        </div>
        <Select value={selectedOutputCandidate?.value || ""} onValueChange={setSelectedOutputValue}>
          <SelectTrigger className="h-8 w-[260px] bg-white text-xs">
            <SelectValue placeholder="选择输出端口" />
          </SelectTrigger>
          <SelectContent>
            {outputCandidates.map((candidate) => (
              <SelectItem key={candidate.value} value={candidate.value}>
                {candidate.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedOutputCandidate ? (
        <div className="mt-2 truncate font-mono text-[11px] text-slate-500">
          {selectedOutputCandidate.value} · {describePortSpec(selectedOutputCandidate.port)}
        </div>
      ) : null}

      <div className="mt-3 grid gap-2">
        {loading ? (
          <div className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
            <Loader2 strokeWidth={1.5} className="h-3.5 w-3.5 animate-spin" />
            正在读取推荐
          </div>
        ) : error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
        ) : recommendations.length === 0 ? (
          <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">暂无可自动推荐的下一步工具。</div>
        ) : recommendations.slice(0, 5).map((recommendation) => {
          const tool = matchingWorkflowReadyTool(recommendation, tools);
          const addStepRevisionId = recommendationAddStepRevisionId(recommendation, tool);
          const canAddStep = Boolean(recommendation.executionGate?.canAddStep && addStepRevisionId);
          const activePrepareJob = isActivePrepareJob(recommendation);
          const key = recommendationKey(recommendation);
          const preparing = preparingCandidateId === key;
          return (
            <div key={key} className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 md:grid-cols-[minmax(0,1fr)_auto]">
              <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium text-slate-800">{recommendationLabel(recommendation)}</span>
                  <span className="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                    {Math.round(recommendation.confidence * 100)}%
                  </span>
                </div>
                <div className="mt-1 truncate text-[11px] text-slate-500">
                  input {recommendation.inputPort.name} · {recommendation.matchedFields.join(" / ")}
                </div>
                {!canAddStep && !tool && recommendation.executionGate?.requiredState ? (
                  <div className="mt-1 truncate text-[11px] text-amber-700">
                    当前 {recommendation.executionGate.currentState || "Discovered"} · 需验证到 {recommendation.executionGate.requiredState}
                  </div>
                ) : null}
                <div className="mt-1 truncate text-[11px] text-slate-500">
                  {recommendation.executionGate?.sourceOfTruth || "recommendation"} · validation stages{" "}
                  {recommendation.validationPlan?.stages?.length ?? 0}
                </div>
                {recommendation.latestPrepareJob?.status ? (
                  <div className="mt-1 truncate text-[11px] text-blue-700">
                    验证任务 {recommendation.latestPrepareJob.status}
                    {recommendation.latestPrepareJob.stage ? ` · ${recommendation.latestPrepareJob.stage}` : ""}
                  </div>
                ) : null}
                <div className="mt-1 truncate text-[11px] text-slate-500">{recommendation.evidence.join(" · ")}</div>
              </div>
              {canAddStep ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 bg-white px-2.5 text-xs"
                  onClick={() => onAddTool(addStepRevisionId)}
                >
                  <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  添加步骤
                </Button>
              ) : activePrepareJob ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 bg-white px-2.5 text-xs"
                  disabled
                >
                  <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  验证中
                </Button>
              ) : recommendation.preparePayload ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 bg-white px-2.5 text-xs"
                  disabled={preparing}
                  onClick={() => void handlePrepareRecommendation(recommendation)}
                >
                  {preparing ? (
                    <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  准备并验证工具
                </Button>
              ) : (
                <Button asChild variant="outline" className="h-8 bg-white px-2.5 text-xs">
                  <Link href={toolSearchHref(recommendation)}>
                    <Plus strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                    准备并验证工具
                  </Link>
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function recommendationKey(recommendation: WorkflowToolRecommendationItem): string {
  return `${recommendation.candidate.candidateId || recommendation.candidate.profileId}-${recommendation.inputPort.name}`;
}

function matchingWorkflowReadyTool(recommendation: WorkflowToolRecommendationItem, tools: AddedTool[]): AddedTool | undefined {
  const toolRevisionId = String(recommendation.executionGate?.toolRevisionId || "").trim();
  const toolId = String(recommendation.executionGate?.toolId || "").trim();
  const matchedByGate = tools.find((tool) =>
    (toolRevisionId && workflowToolRevisionId(tool) === toolRevisionId) ||
    (toolId && String(tool.id || "").trim() === toolId)
  );
  if (matchedByGate) return matchedByGate;
  const names = new Set(
    [
      recommendation.candidate.profileId,
      ...(recommendation.candidate.toolNames || []),
    ].map((value) => String(value || "").trim().toLowerCase()).filter(Boolean)
  );
  return tools.find((tool) => names.has(String(tool.name || "").trim().toLowerCase()));
}

function recommendationAddStepRevisionId(recommendation: WorkflowToolRecommendationItem, tool: AddedTool | undefined): string {
  const localRevisionId = tool ? workflowToolRevisionId(tool) : "";
  return localRevisionId || String(recommendation.executionGate?.toolRevisionId || "").trim();
}

function isActivePrepareJob(recommendation: WorkflowToolRecommendationItem): boolean {
  const status = String(recommendation.latestPrepareJob?.status || "").trim();
  return status === "queued" || status === "running";
}

function recommendationLabel(recommendation: WorkflowToolRecommendationItem): string {
  return recommendationCandidateName(recommendation) || "candidate";
}

function toolSearchHref(recommendation: WorkflowToolRecommendationItem) {
  return {
    pathname: "/workflows/tools",
    query: { q: recommendationSearchQuery(recommendation) },
  };
}

function recommendationSearchQuery(recommendation: WorkflowToolRecommendationItem): string {
  return recommendationCandidateName(recommendation);
}

function recommendationCandidateName(recommendation: WorkflowToolRecommendationItem): string {
  return (
    recommendation.candidate.toolNames?.[0] ||
    recommendation.candidate.toolName ||
    recommendation.candidate.name ||
    recommendation.candidate.profileId ||
    recommendation.candidate.candidateId ||
    ""
  );
}

function addedToolFromRecommendation(recommendation: WorkflowToolRecommendationItem): AddedTool | null {
  const payload = recommendation.preparePayload || recommendation.candidate.preparePayload;
  const id = String(payload?.id || "").trim();
  const name = String(payload?.name || recommendationCandidateName(recommendation)).trim();
  const packageSpec = String(payload?.packageSpec || "").trim();
  if (!id || !name || !packageSpec) return null;
  const source = String(payload?.source || "bioconda").trim() || "bioconda";
  const version = String(payload?.version || "").trim();
  return {
    id,
    name,
    summary: recommendationLabel(recommendation),
    source,
    sourceLabel: String(payload?.sourceLabel || source).trim() || source,
    packageSpec,
    selectedPackageSpec: packageSpec,
    selectedVersion: version,
    version,
    latestVersion: version,
    versions: version ? [version] : [],
    targetPlatform: payload?.targetPlatform || "linux-64",
    targetPlatformSupported: payload?.targetPlatformSupported !== false,
    ruleTemplate: payload?.ruleTemplate,
    ruleSpecDraft: payload?.ruleSpecDraft,
  };
}
