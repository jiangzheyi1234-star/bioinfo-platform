import type { WorkflowInputArtifact } from "./workflows-page-model";

export function WorkflowResultInputLineagePanel({
  inputArtifacts,
}: {
  inputArtifacts: WorkflowInputArtifact[];
}) {
  if (inputArtifacts.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-900">输入 lineage</div>
          <div className="text-xs text-slate-500">已登记的上游输入产物</div>
        </div>
        <span className="shrink-0 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-500">
          {inputArtifacts.length} 个输入
        </span>
      </div>
      <div className="space-y-2">
        {inputArtifacts.map((artifact) => (
          <div key={artifact.artifactBlobId} className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="truncate font-mono text-xs text-slate-800">{artifact.artifactBlobId}</span>
              {artifact.mimeType ? <span className="text-[11px] text-slate-500">{artifact.mimeType}</span> : null}
              {typeof artifact.sizeBytes === "number" ? (
                <span className="text-[11px] text-slate-500">{formatInputArtifactBytes(artifact.sizeBytes)}</span>
              ) : null}
              {artifact.sha256 ? (
                <span className="truncate font-mono text-[11px] text-slate-400">
                  sha256 {artifact.sha256.slice(0, 12)}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(artifact.ports || []).map((port, index) => (
                <span
                  key={port.lineageEdgeId || `${artifact.artifactBlobId}-${index}`}
                  className="inline-flex max-w-full items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600"
                >
                  <span className="font-medium text-slate-700">{port.portName || port.inputRole || "input"}</span>
                  <span className="font-mono text-slate-400">{port.sourceType || "source"}</span>
                  {port.artifactId ? <span className="truncate font-mono text-slate-500">{port.artifactId}</span> : null}
                  {port.upstreamRunId ? (
                    <span className="truncate font-mono text-blue-600">{port.upstreamRunId}</span>
                  ) : null}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatInputArtifactBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
}
