import type { ToolCatalogValidationQueueItem } from "./tools-page-model";

export function ToolCatalogValidationQueueStrip({ items }: { items: ToolCatalogValidationQueueItem[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item.candidateId}
          className="inline-flex min-h-7 max-w-full items-center gap-1 rounded-md border border-blue-100 bg-white px-2 py-1 text-[11px] text-slate-600"
          title={item.validationPlan?.readinessBoundary || (item.priority?.reasons || []).join(", ")}
        >
          <span className="truncate font-medium text-slate-800">{item.profileId}</span>
          <span className="font-mono text-blue-700">{item.priority?.score ?? 0}</span>
          <span className="text-slate-400">{item.executionGate?.nextAction || item.action}</span>
          <span className="font-mono text-slate-800">{item.validationPlan?.stages?.length ?? 0}</span>
          <span className="text-slate-400">prepare stages</span>
          <span className="text-slate-400">wrappers</span>
          <span className="font-mono text-slate-800">{item.evidence?.snakemakeWrapperCount ?? 0}</span>
          <span className="text-slate-400">semantics</span>
          <span className="font-mono text-slate-800">{(item.evidence?.semanticPortFields || []).join("/") || "none"}</span>
        </span>
      ))}
      <span className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-[11px] text-slate-400">
        validation queue
      </span>
    </div>
  );
}
