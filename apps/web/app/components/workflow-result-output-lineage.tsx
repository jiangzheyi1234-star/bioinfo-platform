import type { WorkflowResultOutputLineage } from "./workflows-page-model";

export function WorkflowResultOutputLineagePanel({
  outputLineage,
}: {
  outputLineage: WorkflowResultOutputLineage[];
}) {
  if (outputLineage.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-900">输出 lineage</div>
          <div className="text-xs text-slate-500">已登记的生成与缓存复用关系</div>
        </div>
        <span className="shrink-0 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500">
          {outputLineage.length} 条边
        </span>
      </div>
      <div className="space-y-2">
        {outputLineage.map((edge, index) => (
          <div
            key={edge.lineageEdgeId || `${edge.artifactBlobId}-${index}`}
            className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-xs text-slate-800">{edge.predicate || "lineage"}</span>
              {edge.artifactKey ? <span className="text-xs font-medium text-slate-700">{edge.artifactKey}</span> : null}
              {edge.role ? <span className="text-[11px] text-slate-500">{edge.role}</span> : null}
              {edge.stepId ? <span className="text-[11px] text-slate-500">{edge.stepId}</span> : null}
            </div>
            <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-slate-400">
              {edge.artifactId ? <span className="truncate">artifact {edge.artifactId}</span> : null}
              {edge.artifactBlobId ? <span className="truncate">blob {edge.artifactBlobId}</span> : null}
              {edge.workflowRevisionId ? <span className="truncate">workflow {edge.workflowRevisionId}</span> : null}
              {edge.evidenceEventId ? <span className="truncate">evidence {edge.evidenceEventId}</span> : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
