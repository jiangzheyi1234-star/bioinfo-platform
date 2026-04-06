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
          "--sidebar-width": "250px",
        } as CSSProperties
      }
    >
      <div className="flex min-h-screen w-full bg-white">
        <ProjectWorkspaceSidebar
          activeView={activeView}
          projects={projects}
          currentProjectId={currentProjectId}
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelectProject={onSelectProject}
          onSelectTask={onSelectTask}
        />

        <SidebarInset className="bg-white">
          <section className="w-full flex-1 overflow-y-auto px-7 py-6 xl:max-h-screen">
            {error ? (
              <div className="mb-6 rounded-md border border-red-100 bg-red-50 p-3 text-sm text-red-600" role="alert">
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
