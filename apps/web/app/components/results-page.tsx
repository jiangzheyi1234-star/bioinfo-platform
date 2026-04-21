"use client";

import { DataRow, ExternalAffordance, SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useResultsData } from "./workspace-live-data";

export function ResultsPage() {
  const { results, error } = useResultsData();
  const summary = [
    { label: "Results", value: String(results.length).padStart(2, "0") },
    { label: "Previewable", value: String(results.filter((item) => item.artifactCount > 0).length).padStart(2, "0") },
    { label: "Pending review", value: String(results.filter((item) => item.artifactCount <= 1).length).padStart(2, "0") },
    { label: "Latest run", value: results[0]?.sourceRunId ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title="Results"
        description="结果页优先服务于附件预览与来源追踪，不会把用户拉回老式文件浏览器心智。"
        breadcrumbs={[{ label: "Results" }]}
      />

      <SummaryStrip items={summary} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live results data · {error}</div>
      ) : null}

      <WorkspaceSection title="Result discovery" description="列表先帮助用户定位结果对象，再进入 detail 做 preview / metadata / raw JSON。">
        <div className="space-y-1">
          {results.map((result) => (
            <DataRow key={result.id} href={`/results/${result.id}`}>
              <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-[minmax(0,1.5fr)_160px_120px_32px] md:items-center">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{result.title}</p>
                  <p className="truncate text-[12px] text-slate-500">Source run · {result.sourceRunId}</p>
                </div>
                <p className="text-sm text-slate-700">{result.artifactCount} artifacts</p>
                <p className="text-sm text-slate-500">{result.producedAt}</p>
                <div className="flex justify-end">
                  <ExternalAffordance />
                </div>
              </div>
            </DataRow>
          ))}
        </div>
      </WorkspaceSection>
    </div>
  );
}
