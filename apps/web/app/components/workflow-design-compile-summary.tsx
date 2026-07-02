"use client";

import { AlertCircle, Archive, CheckCircle2, GitBranch } from "lucide-react";

import { cn } from "@/lib/utils";

import type {
  WorkflowDesignCompileResult,
  WorkflowDesignSemanticPortEvidence,
  WorkflowDesignSemanticPortEvidenceEdge,
} from "./workflow-design-draft-model";

export function WorkflowDesignCompileSummary({ result }: { result: WorkflowDesignCompileResult | null }) {
  if (!result) return null;
  const entries = Object.entries(result.layout || {});
  const semanticPortEvidence = semanticPortEvidenceForResult(result);
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
        <Archive strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
        编译产物
      </div>
      <div className="grid gap-1.5">
        {result.workflowRevisionId ? (
          <div className="grid gap-1 rounded-md bg-emerald-50 px-3 py-2 text-xs md:grid-cols-[120px_minmax(0,1fr)]">
            <div className="font-medium text-emerald-700">WorkflowRevision</div>
            <div className="min-w-0 truncate font-mono text-emerald-800">{result.workflowRevisionId}</div>
          </div>
        ) : null}
        {semanticPortEvidence ? <SemanticPortEvidenceSummary evidence={semanticPortEvidence} /> : null}
        {entries.map(([key, value]) => (
          <div key={key} className="grid gap-1 rounded-md bg-slate-50 px-3 py-2 text-xs md:grid-cols-[120px_minmax(0,1fr)]">
            <div className="font-medium text-slate-600">{key}</div>
            <div className="min-w-0 font-mono text-slate-700">
              {Array.isArray(value) ? value.join(", ") : value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function semanticPortEvidenceForResult(
  result: WorkflowDesignCompileResult
): WorkflowDesignSemanticPortEvidence | null {
  return result.semanticPortEvidence || result.workflowRevision?.graphSnapshot?.semanticPortEvidence || null;
}

function SemanticPortEvidenceSummary({ evidence }: { evidence: WorkflowDesignSemanticPortEvidence }) {
  const blocked = evidence.blockedEdgeCount > 0 || evidence.status === "blocked";
  const visibleEdges = evidence.edges.slice(0, 3);
  return (
    <div
      className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs"
      data-semantic-port-evidence-blocked-count={evidence.blockedEdgeCount}
      data-semantic-port-evidence-edge-count={evidence.edgeCount}
      data-semantic-port-evidence-status={evidence.status}
      data-testid="workflow-design-semantic-port-evidence"
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 font-medium text-slate-700">
          <GitBranch strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span>语义端口证据</span>
        </div>
        <span className={cn(
          "inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]",
          blocked
            ? "border-amber-200 bg-amber-50 text-amber-700"
            : "border-emerald-200 bg-emerald-50 text-emerald-700"
        )}>
          {blocked ? (
            <AlertCircle strokeWidth={1.5} className="h-3 w-3" />
          ) : (
            <CheckCircle2 strokeWidth={1.5} className="h-3 w-3" />
          )}
          {blocked ? "blocked" : "passed"}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <SemanticEvidencePill tone="slate" value={`${evidence.edgeCount} edges`} />
        <SemanticEvidencePill tone="emerald" value={`${evidence.compatibleEdgeCount} compatible`} />
        <SemanticEvidencePill tone={blocked ? "amber" : "slate"} value={`${evidence.blockedEdgeCount} blocked`} />
        <SemanticEvidencePill
          tone={evidence.converterCandidateCount > 0 ? "sky" : "slate"}
          value={`${evidence.converterCandidateCount} converters`}
        />
      </div>
      {visibleEdges.length > 0 ? (
        <div className="grid gap-1.5">
          {visibleEdges.map((edge, index) => (
            <SemanticEvidenceEdgeRow key={edge.edgeId || `${edge.from.nodeId}.${edge.from.port}-${index}`} edge={edge} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SemanticEvidenceEdgeRow({ edge }: { edge: WorkflowDesignSemanticPortEvidenceEdge }) {
  const blocked = !edge.compatible;
  return (
    <div className="grid gap-1 rounded-sm bg-white px-2 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 font-mono text-[11px] text-slate-700">
          <span className="break-all">{edge.from.nodeId}.{edge.from.port}</span>
          <span className="px-1 text-slate-400">-&gt;</span>
          <span className="break-all">{edge.to.nodeId}.{edge.to.port}</span>
        </div>
        <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", blocked
          ? "border-amber-200 bg-amber-50 text-amber-700"
          : "border-emerald-200 bg-emerald-50 text-emerald-700")}>
          {edge.recommendation.reasonCode || (blocked ? "BLOCKED" : "CONNECT")}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        {edge.matchedFields.map((field) => <SemanticEvidencePill key={`matched-${field}`} tone="emerald" value={field} />)}
        {edge.genericFields.map((field) => <SemanticEvidencePill key={`generic-${field}`} tone="slate" value={`${field}:generic`} />)}
        {edge.mismatchedField ? <SemanticEvidencePill tone="amber" value={`${edge.mismatchedField}:conflict`} /> : null}
      </div>
    </div>
  );
}

function SemanticEvidencePill({ tone, value }: { tone: "amber" | "emerald" | "sky" | "slate"; value: string }) {
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
