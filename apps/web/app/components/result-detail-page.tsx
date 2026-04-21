"use client";

import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useResultDetailData } from "./workspace-live-data";

export function ResultDetailPage({ resultId }: { resultId: string }) {
  const { result, selectedArtifact, selectedArtifactId, setSelectedArtifactId, preview, error } = useResultDetailData(resultId);

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        eyebrow="Result"
        breadcrumbs={[{ label: "Results", href: "/results" }, { label: result.title || resultId }]}
        title={result.title || `Result ${resultId}`}
        description={`Source run · ${result.runId}`}
        actions={
          <>
            <WorkspaceActionButton href={`/runs/${result.runId}`}>Open source run</WorkspaceActionButton>
            <WorkspaceActionButton variant="primary">Download bundle</WorkspaceActionButton>
          </>
        }
      />

      <SummaryStrip
        items={[
          { label: "Pipeline", value: result.pipelineId },
          { label: "Produced", value: result.producedAt },
          { label: "Artifact Count", value: String(result.artifactCount) },
          { label: "Result ID", value: result.resultId },
        ]}
      />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live result data · {error}</div>
      ) : null}

      <div className="flex flex-wrap gap-2 rounded-2xl bg-slate-50 p-2">
        {["Overview", "Files", "Preview", "Metadata", "Raw JSON"].map((tab, index) => (
          <div key={tab} className={index === 2 ? "rounded-xl bg-white px-4 py-2 text-sm font-medium text-slate-900 shadow-sm" : "rounded-xl px-4 py-2 text-sm text-slate-500"}>
            {tab}
          </div>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <WorkspaceSection title="Artifact selector" description="v1 采用顶部 selector / 轻列表，而不是左侧文件树主导的文件浏览器。">
          <div className="space-y-2">
            {result.artifacts.map((artifact) => (
              <button
                key={artifact.artifactId}
                type="button"
                onClick={() => setSelectedArtifactId(artifact.artifactId)}
                className={artifact.artifactId === selectedArtifactId ? "w-full rounded-xl bg-slate-100 px-4 py-3 text-left" : "w-full rounded-xl px-4 py-3 text-left transition hover:bg-slate-50"}
              >
                <p className="truncate text-sm font-medium text-slate-900">{artifact.name ?? artifact.path.split("/").pop()}</p>
                <p className="truncate text-[12px] text-slate-500">{artifact.kind} · {artifact.mimeType}</p>
              </button>
            ))}
          </div>
        </WorkspaceSection>

        <div className="space-y-5">
          <WorkspaceSection title="Preview" description="先把最值得看的 artifact 展示出来，再补充 metadata 与 raw JSON。">
            {selectedArtifact ? (
              <div className="rounded-2xl border border-slate-200 bg-white">
                <div className="border-b border-slate-200 px-4 py-3">
                  <p className="text-sm font-medium text-slate-900">{selectedArtifact.name ?? selectedArtifact.path.split("/").pop()}</p>
                  <p className="mt-1 text-[12px] text-slate-500">{selectedArtifact.path}</p>
                </div>
                <div className="px-4 py-4">
                  {preview?.preview.kind === "table" ? (
                    <div className="overflow-hidden rounded-2xl bg-slate-50">
                      <div className="grid grid-cols-3 border-b border-slate-200 px-4 py-3 text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                        {preview.preview.columns?.map((column) => (
                          <span key={column}>{column}</span>
                        ))}
                      </div>
                      <div className="divide-y divide-slate-200">
                        {preview.preview.rows?.map((row, index) => (
                          <div key={`${row.join("-")}-${index}`} className="grid grid-cols-3 px-4 py-3 text-sm text-slate-700">
                            {row.map((cell) => (
                              <span key={cell}>{cell}</span>
                            ))}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : preview?.preview.kind === "html" ? (
                    <div
                      className="rounded-2xl bg-slate-50 px-4 py-6 text-sm text-slate-700"
                      dangerouslySetInnerHTML={{ __html: preview.preview.content ?? "" }}
                    />
                  ) : preview?.preview.kind === "text" ? (
                    <pre className="overflow-auto rounded-2xl bg-slate-50 px-4 py-4 text-[12px] leading-6 text-slate-700">
                      {preview.preview.content}
                    </pre>
                  ) : (
                    <div className="rounded-2xl bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                      Preview unavailable for {selectedArtifact.mimeType}. Download the artifact for full inspection.
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </WorkspaceSection>

          <WorkspaceSection title="Metadata" description="把结果元数据压缩成少数明确字段，避免噪音。">
            <dl className="space-y-2 text-sm text-slate-700">
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Result ID</dt><dd>{result.resultId}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Source run</dt><dd>{result.runId}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Artifacts</dt><dd>{result.artifactCount}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Produced</dt><dd>{result.producedAt}</dd></div>
            </dl>
          </WorkspaceSection>

          <WorkspaceSection title="Raw JSON" description="当研究员需要精确核对时，再查看原始对象。">
            <pre className="overflow-auto rounded-2xl bg-slate-950 px-4 py-4 text-[12px] leading-6 text-slate-100">
              {JSON.stringify(result, null, 2)}
            </pre>
          </WorkspaceSection>
        </div>
      </div>
    </div>
  );
}
