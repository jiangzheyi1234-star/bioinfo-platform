"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { DetectionWorkspaceShell } from "./detection_workspace_shell";
import { ProjectSidebarSection } from "./project_sidebar_section";
import { WorkspaceShellProvider, useWorkspaceShell } from "./workspace_shell_context";

type WorkspaceRouteKind = "connect" | "workspace" | "settings" | "other";

function resolveWorkspaceRouteKind(pathname: string): WorkspaceRouteKind {
  if (pathname.startsWith("/connect")) {
    return "connect";
  }
  if (pathname.startsWith("/workspace")) {
    return "workspace";
  }
  if (pathname.startsWith("/settings")) {
    return "settings";
  }
  return "other";
}

function resolveActiveTab(kind: WorkspaceRouteKind) {
  if (kind === "connect") return "connect" as const;
  if (kind === "settings") return "settings" as const;
  return "workspace" as const;
}

function resolvePageCopy(kind: WorkspaceRouteKind) {
  if (kind === "workspace") {
    return {
      title: "工作台",
      description: "围绕当前 Task Workbench 进行 Workflow 组装、运行监控与结果查看。",
    };
  }
  return {
    title: undefined,
    description: undefined,
  };
}

function WorkspaceChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    projects,
    currentProject,
    currentProjectId,
    tasks,
    selectedTaskId,
    shellError,
    createProjectBusy,
    createTaskBusy,
    projectActionBusyId,
    setShellError,
    selectProject,
    selectTask,
    createProject,
    createTask,
    archiveProject,
    deleteProject,
  } = useWorkspaceShell();
  const routeKind = resolveWorkspaceRouteKind(pathname);
  const activeTab = resolveActiveTab(routeKind);
  const pageCopy = resolvePageCopy(routeKind);

  const isWorkspaceRoute = routeKind !== "other";
  const hidePageChrome = routeKind === "workspace";
  const hideWorkspaceMeta = routeKind === "workspace" || routeKind === "connect";
  const hideErrorNotice = routeKind === "workspace";

  useEffect(() => {
    setShellError("");
  }, [pathname, setShellError]);

  if (!isWorkspaceRoute) {
    return <>{children}</>;
  }

  return (
    <DetectionWorkspaceShell
      activeTab={activeTab}
      pageTitle={pageCopy.title}
      pageDescription={pageCopy.description}
      hidePageHeader={hidePageChrome}
      hidePageMeta={hideWorkspaceMeta}
      hideFooterNote={hideWorkspaceMeta}
      hideErrorNotice={hideErrorNotice}
      currentProject={currentProject ?? undefined}
      projects={projects}
      currentProjectId={currentProjectId}
      error={shellError}
      onOpenConnectionEditor={
        routeKind === "connect"
          ? () => {
              router.push("/connect?edit=1");
            }
          : undefined
      }
      sidebarContent={
        <ProjectSidebarSection
          projects={projects}
          currentProjectId={currentProjectId}
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          createProjectBusy={createProjectBusy}
          createTaskBusy={createTaskBusy}
          projectActionBusyId={projectActionBusyId}
          onOpenProject={async (projectId) => {
            await selectProject(projectId);
            router.push("/workspace");
          }}
          onOpenTask={(taskId) => {
            selectTask(taskId);
            router.push("/workspace");
          }}
          onCreateProject={createProject}
          onCreateTask={createTask}
          onArchiveProject={async (projectId) => {
            await archiveProject(projectId);
            router.push("/workspace");
          }}
          onDeleteProject={async (projectId) => {
            await deleteProject(projectId);
            router.push("/workspace");
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
