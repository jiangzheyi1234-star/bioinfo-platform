"use client";

import type { WorkflowRunRule } from "./workflows-page-model";

export function WorkflowRuleLogEvidence({ rule }: { rule: WorkflowRunRule }) {
  const context = rule.logContext;
  const tail = context?.tail || [];
  const selectedArtifactId = context?.selectedArtifact?.artifactId;
  const logReferenceCount = rule.logReferenceCount ?? context?.logReferenceCount ?? 0;

  if (!context && logReferenceCount === 0) return null;

  return (
    <div className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-600">
      <div className="grid gap-1 text-[11px] sm:grid-cols-[96px_minmax(0,1fr)]">
        <span className="text-slate-400">log refs</span>
        <span className="font-mono text-slate-700">{logReferenceCount}</span>
        {context ? (
          <>
            <span className="text-slate-400">log evidence</span>
            <span className="truncate font-mono text-slate-700">{context.reasonCode || context.status || "unknown"}</span>
            <span className="text-slate-400">artifact</span>
            <span className="truncate font-mono text-slate-700">{selectedArtifactId || context.message || "-"}</span>
          </>
        ) : null}
      </div>
      {tail.length > 0 ? (
        <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-2 text-[11px] text-slate-100">
          {tail.join("\n")}
        </pre>
      ) : null}
    </div>
  );
}
