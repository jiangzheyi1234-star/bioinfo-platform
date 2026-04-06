"use client";

import { ProjectWorkspaceShell } from "./project_workspace_shell";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { useProjectWorkspaceSidebarState } from "./use_project_workspace_sidebar_state";

export function ProjectSettingsPage() {
  const {
    projects,
    currentProjectId,
    tasks,
    selectedTaskId,
    error,
    selectProject,
    selectTask,
  } = useProjectWorkspaceSidebarState();

  return (
    <ProjectWorkspaceShell
      activeView="settings"
      projects={projects}
      currentProjectId={currentProjectId}
      tasks={tasks}
      selectedTaskId={selectedTaskId}
      error={error}
      onSelectProject={selectProject}
      onSelectTask={selectTask}
    >
      <section className="grid gap-[18px]">
        <WorkspaceSectionHeader title="设置" description="SSH 连接已迁移到左侧“连接”页面；这里后续只保留纯设置项。" />
        <WorkspaceEmptyState mark="Cfg" label="当前无可编辑设置" hint="连接、测试和断开 SSH 请在左侧“连接”页完成。" />
      </section>
    </ProjectWorkspaceShell>
  );
}
