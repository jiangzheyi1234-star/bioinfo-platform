"use client";

import { useEffect, useMemo, useState } from "react";

import { DatabaseSection, HistorySection, RunsSection } from "./detection_workspace_sections";
import { ProjectWorkspaceShell } from "./project_workspace_shell";
import type { DatabaseEntry, Execution, Project, Task, ToolDescriptor, ToolSummary } from "./detection_workspace_types";
import {
  apiBase,
  isRecord,
  readJsonOrThrow,
  safeText,
  toDatabaseEntry,
  toExecution,
  toProject,
  toTask,
  toToolSummary,
} from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

type WorkspaceTab = "overview" | "run" | "history" | "results" | "databases";

function formatTs(value: number): string {
  if (!value) {
    return "未记录";
  }
  return new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });
}

function mapStatusLabel(status: string): string {
  const normalized = status.trim();
  if (normalized === "queued") return "排队中";
  if (normalized === "in_progress") return "执行中";
  if (normalized === "completed") return "已完成";
  if (normalized === "failed") return "失败";
  if (normalized === "cancelled") return "已取消";
  return normalized || "待处理";
}

export function ProjectWorkspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [taskSearch, setTaskSearch] = useState<string>("");
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("overview");

  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [selectedToolId, setSelectedToolId] = useState<string>("");
  const [selectedDescriptor, setSelectedDescriptor] = useState<ToolDescriptor | null>(null);
  const [toolRunBusy, setToolRunBusy] = useState<boolean>(false);
  const [toolRunMsg, setToolRunMsg] = useState<string>("");
  const [toolSearch, setToolSearch] = useState<string>("");

  const [historyRows, setHistoryRows] = useState<Execution[]>([]);
  const [historySearch, setHistorySearch] = useState<string>("");
  const [busyArchiveId, setBusyArchiveId] = useState<string>("");

  const [databases, setDatabases] = useState<DatabaseEntry[]>([]);
  const [latestExecution, setLatestExecution] = useState<Record<string, unknown> | null>(null);
  const [latestResult, setLatestResult] = useState<Record<string, unknown> | null>(null);

  const [createProjectName, setCreateProjectName] = useState<string>("");
  const [createTaskTitle, setCreateTaskTitle] = useState<string>("");
  const [createTaskDescription, setCreateTaskDescription] = useState<string>("");
  const [busyProjectCreate, setBusyProjectCreate] = useState<boolean>(false);
  const [busyTaskCreate, setBusyTaskCreate] = useState<boolean>(false);
  const [error, setError] = useState<string>("");

  const filteredTasks = useMemo(() => {
    const query = taskSearch.trim().toLowerCase();
    if (!query) {
      return tasks;
    }
    return tasks.filter((task) => {
      const content = `${task.title} ${task.description} ${task.summary}`.toLowerCase();
      return content.includes(query);
    });
  }, [taskSearch, tasks]);

  const selectedTask = useMemo(
    () => filteredTasks.find((task) => task.task_id === selectedTaskId) ?? tasks.find((task) => task.task_id === selectedTaskId) ?? null,
    [filteredTasks, selectedTaskId, tasks]
  );

  const filteredTools = useMemo(() => {
    const query = toolSearch.trim().toLowerCase();
    if (!query) {
      return tools;
    }
    return tools.filter((tool) => `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase().includes(query));
  }, [toolSearch, tools]);

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

  const openProject = async (projectId: string) => {
    const normalized = safeText(projectId);
    if (!normalized) {
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
    if (items.length === 0) {
      setSelectedTaskId("");
      return;
    }
    setSelectedTaskId((prev) => (items.some((task) => task.task_id === prev) ? prev : items[0].task_id));
  };

  const refreshTools = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/tools`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toToolSummary).filter((item: ToolSummary | null): item is ToolSummary => !!item)
      : [];
    setTools(items);
    if (!selectedToolId && items[0]) {
      await selectTool(items[0].id);
    }
  };

  const selectTool = async (toolId: string) => {
    const normalized = safeText(toolId);
    if (!normalized) {
      return;
    }
    setSelectedToolId(normalized);
    const resp = await fetch(`${apiBase()}/api/v1/tools/${encodeURIComponent(normalized)}/descriptor`);
    const data = await readJsonOrThrow(resp);
    setSelectedDescriptor(isRecord(data?.item) ? (data.item as ToolDescriptor) : null);
  };

  const refreshTaskExecutions = async (projectId: string, taskId: string) => {
    if (!projectId || !taskId) {
      setHistoryRows([]);
      setLatestExecution(null);
      setLatestResult(null);
      return;
    }
    const resp = await fetch(
      `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/executions?limit=50`
    );
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
      : [];
    setHistoryRows(items);
  };

  const refreshDatabases = async (projectId: string) => {
    if (!projectId) {
      setDatabases([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/databases?include_status=true`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toDatabaseEntry).filter((item: DatabaseEntry | null): item is DatabaseEntry => !!item)
      : [];
    setDatabases(items);
  };

  const refreshLatestResult = async (projectId: string, task: Task | null) => {
    if (!projectId || !task?.latest_execution_id) {
      setLatestExecution(null);
      setLatestResult(null);
      return;
    }
    const [executionResp, resultResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/executions/${encodeURIComponent(task.latest_execution_id)}`),
      fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/workbench/executions/${encodeURIComponent(task.latest_execution_id)}/result`
      ),
    ]);
    const executionData = await readJsonOrThrow(executionResp);
    const resultData = await readJsonOrThrow(resultResp);
    setLatestExecution(isRecord(executionData?.item) ? executionData.item : null);
    setLatestResult(isRecord(resultData?.item) ? resultData.item : null);
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

  const createTask = async () => {
    if (!currentProjectId) {
      setError("请先选择项目。");
      return;
    }
    const title = createTaskTitle.trim();
    if (!title) {
      setError("任务标题不能为空。");
      return;
    }
    setBusyTaskCreate(true);
    setError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description: createTaskDescription.trim() }),
      });
      const data = await readJsonOrThrow(resp);
      const task = toTask(data?.item);
      setCreateTaskTitle("");
      setCreateTaskDescription("");
      await refreshTasks(currentProjectId);
      if (task) {
        setSelectedTaskId(task.task_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyTaskCreate(false);
    }
  };

  const runSelectedTool = async (params: Record<string, unknown>) => {
    if (!currentProjectId || !selectedTaskId || !selectedToolId) {
      setError("请先选择项目、任务和工具。");
      return;
    }
    setToolRunBusy(true);
    setToolRunMsg("");
    setError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/workbench/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          task_id: selectedTaskId,
          tool_id: selectedToolId,
          params,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const executionId = safeText(data?.item?.execution_id);
      setToolRunMsg(executionId ? `已提交任务执行: ${executionId}` : "已提交任务执行");
      await Promise.all([refreshTasks(currentProjectId), refreshTaskExecutions(currentProjectId, selectedTaskId)]);
      setActiveTab("history");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setToolRunBusy(false);
    }
  };

  const archiveExecution = async (executionId: string) => {
    if (!currentProjectId || !selectedTaskId) {
      return;
    }
    setBusyArchiveId(executionId);
    setError("");
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(executionId)}/archive`,
        { method: "POST" }
      );
      await readJsonOrThrow(resp);
      await Promise.all([refreshTasks(currentProjectId), refreshTaskExecutions(currentProjectId, selectedTaskId)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyArchiveId("");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshProjects();
        await refreshTools();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshTasks(currentProjectId), refreshDatabases(currentProjectId)]);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId]);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshTaskExecutions(currentProjectId, selectedTaskId), refreshLatestResult(currentProjectId, selectedTask)]);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId, selectedTask, selectedTaskId]);

  return (
    <ProjectWorkspaceShell
      activeView="workspace"
      projects={projects}
      currentProjectId={currentProjectId}
      tasks={filteredTasks}
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
      taskToolbar={
        <>
          <input
            className="control-input"
            value={taskSearch}
            onChange={(event) => setTaskSearch(event.target.value)}
            placeholder="搜索当前项目任务"
            aria-label="搜索当前项目任务"
          />
          <input
            className="control-input"
            value={createTaskTitle}
            onChange={(event) => setCreateTaskTitle(event.target.value)}
            placeholder="新任务标题"
            aria-label="新任务标题"
          />
          <textarea
            className="input-control textarea-control"
            value={createTaskDescription}
            onChange={(event) => setCreateTaskDescription(event.target.value)}
            placeholder="任务说明"
            aria-label="任务说明"
          />
          <button className="ui-button ui-button--primary" disabled={busyTaskCreate} onClick={() => void createTask()}>
            {busyTaskCreate ? "创建中..." : "新建任务"}
          </button>
        </>
      }
    >
      {!selectedTask ? (
        <WorkspaceEmptyState mark="Task" label="当前项目没有可用任务" hint="先在左侧创建任务，再进入单任务工作区。" />
      ) : (
        <section className="workspace-panel-card project-canvas">
          <header className="project-canvas-head">
            <div>
              <h2>{selectedTask.title}</h2>
              <p>{selectedTask.description || "当前任务用于承载长时程分析、执行和结果回看。"}</p>
              <div className="workspace-context-meta">
                <span>{mapStatusLabel(selectedTask.status)}</span>
                <span>{selectedTask.execution_count} executions</span>
                <span>{selectedTask.failed_execution_count} failed</span>
                <span>更新于 {formatTs(selectedTask.last_activity_at)}</span>
              </div>
            </div>
            <div className="project-canvas-tabs">
              {(["overview", "run", "history", "results", "databases"] as WorkspaceTab[]).map((tab) => (
                <button
                  key={tab}
                  className={`project-canvas-tab${activeTab === tab ? " active" : ""}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === "overview" ? "概览" : null}
                  {tab === "run" ? "执行" : null}
                  {tab === "history" ? "历史" : null}
                  {tab === "results" ? "结果" : null}
                  {tab === "databases" ? "数据库" : null}
                </button>
              ))}
            </div>
          </header>

          {activeTab === "overview" ? (
            <div className="project-canvas-grid">
              <section className="panel project-canvas-card">
                <WorkspaceSectionHeader title="任务摘要" description="持久化的任务元信息与最近状态。" />
                <div className="project-summary-stack">
                  <div className="project-summary-row">
                    <span>状态</span>
                    <strong>{mapStatusLabel(selectedTask.status)}</strong>
                  </div>
                  <div className="project-summary-row">
                    <span>最新执行</span>
                    <strong>{selectedTask.latest_execution_id || "暂无"}</strong>
                  </div>
                  <div className="project-summary-row">
                    <span>任务摘要</span>
                    <strong>{selectedTask.summary || "暂无摘要"}</strong>
                  </div>
                </div>
              </section>
              <section className="panel project-canvas-card">
                <WorkspaceSectionHeader title="最近产出" description="最近一次执行留下的结构化结果快照。" />
                {latestResult ? (
                  <pre className="workspace-json-surface">{JSON.stringify(latestResult, null, 2)}</pre>
                ) : (
                  <WorkspaceEmptyState mark="Res" label="暂无结果" hint="执行一次任务后，这里会显示最近一次结果载荷。" compact />
                )}
              </section>
            </div>
          ) : null}

          {activeTab === "run" ? (
            <RunsSection
              filteredTools={filteredTools}
              selectedToolId={selectedToolId}
              selectedDescriptor={selectedDescriptor}
              toolSearch={toolSearch}
              onToolSearchChange={setToolSearch}
              onSelectTool={selectTool}
              toolRunBusy={toolRunBusy}
              onRunTool={runSelectedTool}
              toolRunMsg={toolRunMsg}
            />
          ) : null}

          {activeTab === "history" ? (
            <HistorySection
              historyRows={historyRows}
              historySearch={historySearch}
              busyArchiveId={busyArchiveId}
              onHistorySearchChange={setHistorySearch}
              onRefresh={async () => {
                await refreshTaskExecutions(currentProjectId, selectedTask.task_id);
              }}
              onArchiveExecution={archiveExecution}
            />
          ) : null}

          {activeTab === "results" ? (
            <div className="project-canvas-grid">
              <section className="panel project-canvas-card">
                <WorkspaceSectionHeader title="最新执行" description="任务级结果视图基于 latest_execution_id。" />
                {latestExecution ? (
                  <pre className="workspace-json-surface">{JSON.stringify(latestExecution, null, 2)}</pre>
                ) : (
                  <WorkspaceEmptyState mark="Exec" label="暂无执行记录" hint="先在执行页触发一次工具运行。" compact />
                )}
              </section>
              <section className="panel project-canvas-card">
                <WorkspaceSectionHeader title="Workbench 结果" description="复用现有结果构建接口回看最新执行。" />
                {latestResult ? (
                  <pre className="workspace-json-surface">{JSON.stringify(latestResult, null, 2)}</pre>
                ) : (
                  <WorkspaceEmptyState mark="WB" label="暂无 workbench 结果" hint="只有已有 latest_execution_id 时才会加载。" compact />
                )}
              </section>
            </div>
          ) : null}

          {activeTab === "databases" ? (
            <DatabaseSection
              databases={databases}
              onRefresh={async () => {
                await refreshDatabases(currentProjectId);
              }}
            />
          ) : null}
        </section>
      )}
    </ProjectWorkspaceShell>
  );
}
