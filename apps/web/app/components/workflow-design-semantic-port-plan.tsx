"use client";

import { AlertCircle, CheckCircle2, GitBranch, Plus, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import type { RulePortConverterInsertionRequest } from "./generated-workflow-converter-recommendation";
import { insertionRequestForBackendCandidate } from "./generated-workflow-port-advice";
import { workflowToolRevisionId } from "./generated-workflow-model";
import type {
  WorkflowDesignSemanticPortCandidate,
  WorkflowDesignSemanticPortDecision,
  WorkflowDesignSemanticPortEdgePlan,
  WorkflowDesignSemanticPortPlan,
} from "./workflow-design-draft-model";

export function WorkflowDesignSemanticPortPlanPreview({
  onInsertConverter,
  plan,
  tools = [],
}: {
  onInsertConverter?: (request: RulePortConverterInsertionRequest) => void;
  plan: WorkflowDesignSemanticPortPlan | null;
  tools?: AddedTool[];
}) {
  if (!plan || plan.edgeCount === 0) return null;
  const hasBlockedEdges = plan.blockedEdgeCount > 0;
  const availableConverterRevisionIds = new Set(tools.map((tool) => workflowToolRevisionId(tool)).filter(Boolean));
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3" data-testid="workflow-design-semantic-port-plan">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <GitBranch strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            语义端口计划
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
            <SemanticPortCountTone tone="slate" value={`${plan.edgeCount} edges`} />
            <SemanticPortCountTone tone="emerald" value={`${plan.compatibleEdgeCount} compatible`} />
            <SemanticPortCountTone tone={hasBlockedEdges ? "amber" : "slate"} value={`${plan.blockedEdgeCount} blocked`} />
            <SemanticPortCountTone tone={plan.converterCandidateCount > 0 ? "sky" : "slate"} value={`${plan.converterCandidateCount} converters`} />
          </div>
        </div>
        <div className={cn("inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px]", hasBlockedEdges
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-emerald-200 bg-emerald-50 text-emerald-700")}>
          {hasBlockedEdges ? (
            <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
          ) : (
            <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5" />
          )}
          {hasBlockedEdges ? "needs review" : "all connected"}
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {plan.edges.slice(0, 6).map((edge, index) => (
          <SemanticPortEdgeRow
            key={edge.edgeId || `${edge.from.nodeId}.${edge.from.port}-${edge.to.nodeId}.${edge.to.port}-${index}`}
            availableConverterRevisionIds={availableConverterRevisionIds}
            edge={edge}
            onInsertConverter={onInsertConverter}
          />
        ))}
      </div>
    </div>
  );
}

function SemanticPortEdgeRow({
  availableConverterRevisionIds,
  edge,
  onInsertConverter,
}: {
  availableConverterRevisionIds: Set<string>;
  edge: WorkflowDesignSemanticPortEdgePlan;
  onInsertConverter?: (request: RulePortConverterInsertionRequest) => void;
}) {
  const status = edgeStatus(edge);
  const evidence = decisionEvidence(edge.decision);
  return (
    <div className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-[11px] text-slate-700">
          <span className="break-all">{edge.from.nodeId}.{edge.from.port}</span>
          <span className="px-1 text-slate-400">-&gt;</span>
          <span className="break-all">{edge.to.nodeId}.{edge.to.port}</span>
        </div>
        <span className={cn("inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]", status.className)}>
          {status.icon}
          {status.label}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <SemanticPortCountTone tone="slate" value={edge.recommendation.reasonCode} />
        {evidence.map((item) => (
          <SemanticPortCountTone key={item} tone="emerald" value={item} />
        ))}
        {edge.decision.mismatchedField ? (
          <SemanticPortCountTone tone="amber" value={`${edge.decision.mismatchedField}:conflict`} />
        ) : null}
      </div>
      {edge.recommendation.evidence.length > 0 ? (
        <div className="line-clamp-2 text-[11px] text-slate-500">{edge.recommendation.evidence.join(" · ")}</div>
      ) : null}
      {edge.converterCandidates.length > 0 ? (
        <div className="grid gap-1.5 rounded-md bg-sky-50 px-2 py-2 text-[11px] text-sky-800">
          <div className="font-medium">一跳转换候选 · 需确认，不会自动插入</div>
          {edge.converterCandidates.slice(0, 2).map((candidate) => (
            <SemanticPortConverterCandidateRow
              key={candidateKey(candidate)}
              available={availableConverterRevisionIds.has(candidate.converterToolRevisionId)}
              candidate={candidate}
              edge={edge}
              onInsertConverter={onInsertConverter}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SemanticPortConverterCandidateRow({
  available,
  candidate,
  edge,
  onInsertConverter,
}: {
  available: boolean;
  candidate: WorkflowDesignSemanticPortCandidate;
  edge: WorkflowDesignSemanticPortEdgePlan;
  onInsertConverter?: (request: RulePortConverterInsertionRequest) => void;
}) {
  return (
    <div className="grid gap-1 rounded-sm bg-white/80 px-2 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <span className="min-w-0 break-words font-medium text-sky-900">{candidate.converterToolName}</span>
        <SemanticPortCountTone tone="sky" value={`score ${candidate.totalScore}`} />
        {candidate.confirmationRequired ? <SemanticPortCountTone tone="amber" value="confirmation required" /> : null}
      </div>
      <div className="min-w-0 break-words text-sky-700">
        {candidate.inputPort} -&gt; {candidate.outputPort} · {candidate.insertionMode}
      </div>
      <div className="min-w-0 break-words text-sky-700">{candidate.evidence.join(" · ")}</div>
      {onInsertConverter ? (
        available ? (
          <Button
            type="button"
            variant="outline"
            className="h-7 justify-self-start bg-white px-2 text-[11px]"
            onClick={() => onInsertConverter(insertionRequestForBackendCandidate(edge, candidate))}
          >
            <Plus strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
            确认插入转换
          </Button>
        ) : (
          <div className="text-[11px] text-amber-700">候选工具不在当前可用工具库</div>
        )
      ) : null}
    </div>
  );
}

function SemanticPortCountTone({ tone, value }: { tone: "amber" | "emerald" | "sky" | "slate"; value: string }) {
  return (
    <span className={cn("rounded border px-1.5 py-0.5", {
      "border-amber-200 bg-amber-50 text-amber-700": tone === "amber",
      "border-emerald-200 bg-emerald-50 text-emerald-700": tone === "emerald",
      "border-sky-200 bg-sky-50 text-sky-700": tone === "sky",
      "border-slate-200 bg-white text-slate-500": tone === "slate",
    })}>
      {value}
    </span>
  );
}

function edgeStatus(edge: WorkflowDesignSemanticPortEdgePlan) {
  if (edge.decision.compatible) {
    return {
      label: "可连接",
      className: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: <CheckCircle2 strokeWidth={1.5} className="h-3 w-3" />,
    };
  }
  if (edge.converterCandidates.length > 0 || edge.recommendation.action === "insert-converter") {
    return {
      label: "需转换",
      className: "border-sky-200 bg-sky-50 text-sky-700",
      icon: <Wand2 strokeWidth={1.5} className="h-3 w-3" />,
    };
  }
  return {
    label: "阻断",
    className: "border-amber-200 bg-amber-50 text-amber-700",
    icon: <AlertCircle strokeWidth={1.5} className="h-3 w-3" />,
  };
}

function decisionEvidence(decision: WorkflowDesignSemanticPortDecision): string[] {
  return [...decision.matchedFields, ...decision.genericFields.map((field) => `${field}:generic`)];
}

function candidateKey(candidate: WorkflowDesignSemanticPortCandidate) {
  return `${candidate.converterToolRevisionId}.${candidate.inputPort}.${candidate.outputPort}`;
}
