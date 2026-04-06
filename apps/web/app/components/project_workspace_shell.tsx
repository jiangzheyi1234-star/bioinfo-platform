"use client";

import { type CSSProperties, type ReactNode } from "react";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

import type { Project, Task } from "./detection_workspace_types";
import { ProjectWorkspaceSidebar } from "./project_workspace_sidebar";

type ProjectWorkspaceShellProps = {
  activeView: "workspace" | "results" | "settings" | string;
  projects: Project[];
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  error: string;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
  children: ReactNode;
};

export function ProjectWorkspaceShell({
  activeView,
  projects,
  currentProjectId,
  tasks,
  selectedTaskId,
  error,
  onSelectProject,
  onSelectTask,
  children,
}: ProjectWorkspaceShellProps) {
  return (
    <SidebarProvider
      defaultOpen
      style={
        {
          "--sidebar-width": "288px",
        } as CSSProperties
      }
    >
      <div className="flex min-h-screen w-full bg-[var(--app-shell-background)]">
        <ProjectWorkspaceSidebar
          activeView={activeView}
          projects={projects}
          currentProjectId={currentProjectId}
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelectProject={onSelectProject}
          onSelectTask={onSelectTask}
        />

        <SidebarInset>
          <section className="codex-main-shell w-full flex-1 overflow-y-auto px-6 py-5 xl:max-h-screen xl:px-8">
            {error ? (
              <div className="mb-5 rounded-2xl border border-red-200 bg-red-50/90 px-4 py-3 text-sm text-red-700" role="alert">
                <strong className="mb-0.5 block font-medium">API Error</strong>
                <span className="font-mono text-xs">{error}</span>
              </div>
            ) : null}
            {children}
          </section>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
