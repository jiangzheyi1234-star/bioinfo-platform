"use client";

import { useEffect, useState } from "react";

import type { Project } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, toProject } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { useWorkspaceShell } from "./workspace_shell_context";

export function ProjectSettingsPage() {
  const { refreshProjects, setShellError } = useWorkspaceShell();
  const [archivedProjects, setArchivedProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyProjectId, setBusyProjectId] = useState("");

  const loadArchivedProjects = async () => {
    setLoading(true);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects?include_archived=true`);
      const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
      const items = Array.isArray(data.items)
        ? data.items.map(toProject).filter((item): item is Project => !!item && item.status === "archived")
        : [];
      setArchivedProjects(items);
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const restoreProject = async (projectId: string) => {
    setBusyProjectId(projectId);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/restore`, {
        method: "POST",
      });
      await readJsonOrThrow(resp);
      await Promise.all([loadArchivedProjects(), refreshProjects()]);
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setBusyProjectId("");
    }
  };

  useEffect(() => {
    void loadArchivedProjects();
  }, []);

  return (
    <section className="grid gap-4" aria-label="设置页内容">
      <section className="panel p-4">
        <WorkspaceSectionHeader
          title="归档项目"
          description="查看已归档项目，并将需要继续使用的项目移出归档。"
          aside={
            <button className="control-btn" type="button" onClick={() => void loadArchivedProjects()} disabled={loading}>
              {loading ? "刷新中..." : "刷新"}
            </button>
          }
        />
        {archivedProjects.length === 0 ? (
          <WorkspaceEmptyState mark="Arc" label="暂无归档项目" hint="项目归档后会出现在这里，可随时移出归档。" compact />
        ) : (
          <div className="settings-archive-list">
            {archivedProjects.map((project) => (
              <article key={project.project_id} className="settings-archive-item">
                <div className="settings-archive-copy">
                  <strong>{project.name}</strong>
                  {project.description ? <p>{project.description}</p> : null}
                  <span>{project.project_id}</span>
                </div>
                <button
                  className="control-btn"
                  type="button"
                  disabled={busyProjectId === project.project_id}
                  onClick={() => void restoreProject(project.project_id)}
                >
                  {busyProjectId === project.project_id ? "移出中..." : "移出归档"}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
