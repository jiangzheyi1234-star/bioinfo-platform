"use client";

import type { Project } from "./detection_workspace_types";

type DetectionWorkspaceProjectSelectProps = {
  currentProjectId: string;
  projects: Project[];
  onOpenProject: (projectId: string) => Promise<void>;
};

export function DetectionWorkspaceProjectSelect({
  currentProjectId,
  projects,
  onOpenProject,
}: DetectionWorkspaceProjectSelectProps) {
  return (
    <select
      className="control-select"
      value={currentProjectId}
      onChange={(event) => void onOpenProject(event.target.value)}
      aria-label="选择项目"
    >
      {projects.length === 0 ? <option value="">暂无项目</option> : null}
      {projects.map((project) => (
        <option key={project.project_id} value={project.project_id}>
          {project.name} ({project.project_id})
        </option>
      ))}
    </select>
  );
}
