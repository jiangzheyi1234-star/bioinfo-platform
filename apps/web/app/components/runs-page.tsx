"use client";

import {
  DataRow,
  EmptyState,
  ExternalAffordance,
  FilterPill,
  SearchField,
  StatusBadge,
  SummaryStrip,
  WorkspaceActionButton,
  WorkspacePageHeader,
  WorkspaceSection,
} from "./workspace-primitives";
import { useRunsData } from "./workspace-live-data";

export function RunsPage() {
  const { runs, error } = useRunsData();
  const runsSummary = [
    { label: "Total Runs", value: String(runs.length).padStart(2, "0") },
    { label: "Running", value: String(runs.filter((run) => run.status === "running").length).padStart(2, "0") },
    { label: "Failed", value: String(runs.filter((run) => run.status === "failed").length).padStart(2, "0") },
    { label: "Completed", value: String(runs.filter((run) => run.status === "completed").length).padStart(2, "0") },
    { label: "Connected Server", value: runs[0]?.serverLabel ?? "Unavailable" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title="Runs"
        description="运行列表优先暴露 status、stage、stateVersion 与 requestId，让研究员第一眼就能判断当前进度和可排障性。"
        breadcrumbs={[{ label: "Runs" }]}
        actions={
          <>
            <WorkspaceActionButton>Export</WorkspaceActionButton>
            <WorkspaceActionButton variant="primary">New Run</WorkspaceActionButton>
          </>
        }
      />

      <SummaryStrip items={runsSummary.map((item) => ({ label: item.label, value: item.value }))} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">
          Failed to load live runs data · {error}
        </div>
      ) : null}

      <WorkspaceSection title="Run inventory" description="列表保持中等密度，用 hover 而不是重边框表达可操作性。">
        <div className="flex flex-wrap gap-2">
          <SearchField placeholder="Search runId / pipeline / requestId" />
          <FilterPill>Status</FilterPill>
          <FilterPill>Stage</FilterPill>
          <FilterPill>Server</FilterPill>
          <FilterPill>Project</FilterPill>
          <FilterPill>Updated time</FilterPill>
        </div>

        <div className="mt-5 overflow-hidden rounded-2xl border border-slate-200/80">
          <div className="hidden grid-cols-[minmax(0,1.5fr)_140px_140px_120px_110px_110px_90px_120px_24px] gap-3 bg-slate-50 px-3 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400 lg:grid">
            <span>Run</span>
            <span>Server</span>
            <span>Project</span>
            <span>Pipeline</span>
            <span>Status</span>
            <span>Stage</span>
            <span>State</span>
            <span>Updated</span>
            <span />
          </div>

          <div className="space-y-1 bg-white p-2">
            {runs.map((run) => (
              <DataRow key={run.runId} href={`/runs/${run.runId}`}>
                <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1.5fr)_140px_140px_120px_110px_110px_90px_120px_24px] lg:items-center">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">{run.runId}</p>
                    <p className="truncate text-[12px] text-slate-500">{run.message} · {run.requestId}</p>
                  </div>
                  <p className="text-sm text-slate-700">{run.serverLabel}</p>
                  <p className="truncate text-sm text-slate-700">{run.projectLabel}</p>
                  <p className="text-sm text-slate-700">{run.pipelineId}</p>
                  <StatusBadge status={run.status} />
                  <p className="text-sm text-slate-700">{run.stage}</p>
                  <p className="text-sm text-slate-500">v{run.stateVersion}</p>
                  <p className="text-sm text-slate-500">{run.lastUpdatedAt}</p>
                  <div className="flex justify-end">
                    <ExternalAffordance />
                  </div>
                </div>
              </DataRow>
            ))}
          </div>
        </div>
      </WorkspaceSection>

      <WorkspaceSection title="Empty state preview" description="空白态保留情绪温度，但仍然像工具，不像营销页。">
        <EmptyState
          title="暂无 Run"
          description="连接服务器并创建一次新的 Run 后，这里会显示执行阶段、stateVersion 以及 requestId。"
          action={<WorkspaceActionButton variant="primary">New Run</WorkspaceActionButton>}
        />
      </WorkspaceSection>
    </div>
  );
}
