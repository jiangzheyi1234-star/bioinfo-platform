"use client";

import { DataRow, ExternalAffordance, SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useProjectsData } from "./workspace-live-data";

export function ProjectsPage() {
  const { projects, error } = useProjectsData();
  const summary = [
    { label: "Projects", value: String(projects.length).padStart(2, "0") },
    { label: "Active", value: String(projects.filter((project) => project.status === "active").length).padStart(2, "0") },
    { label: "With runs", value: String(projects.filter((project) => project.status === "active").length).padStart(2, "0") },
    { label: "Latest", value: projects[0]?.name ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title="Projects"
        description="项目页承接输入资产与 run 的归属关系，保持对象页优先。"
        breadcrumbs={[{ label: "Projects" }]}
        actions={<WorkspaceActionButton variant="primary">Create project</WorkspaceActionButton>}
      />

      <SummaryStrip items={summary} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live project data · {error}</div>
      ) : null}

      <WorkspaceSection title="Project inventory" description="列表只保留真正帮助研究员定位对象的信息。">
        <div className="space-y-1">
          {projects.map((project) => (
            <DataRow key={project.project_id} href={`/projects/${project.project_id}`}>
              <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-[minmax(0,1.5fr)_140px_32px] md:items-center">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{project.name}</p>
                  <p className="truncate text-[12px] text-slate-500">{project.description || "No description"}</p>
                </div>
                <p className="text-sm text-slate-700">{project.status}</p>
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
