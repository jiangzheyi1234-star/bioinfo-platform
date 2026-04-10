"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { Execution, Project, Task } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toExecution, toProject, toTask } from "./detection_workspace_utils";

export type ProjectWorkspaceTab = "overview" | "run" | "history" | "results" | "databases";

const SIDEBAR_EXECUTION_SUMMARY_LIMIT = 20;
const SIDEBAR_EXECUTION_SUMMARY_STALE_MS = 30_000;

type WorkspaceShellContextValue = {
  projects: Project[];
  currentProject: Project | null;
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  selectedExecutionId: string;
  projectExecutionRows: Execution[];
  projectExecutionSummaryByProject: Record<string, Execution[]>;
  projectExecutionSummaryLoadingByProject: Record<string, boolean>;
  projectSummaryOpen: boolean;
  projectWorkspaceTab: ProjectWorkspaceTab;
  shellError: string;
  createProjectBusy: boolean;
  renameProjectBusy: boolean;
  projectActionBusyId: string;
  setShellError: (message: string) => void;
  selectProject: (projectId: string) => Promise<void>;
  selectTask: (taskId: string) => void;
  selectExecution: (execution: Execution) => void;
  openProjectSummary: () => void;
  setProjectWorkspaceTab: (tab: ProjectWorkspaceTab) => void;
  setSelectedExecutionId: (executionId: string) => void;
  setProjectSummaryOpen: (open: boolean) => void;
  refreshProjects: () => Promise<void>;
  refreshTasks: (projectId: string) => Promise<void>;
  refreshProjectExecutions: (projectId: string) => Promise<void>;
  refreshProjectExecutionSummary: (projectId: string, options?: { force?: boolean }) => Promise<void>;
  createProject: (name: string, description: string) => Promise<void>;
  renameProject: (name: string, description?: string) => Promise<void>;
  archiveProject: (projectId: string) => Promise<void>;
  deleteProject: (projectId: string) => Promise<void>;
};

const WorkspaceShellContext = createContext<WorkspaceShellContextValue | null>(null);

export function WorkspaceShellProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [selectedExecutionId, setSelectedExecutionId] = useState("");
  const [projectExecutionRows, setProjectExecutionRows] = useState<Execution[]>([]);
  const [projectExecutionSummaryByProject, setProjectExecutionSummaryByProject] = useState<Record<string, Execution[]>>({});
  const [projectExecutionSummaryLoadingByProject, setProjectExecutionSummaryLoadingByProject] = useState<Record<string, boolean>>({});
  const [projectSummaryOpen, setProjectSummaryOpen] = useState(false);
  const [projectWorkspaceTab, setProjectWorkspaceTab] = useState<ProjectWorkspaceTab>("overview");
  const [shellError, setShellError] = useState("");
  const [createProjectBusy, setCreateProjectBusy] = useState(false);
  const [renameProjectBusy, setRenameProjectBusy] = useState(false);
  const [projectActionBusyId, setProjectActionBusyId] = useState("");
  const currentProjectIdRef = useRef("");
  const projectExecutionSummaryFetchedAtRef = useRef<Record<string, number>>({});

  const currentProject = useMemo(
    () => projects.find((project) => project.project_id === currentProjectId) ?? null,
    [currentProjectId, projects]
  );

  useEffect(() => {
    currentProjectIdRef.current = currentProjectId;
  }, [currentProjectId]);

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

  const refreshProjectExecutions = async (projectId: string) => {
    if (!projectId) {
      setProjectExecutionRows([]);
      setSelectedExecutionId("");
      return;
    }
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/history?limit=100`);
      const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
      const items = Array.isArray(data.items)
        ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
        : [];
      if (projectId === currentProjectIdRef.current) {
        setProjectExecutionRows(items);
        setSelectedExecutionId((prev) =>
          prev && items.some((item) => item.execution_id === prev) ? prev : items[0]?.execution_id || ""
        );
      }
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  };

  const refreshProjectExecutionSummary = async (projectId: string, options?: { force?: boolean }) => {
    if (!projectId) {
      setProjectExecutionSummaryByProject({});
      setProjectExecutionSummaryLoadingByProject({});
      projectExecutionSummaryFetchedAtRef.current = {};
      return;
    }
    const force = options?.force === true;
    const fetchedAt = projectExecutionSummaryFetchedAtRef.current[projectId] ?? 0;
    const isFresh = fetchedAt > 0 && Date.now() - fetchedAt < SIDEBAR_EXECUTION_SUMMARY_STALE_MS;
    if (!force && isFresh) {
      return;
    }
    setProjectExecutionSummaryLoadingByProject((prev) => ({ ...prev, [projectId]: true }));
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/history/summary?limit=${SIDEBAR_EXECUTION_SUMMARY_LIMIT}`
      );
      const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
      const items = Array.isArray(data.items)
        ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
        : [];
      projectExecutionSummaryFetchedAtRef.current = {
        ...projectExecutionSummaryFetchedAtRef.current,
        [projectId]: Date.now(),
      };
      setProjectExecutionSummaryByProject((prev) => ({ ...prev, [projectId]: items }));
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setProjectExecutionSummaryLoadingByProject((prev) => ({ ...prev, [projectId]: false }));
    }
  };

  const openProject = async (projectId: string) => {
    const normalized = safeText(projectId);
    if (!normalized) {
      setCurrentProjectId("");
      setTasks([]);
      setSelectedTaskId("");
      setProjectExecutionRows([]);
      setSelectedExecutionId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalized)}/open`, { method: "POST" });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalized);
    setProjectExecutionRows([]);
    setSelectedExecutionId("");
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
      setProjectExecutionRows([]);
      setProjectExecutionSummaryByProject({});
      setProjectExecutionSummaryLoadingByProject({});
      projectExecutionSummaryFetchedAtRef.current = {};
      setSelectedExecutionId("");
    }
  };

  const createProject = async (name: string, description: string) => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      throw new Error("项目名称不能为空。");
    }
    setCreateProjectBusy(true);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          description: description.trim() || undefined,
          open_after_create: true,
        }),
      });
      await readJsonOrThrow(resp);
      setProjectWorkspaceTab("overview");
      setProjectSummaryOpen(false);
      await refreshProjects();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setShellError(message);
      throw err;
    } finally {
      setCreateProjectBusy(false);
    }
  };

  const renameProject = async (name: string, description?: string) => {
    const trimmedName = name.trim();
    if (!currentProjectId) {
      throw new Error("项目不存在。");
    }
    if (!trimmedName) {
      throw new Error("项目名称不能为空。");
    }
    setRenameProjectBusy(true);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: trimmedName,
          ...(typeof description === "string" ? { description } : {}),
        }),
      });
      await readJsonOrThrow(resp);
      await refreshProjects();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setShellError(message);
      throw err;
    } finally {
      setRenameProjectBusy(false);
    }
  };

  const archiveProject = async (projectId: string) => {
    const normalizedProjectId = safeText(projectId);
    if (!normalizedProjectId) {
      throw new Error("项目不存在。");
    }
    setProjectActionBusyId(normalizedProjectId);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/archive`, {
        method: "POST",
      });
      await readJsonOrThrow(resp);
      setProjectSummaryOpen(false);
      setProjectWorkspaceTab("overview");
      await refreshProjects();
    } catch (err) {
      const rawMessage = err instanceof Error ? err.message : String(err);
      const message =
        rawMessage === "Not Found"
          ? "归档项目接口不可用；请重启当前应用后重试。"
          : rawMessage;
      setShellError(message);
      window.alert(message);
    } finally {
      setProjectActionBusyId("");
    }
  };

  const deleteProject = async (projectId: string) => {
    const normalizedProjectId = safeText(projectId);
    if (!normalizedProjectId) {
      throw new Error("项目不存在。");
    }
    setProjectActionBusyId(normalizedProjectId);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalizedProjectId)}`, {
        method: "DELETE",
      });
      await readJsonOrThrow(resp);
      const remainingProjects = projects.filter((project) => project.project_id !== normalizedProjectId);
      setProjects(remainingProjects);
      setProjectExecutionSummaryByProject((prev) => {
        const next = { ...prev };
        delete next[normalizedProjectId];
        return next;
      });
      setProjectExecutionSummaryLoadingByProject((prev) => {
        const next = { ...prev };
        delete next[normalizedProjectId];
        return next;
      });
      const nextFetchedAt = { ...projectExecutionSummaryFetchedAtRef.current };
      delete nextFetchedAt[normalizedProjectId];
      projectExecutionSummaryFetchedAtRef.current = nextFetchedAt;
      setProjectSummaryOpen(false);
      setProjectWorkspaceTab("overview");
      if (currentProjectId === normalizedProjectId) {
        const nextProjectId = remainingProjects[0]?.project_id || "";
        setCurrentProjectId(nextProjectId);
        setTasks([]);
        setSelectedTaskId("");
        setProjectExecutionRows([]);
        setSelectedExecutionId("");
        if (nextProjectId) {
          await openProject(nextProjectId);
          await Promise.all([
            refreshTasks(nextProjectId),
            refreshProjectExecutions(nextProjectId),
            refreshProjectExecutionSummary(nextProjectId, { force: true }),
          ]);
        }
      } else {
        await refreshProjects();
      }
    } catch (err) {
      const rawMessage = err instanceof Error ? err.message : String(err);
      const message =
        rawMessage === "Not Found"
          ? "彻底删除项目接口不可用；请重启当前应用后重试。"
          : rawMessage;
      setShellError(message);
      window.alert(message);
    } finally {
      setProjectActionBusyId("");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshProjects();
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([
          refreshTasks(currentProjectId),
          refreshProjectExecutions(currentProjectId),
          refreshProjectExecutionSummary(currentProjectId),
        ]);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId]);

  const value = useMemo<WorkspaceShellContextValue>(
    () => ({
      projects,
      currentProject,
      currentProjectId,
      tasks,
      selectedTaskId,
      selectedExecutionId,
      projectExecutionRows,
      projectExecutionSummaryByProject,
      projectExecutionSummaryLoadingByProject,
      projectSummaryOpen,
      projectWorkspaceTab,
      shellError,
      createProjectBusy,
      renameProjectBusy,
      projectActionBusyId,
      setShellError,
      selectProject: async (projectId: string) => {
        setProjectSummaryOpen(false);
        setProjectWorkspaceTab("overview");
        await openProject(projectId);
      },
      selectTask: (taskId: string) => {
        setSelectedTaskId(taskId);
        setProjectSummaryOpen(false);
      },
      selectExecution: (execution: Execution) => {
        if (execution.task_id) {
          setSelectedTaskId(execution.task_id);
        }
        setSelectedExecutionId(execution.execution_id);
        setProjectSummaryOpen(false);
        setProjectWorkspaceTab("results");
      },
      openProjectSummary: () => {
        setProjectSummaryOpen(true);
        setProjectWorkspaceTab("overview");
      },
      setProjectWorkspaceTab,
      setSelectedExecutionId,
      setProjectSummaryOpen,
      refreshProjects,
      refreshTasks,
      refreshProjectExecutions,
      refreshProjectExecutionSummary,
      createProject,
      renameProject,
      archiveProject,
      deleteProject,
    }),
    [
      projectActionBusyId,
      createProjectBusy,
      currentProject,
      currentProjectId,
      projectExecutionRows,
      projectExecutionSummaryByProject,
      projectExecutionSummaryLoadingByProject,
      projectSummaryOpen,
      projectWorkspaceTab,
      projects,
      renameProjectBusy,
      selectedExecutionId,
      selectedTaskId,
      shellError,
      tasks,
    ]
  );

  return <WorkspaceShellContext.Provider value={value}>{children}</WorkspaceShellContext.Provider>;
}

export function useWorkspaceShell() {
  const value = useContext(WorkspaceShellContext);
  if (!value) {
    throw new Error("useWorkspaceShell must be used within WorkspaceShellProvider");
  }
  return value;
}
