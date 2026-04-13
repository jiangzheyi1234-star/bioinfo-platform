"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { DetectionWorkspaceShell } from "./detection_workspace_shell";
import { ProjectSidebarSection } from "./project_sidebar_section";
import { WorkspaceShellProvider, useWorkspaceShell } from "./workspace_shell_context";

function resolveActiveTab(pathname: string) {
  if (pathname.startsWith("/connect")) return "connect" as const;
  if (pathname.startsWith("/workflows")) return "workflows" as const;
  if (pathname.startsWith("/runs")) return "runs" as const;
  if (pathname.startsWith("/artifacts")) return "artifacts" as const;
  if (pathname.startsWith("/settings")) return "settings" as const;
  return "workflows" as const;
}

function WorkspaceChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    projects,
    currentProject,
    currentProjectId,
    shellError,
    createProjectBusy,
    projectActionBusyId,
    setShellError,
    selectProject,
    openProjectSummary,
    createProject,
    archiveProject,
    deleteProject,
  } = useWorkspaceShell();

  const isWorkspaceRoute =
    pathname.startsWith("/connect") ||
    pathname.startsWith("/workflows") ||
    pathname.startsWith("/projects") ||
    pathname.startsWith("/runs") ||
    pathname.startsWith("/artifacts") ||
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
      pageTitle={pathname.startsWith("/artifacts") ? "产物中心" : undefined}
      pageDescription={pathname.startsWith("/artifacts") ? "集中查看 workflow run 拉回的 artifacts 与报告文件。" : undefined}
      hidePageHeader={pathname.startsWith("/workflows") || pathname.startsWith("/runs") || pathname.startsWith("/artifacts")}
      hidePageMeta={pathname.startsWith("/workflows") || pathname.startsWith("/runs") || pathname.startsWith("/artifacts") || pathname.startsWith("/connect")}
      hideFooterNote={pathname.startsWith("/workflows") || pathname.startsWith("/runs") || pathname.startsWith("/artifacts") || pathname.startsWith("/connect")}
      hideErrorNotice={pathname.startsWith("/workflows") || pathname.startsWith("/runs")}
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
          createProjectBusy={createProjectBusy}
          projectActionBusyId={projectActionBusyId}
          onOpenProject={async (projectId) => {
            await selectProject(projectId);
            router.push("/workflows");
          }}
          onSelectProjectSummary={() => {
            openProjectSummary();
            router.push("/workflows");
          }}
          onCreateProject={createProject}
          onArchiveProject={async (projectId) => {
            await archiveProject(projectId);
            router.push("/workflows");
          }}
          onDeleteProject={async (projectId) => {
            await deleteProject(projectId);
            router.push("/workflows");
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
