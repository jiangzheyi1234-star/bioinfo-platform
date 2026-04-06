"use client";

import { useEffect, useState } from "react";

import { ProjectWorkspaceShell } from "./project_workspace_shell";
import type { Project, Task } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toProject, toTask } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

function formatTs(value: number): string {
  if (!value) {
    return "未记录";
  }
  return new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });
}

export function ProjectResultsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [resultRows, setResultRows] = useState<Array<Record<string, unknown>>>([]);
  const [createProjectName, setCreateProjectName] = useState<string>("");
  const [busyProjectCreate, setBusyProjectCreate] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  const openProject = async (projectId: string) => {
    const normalized = safeText(projectId);
    if (!normalized) {
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalized)}/open`, { method: "POST" });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalized);
  };

  const refreshProjects = async () => {
    const projectResp = await fetch(`${apiBase()}/api/v1/projects`);
    const projectData = await readJsonOrThrow(projectResp);
    const projectItems = Array.isArray(projectData.items)
      ? projectData.items.map(toProject).filter((item: Project | null): item is Project => !!item)
      : [];
    setProjects(projectItems);
    const currentResp = await fetch(`${apiBase()}/api/v1/projects/current`);
    const currentData = await readJsonOrThrow(currentResp);
    const currentId = safeText(currentData?.item?.project_id) || projectItems[0]?.project_id || "";
    if (currentId) {
      await openProject(currentId);
    }
  };

  const refreshTasks = async (projectId: string) => {
    if (!projectId) {
      setTasks([]);
      setSelectedTaskId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/tasks`);
    const data = await readJsonOrThrow(resp);
    const items = Array.isArray(data.items) ? data.items.map(toTask).filter((item: Task | null): item is Task => !!item) : [];
    setTasks(items);
    setSelectedTaskId((prev) => (items.some((task: Task) => task.task_id === prev) ? prev : items[0]?.task_id || ""));
  };

  const refreshResults = async (projectId: string) => {
    if (!projectId) {
      setResultRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/results`);
    const data = await readJsonOrThrow(resp);
    setResultRows(Array.isArray(data.items) ? data.items : []);
  };

  const createProject = async () => {
    const name = createProjectName.trim();
    if (!name) {
      setError("项目名称不能为空。");
      return;
    }
    setBusyProjectCreate(true);
    setError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: "", open_after_create: true }),
      });
      await readJsonOrThrow(resp);
      setCreateProjectName("");
      await refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyProjectCreate(false);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshTasks(currentProjectId), refreshResults(currentProjectId)]);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId]);

  return (
    <ProjectWorkspaceShell
      activeView="results"
      projects={projects}
      currentProjectId={currentProjectId}
      tasks={tasks}
      selectedTaskId={selectedTaskId}
      error={error}
      onSelectProject={(projectId) => {
        void openProject(projectId);
      }}
      onSelectTask={(taskId) => setSelectedTaskId(taskId)}
      projectControls={
        <>
          <input
            className="control-input"
            value={createProjectName}
            onChange={(event) => setCreateProjectName(event.target.value)}
            placeholder="新项目名称"
            aria-label="新项目名称"
          />
          <button className="ui-button ui-button--primary" disabled={busyProjectCreate} onClick={() => void createProject()}>
            {busyProjectCreate ? "创建中..." : "新建项目"}
          </button>
        </>
      }
      taskToolbar={null}
    >
      <section className="workspace-panel-card project-canvas">
        <header className="project-canvas-head">
          <div>
            <h2>项目结果页</h2>
            <p>聚合当前项目下所有任务的最新状态、最近执行和失败情况。</p>
          </div>
        </header>

        {resultRows.length === 0 ? (
          <WorkspaceEmptyState mark="Res" label="当前项目暂无可展示结果" hint="先创建任务并执行工具，再回到这里查看聚合结果。" />
        ) : (
          <div className="project-results-grid">
            {resultRows.map((row) => (
              <article key={safeText(row.task_id, safeText(row.title))} className="project-result-card">
                <WorkspaceSectionHeader
                  title={safeText(row.title, safeText(row.task_id))}
                  description={safeText(row.summary, "暂无摘要")}
                  aside={<span className="badge">{safeText(row.task_status, "pending")}</span>}
                  titleAs="h4"
                />
                <div className="project-summary-stack">
                  <div className="project-summary-row">
                    <span>最新执行</span>
                    <strong>{safeText(row.latest_execution_id, "暂无")}</strong>
                  </div>
                  <div className="project-summary-row">
                    <span>最近工具</span>
                    <strong>{safeText(row.latest_tool_id, "未记录")}</strong>
                  </div>
                  <div className="project-summary-row">
                    <span>执行统计</span>
                    <strong>
                      {safeText(row.completed_count, "0")} completed / {safeText(row.failed_count, "0")} failed
                    </strong>
                  </div>
                  <div className="project-summary-row">
                    <span>最近活动</span>
                    <strong>{formatTs(Number(row.last_activity_at || 0))}</strong>
                  </div>
                  {safeText(row.latest_error) ? (
                    <div className="project-summary-row">
                      <span>最近错误</span>
                      <strong>{safeText(row.latest_error)}</strong>
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </ProjectWorkspaceShell>
  );
}
