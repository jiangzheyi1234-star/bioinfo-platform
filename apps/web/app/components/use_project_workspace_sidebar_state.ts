"use client";

import { useEffect, useState } from "react";

import type { Project, Task } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toProject, toTask } from "./detection_workspace_utils";

export function useProjectWorkspaceSidebarState() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [error, setError] = useState<string>("");

  const openProject = async (projectId: string) => {
    const normalized = safeText(projectId);
    if (!normalized) {
      setCurrentProjectId("");
      setTasks([]);
      setSelectedTaskId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalized)}/open`, { method: "POST" });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalized);
  };

  const refreshTasks = async (projectId: string) => {
    if (!projectId) {
      setTasks([]);
      setSelectedTaskId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/tasks`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items) ? data.items.map(toTask).filter((item: Task | null): item is Task => !!item) : [];
    setTasks(items);
    setSelectedTaskId((prev) => (items.some((task) => task.task_id === prev) ? prev : items[0]?.task_id || ""));
  };

  const refreshProjects = async () => {
    const projectResp = await fetch(`${apiBase()}/api/v1/projects`);
    const projectData = (await readJsonOrThrow(projectResp)) as { items?: unknown[] };
    const projectItems = Array.isArray(projectData.items)
      ? projectData.items.map(toProject).filter((item: Project | null): item is Project => !!item)
      : [];
    setProjects(projectItems);

    const currentResp = await fetch(`${apiBase()}/api/v1/projects/current`);
    const currentData = await readJsonOrThrow(currentResp);
    const currentId = safeText(currentData?.item?.project_id) || projectItems[0]?.project_id || "";
    if (currentId) {
      await openProject(currentId);
    } else {
      setCurrentProjectId("");
      setTasks([]);
      setSelectedTaskId("");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshProjects();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await refreshTasks(currentProjectId);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId]);

  return {
    projects,
    currentProjectId,
    tasks,
    selectedTaskId,
    error,
    setError,
    selectProject: (projectId: string) => {
      void openProject(projectId);
    },
    selectTask: (taskId: string) => setSelectedTaskId(taskId),
    refreshProjects: () => {
      void refreshProjects();
    },
  };
}
