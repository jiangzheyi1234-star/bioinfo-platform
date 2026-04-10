"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { DetectionWorkspaceShell } from "./detection_workspace_shell";
import { ProjectSidebarSection } from "./project_sidebar_section";
import { WorkspaceShellProvider, useWorkspaceShell } from "./workspace_shell_context";

function resolveActiveTab(pathname: string) {
  if (pathname.startsWith("/connect")) return "connect" as const;
  if (pathname.startsWith("/toolflows")) return "toolflows" as const;
  if (pathname.startsWith("/settings")) return "settings" as const;
  return "projects" as const;
}

function WorkspaceChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    projects,
    currentProject,
    currentProjectId,
    selectedExecutionId,
    projectExecutionSummaryByProject,
    projectExecutionSummaryLoadingByProject,
    shellError,
    createProjectBusy,
    projectActionBusyId,
    setShellError,
    selectProject,
    selectTask,
    selectExecution,
    openProjectSummary,
    refreshProjectExecutionSummary,
    createProject,
    archiveProject,
    deleteProject,
  } = useWorkspaceShell();

  const isWorkspaceRoute =
    pathname.startsWith("/connect") ||
    pathname.startsWith("/toolflows") ||
    pathname.startsWith("/projects") ||
    pathname.startsWith("/settings") ||
    pathname.startsWith("/results");

  useEffect(() => {
    setShellError("");
  }, [pathname, setShellError]);

  if (!isWorkspaceRoute) {
    return <>{children}</>;
  }

  return (
    <DetectionWorkspaceShell
      activeTab={resolveActiveTab(pathname)}
      pageTitle={pathname.startsWith("/results") ? "项目结果页" : undefined}
      pageDescription={pathname.startsWith("/results") ? "聚合当前项目下所有任务的最新状态、最近执行和失败情况。" : undefined}
      hidePageHeader={pathname.startsWith("/projects") || pathname.startsWith("/toolflows")}
      hidePageMeta={pathname.startsWith("/projects") || pathname.startsWith("/toolflows") || pathname.startsWith("/connect")}
      hideFooterNote={pathname.startsWith("/projects") || pathname.startsWith("/toolflows") || pathname.startsWith("/connect")}
      hideErrorNotice={pathname.startsWith("/projects")}
      currentProject={currentProject ?? undefined}
      projects={projects}
      currentProjectId={currentProjectId}
      error={shellError}
      onOpenConnectionEditor={
        pathname.startsWith("/connect")
          ? () => {
              router.push("/connect?edit=1");
            }
          : undefined
      }
      sidebarContent={
        <ProjectSidebarSection
          projects={projects}
          currentProjectId={currentProjectId}
          executionItemsByProject={projectExecutionSummaryByProject}
          executionLoadingByProject={projectExecutionSummaryLoadingByProject}
          selectedExecutionId={selectedExecutionId}
          createProjectBusy={createProjectBusy}
          projectActionBusyId={projectActionBusyId}
          onOpenProject={async (projectId) => {
            await selectProject(projectId);
            void refreshProjectExecutionSummary(projectId);
            router.push("/projects");
          }}
          onSelectProjectSummary={() => {
            openProjectSummary();
            router.push("/projects");
          }}
          onSelectTask={(taskId) => {
            selectTask(taskId);
            router.push("/projects");
          }}
          onSelectExecution={(execution) => {
            selectExecution(execution);
            router.push("/projects");
          }}
          onCreateProject={createProject}
          onArchiveProject={async (projectId) => {
            await archiveProject(projectId);
            router.push("/projects");
          }}
          onDeleteProject={async (projectId) => {
            await deleteProject(projectId);
            router.push("/projects");
          }}
          onLoadProjectExecutions={async (projectId) => {
            await refreshProjectExecutionSummary(projectId, { force: true });
          }}
        />
      }
    >
      {children}
    </DetectionWorkspaceShell>
  );
}

export function WorkspaceRootShell({ children }: { children: ReactNode }) {
  return (
    <WorkspaceShellProvider>
      <WorkspaceChrome>{children}</WorkspaceChrome>
    </WorkspaceShellProvider>
  );
}
