"use client";

import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useProjectDetailData } from "./workspace-live-data";

export function ProjectDetailPage({ projectId }: { projectId: string }) {
  const { project, runs, error } = useProjectDetailData(projectId);
  const summary = [
    { label: "Project", value: project?.name ?? projectId },
    { label: "Status", value: project?.status ?? "—" },
    { label: "Runs", value: String(runs.length).padStart(2, "0") },
    { label: "Last run", value: runs[0]?.runId ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        eyebrow="Project"
        breadcrumbs={[{ label: "Projects", href: "/projects" }, { label: project?.name ?? projectId }]}
        title={project?.name ?? `Project ${projectId}`}
        description={project?.description || "Project detail keeps runs and inputs close to the object."}
        actions={<WorkspaceActionButton href={`/projects/${projectId}/new-run`} variant="primary">New Run</WorkspaceActionButton>}
      />

      <SummaryStrip items={summary} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live project data · {error}</div>
      ) : null}

      <WorkspaceSection title="Recent runs" description="项目 detail 只保留和当前对象直接相关的运行入口。">
        <div className="space-y-2">
          {runs.map((run) => (
            <div key={run.runId} className="rounded-xl bg-slate-50 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-900">{run.runId}</p>
                  <p className="mt-1 text-[12px] text-slate-500">{run.pipelineId} · {run.requestId}</p>
                </div>
                <div className="text-right text-[12px] text-slate-500">
                  <p>{run.status}</p>
                  <p>{run.stage}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </WorkspaceSection>
    </div>
  );
}
