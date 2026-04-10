"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EllipsisHorizontalIcon, PencilSquareIcon } from "@heroicons/react/24/outline";

import { cn } from "@/lib/utils";

import { DatabaseSection, HistorySection, RunsSection } from "./detection_workspace_sections";
import type { DatabaseEntry, Execution, ToolDescriptor, ToolSummary } from "./detection_workspace_types";
import {
  apiBase,
  isRecord,
  readJsonOrThrow,
  safeText,
  toDatabaseEntry,
  toExecution,
  toToolSummary,
} from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { useWorkspaceShell } from "./workspace_shell_context";

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
  const {
    currentProject,
    currentProjectId,
    tasks,
    selectedTaskId,
    selectedExecutionId,
    projectExecutionRows,
    projectSummaryOpen,
    projectWorkspaceTab,
    renameProjectBusy,
    setShellError,
    setProjectWorkspaceTab,
    setSelectedExecutionId,
    refreshTasks,
    refreshProjectExecutions,
    refreshProjectExecutionSummary,
    renameProject,
  } = useWorkspaceShell();

  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [selectedToolId, setSelectedToolId] = useState("");
  const [selectedDescriptor, setSelectedDescriptor] = useState<ToolDescriptor | null>(null);
  const [toolRunBusy, setToolRunBusy] = useState(false);
  const [toolRunMsg, setToolRunMsg] = useState("");
  const [toolSearch, setToolSearch] = useState("");

  const [historyRows, setHistoryRows] = useState<Execution[]>([]);
  const [projectResultRows, setProjectResultRows] = useState<Array<Record<string, unknown>>>([]);
  const [historySearch, setHistorySearch] = useState("");
  const [busyArchiveId, setBusyArchiveId] = useState("");

  const [databases, setDatabases] = useState<DatabaseEntry[]>([]);
  const [latestExecution, setLatestExecution] = useState<Record<string, unknown> | null>(null);
  const [latestResult, setLatestResult] = useState<Record<string, unknown> | null>(null);

  const [renameTaskBusy, setRenameTaskBusy] = useState(false);
  const [taskTitleDraft, setTaskTitleDraft] = useState("");
  const [taskRenameOpen, setTaskRenameOpen] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [projectRenameOpen, setProjectRenameOpen] = useState(false);
  const [projectTitleDraft, setProjectTitleDraft] = useState("");
  const projectMenuRef = useRef<HTMLDivElement | null>(null);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) ?? null,
    [selectedTaskId, tasks]
  );
  const selectedExecution = useMemo(
    () => projectExecutionRows.find((execution) => execution.execution_id === selectedExecutionId) ?? null,
    [projectExecutionRows, selectedExecutionId]
  );
  const selectedExecutionLabel =
    safeText(selectedExecution?.sample_name) ||
    safeText(selectedExecution?.sample_id) ||
    safeText(selectedExecution?.execution_id);
  const selectedTaskTitle = safeText(selectedTask?.title);
  const preferredTaskTitle =
    selectedTaskTitle && !/^\d+$/.test(selectedTaskTitle) ? selectedTaskTitle : selectedExecutionLabel || selectedTaskTitle || "未命名任务";

  const filteredTools = useMemo(() => {
    const query = toolSearch.trim().toLowerCase();
    if (!query) {
      return tools;
    }
    return tools.filter((tool) => `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase().includes(query));
  }, [toolSearch, tools]);

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
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/executions?limit=50`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
      : [];
    setHistoryRows(items);
  };

  const refreshProjectResults = async (projectId: string) => {
    if (!projectId) {
      setProjectResultRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/results`);
    const data = await readJsonOrThrow(resp);
    setProjectResultRows(Array.isArray(data.items) ? data.items : []);
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

  const refreshLatestResult = async () => {
    if (!currentProjectId || !selectedTask?.latest_execution_id) {
      setLatestExecution(null);
      setLatestResult(null);
      return;
    }
    const [executionResp, resultResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(selectedTask.latest_execution_id)}`),
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/workbench/executions/${encodeURIComponent(selectedTask.latest_execution_id)}/result`),
    ]);
    const executionData = await readJsonOrThrow(executionResp);
    const resultData = await readJsonOrThrow(resultResp);
    setLatestExecution(isRecord(executionData?.item) ? executionData.item : null);
    setLatestResult(isRecord(resultData?.item) ? resultData.item : null);
  };

  const refreshExecutionResult = async (executionId: string) => {
    if (!currentProjectId || !executionId) {
      setLatestExecution(null);
      setLatestResult(null);
      return;
    }
    const [executionResp, resultResp] = await Promise.all([
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(executionId)}`),
      fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/workbench/executions/${encodeURIComponent(executionId)}/result`),
    ]);
    const executionData = await readJsonOrThrow(executionResp);
    const resultData = await readJsonOrThrow(resultResp);
    setLatestExecution(isRecord(executionData?.item) ? executionData.item : null);
    setLatestResult(isRecord(resultData?.item) ? resultData.item : null);
  };

  const renameTask = async (taskId: string, title: string) => {
    const trimmedTitle = title.trim();
    if (!currentProjectId || !taskId) {
      throw new Error("任务不存在。");
    }
    if (!trimmedTitle) {
      throw new Error("任务名称不能为空。");
    }
    setRenameTaskBusy(true);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/tasks/${encodeURIComponent(taskId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmedTitle }),
      });
      await readJsonOrThrow(resp);
      await refreshTasks(currentProjectId);
      setTaskRenameOpen(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setShellError(message);
      throw err;
    } finally {
      setRenameTaskBusy(false);
    }
  };

  const renameCurrentProject = async () => {
    await renameProject(projectTitleDraft, currentProject?.description ?? "");
    setProjectRenameOpen(false);
    setProjectMenuOpen(false);
  };

  const runSelectedTool = async (params: Record<string, unknown>) => {
    if (!currentProjectId || !selectedTaskId || !selectedToolId) {
      setShellError("请先选择项目、任务和工具。");
      return;
    }
    setToolRunBusy(true);
    setToolRunMsg("");
    setShellError("");
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
      setSelectedExecutionId(executionId);
      await Promise.all([
        refreshTasks(currentProjectId),
        refreshTaskExecutions(currentProjectId, selectedTaskId),
        refreshProjectExecutions(currentProjectId),
        refreshProjectExecutionSummary(currentProjectId, { force: true }),
      ]);
      setProjectWorkspaceTab("history");
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setToolRunBusy(false);
    }
  };

  const archiveExecution = async (executionId: string) => {
    if (!currentProjectId || !selectedTaskId) {
      return;
    }
    setBusyArchiveId(executionId);
    setShellError("");
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(executionId)}/archive`, {
        method: "POST",
      });
      await readJsonOrThrow(resp);
      await Promise.all([
        refreshTasks(currentProjectId),
        refreshTaskExecutions(currentProjectId, selectedTaskId),
        refreshProjectExecutions(currentProjectId),
        refreshProjectExecutionSummary(currentProjectId, { force: true }),
      ]);
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyArchiveId("");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshTools();
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [setShellError]);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshDatabases(currentProjectId), refreshProjectResults(currentProjectId)]);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId, setShellError]);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([
          refreshTaskExecutions(currentProjectId, selectedTaskId),
          selectedExecutionId ? refreshExecutionResult(selectedExecutionId) : refreshLatestResult(),
        ]);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId, selectedExecutionId, selectedTaskId, selectedTask?.latest_execution_id, setShellError]);

  useEffect(() => {
    setTaskTitleDraft(preferredTaskTitle);
    setTaskRenameOpen(false);
  }, [preferredTaskTitle, selectedTask?.task_id]);

  useEffect(() => {
    setProjectTitleDraft(currentProject?.name || "");
    setProjectRenameOpen(false);
    setProjectMenuOpen(false);
  }, [currentProject?.name]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!projectMenuRef.current?.contains(event.target as Node)) {
        setProjectMenuOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  useEffect(() => {
    const hasActiveTask = tasks.some((task) => {
      const normalized = task.status.trim();
      return normalized === "queued" || normalized === "in_progress" || normalized === "running";
    });
    if (!currentProjectId || !hasActiveTask) {
      return;
    }
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          await Promise.all([refreshTasks(currentProjectId), refreshTaskExecutions(currentProjectId, selectedTaskId), refreshProjectExecutions(currentProjectId), refreshProjectResults(currentProjectId)]);
          await refreshProjectExecutionSummary(currentProjectId, { force: true });
        } catch (err) {
          setShellError(err instanceof Error ? err.message : String(err));
        }
      })();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [currentProjectId, selectedTaskId, tasks, refreshProjectExecutionSummary, refreshProjectExecutions, refreshTasks, setShellError]);

  const projectBody = projectSummaryOpen ? (
    <section className="grid gap-[18px]">
      {projectResultRows.length === 0 ? (
        <WorkspaceEmptyState mark="Proj" label="当前项目暂无任务历史" hint="还没有执行记录时，点击项目名不会切换到项目汇总。" />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {projectResultRows.map((row) => (
            <article key={safeText(row.task_id, safeText(row.title))} className="panel p-4">
              <WorkspaceSectionHeader title={safeText(row.title, safeText(row.task_id))} description={safeText(row.summary, "暂无摘要")} aside={<span className="badge">{safeText(row.task_status, "pending")}</span>} titleAs="h4" />
              <div className="grid gap-3">
                <div className="row border-t border-[var(--workspace-line-soft)] pt-0 first:border-t-0">
                  <span>最新执行</span>
                  <strong>{safeText(row.latest_execution_id, "暂无")}</strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>最近工具</span>
                  <strong>{safeText(row.latest_tool_id, "未记录")}</strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>执行统计</span>
                  <strong>
                    {safeText(row.completed_count, "0")} completed / {safeText(row.failed_count, "0")} failed
                  </strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>最近活动</span>
                  <strong>{formatTs(Number(row.last_activity_at || 0))}</strong>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  ) : !selectedTask ? (
    <WorkspaceEmptyState mark="Task" label="当前项目没有可用任务" hint="先在左侧创建任务，再进入单任务工作区。" />
  ) : (
    <section className="grid gap-[18px]">
      <header className="flex flex-col items-start justify-between gap-4 xl:flex-row">
        <div>
          <div className="task-title-row">
            {taskRenameOpen ? (
              <>
                <input
                  className="control-input task-title-input"
                  value={taskTitleDraft}
                  onChange={(event) => setTaskTitleDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void renameTask(selectedTask.task_id, taskTitleDraft);
                    }
                    if (event.key === "Escape") {
                      setTaskRenameOpen(false);
                      setTaskTitleDraft(selectedTask.title);
                    }
                  }}
                  autoFocus
                />
                <button type="button" className="control-btn" disabled={renameTaskBusy} onClick={() => void renameTask(selectedTask.task_id, taskTitleDraft)}>
                  {renameTaskBusy ? "保存中..." : "保存"}
                </button>
                <button
                  type="button"
                  className="control-btn"
                  onClick={() => {
                    setTaskRenameOpen(false);
                    setTaskTitleDraft(selectedTask.title);
                  }}
                >
                  取消
                </button>
              </>
            ) : (
              <>
                <h2>{preferredTaskTitle}</h2>
                <button type="button" className="task-title-rename-btn" aria-label="重命名任务" onClick={() => setTaskRenameOpen(true)}>
                  <PencilSquareIcon className="task-title-rename-icon" />
                </button>
              </>
            )}
          </div>
          <p>{selectedTask.description || "当前任务用于承载长时程分析、执行和结果回看。"}</p>
          <div className="workspace-context-meta">
            <span>{mapStatusLabel(selectedTask.status)}</span>
            <span>{selectedTask.execution_count} executions</span>
            <span>{selectedTask.failed_execution_count} failed</span>
            <span>更新于 {formatTs(selectedTask.last_activity_at)}</span>
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {(["overview", "run", "history", "results", "databases"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              className={cn(
                "rounded-full border border-transparent bg-transparent px-3 py-1.5 text-sm text-[var(--text-main)] transition-colors hover:bg-[var(--workspace-selection)]",
                projectWorkspaceTab === tab && "border-[var(--workspace-selection-border)] bg-[var(--workspace-selection)]"
              )}
              onClick={() => setProjectWorkspaceTab(tab)}
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

      {projectWorkspaceTab === "overview" ? (
        <div className="grid gap-4">
          <section className="panel p-4">
            <WorkspaceSectionHeader title="任务摘要" description="持久化的任务元信息与最近状态。" />
            <div className="grid gap-3">
              <div className="row border-t border-[var(--workspace-line-soft)] pt-0 first:border-t-0">
                <span>状态</span>
                <strong>{mapStatusLabel(selectedTask.status)}</strong>
              </div>
              <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                <span>最新执行</span>
                <strong>{selectedTask.latest_execution_id || "暂无"}</strong>
              </div>
              <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                <span>任务摘要</span>
                <strong>{selectedTask.summary || "暂无摘要"}</strong>
              </div>
            </div>
          </section>
        </div>
      ) : null}

      {projectWorkspaceTab === "run" ? (
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

      {projectWorkspaceTab === "history" ? (
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

      {projectWorkspaceTab === "results" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="panel p-4">
            <WorkspaceSectionHeader title="最新执行" description="任务级结果视图基于 latest_execution_id。" />
            {latestExecution ? <pre className="workspace-json-surface">{JSON.stringify(latestExecution, null, 2)}</pre> : <WorkspaceEmptyState mark="Exec" label="暂无执行记录" hint="先在执行页触发一次工具运行。" compact />}
          </section>
          <section className="panel p-4">
            <WorkspaceSectionHeader title="Workbench 结果" description="复用现有结果构建接口回看最新执行。" />
            {latestResult ? <pre className="workspace-json-surface">{JSON.stringify(latestResult, null, 2)}</pre> : <WorkspaceEmptyState mark="WB" label="暂无 workbench 结果" hint="只有已有 latest_execution_id 时才会加载。" compact />}
          </section>
        </div>
      ) : null}

      {projectWorkspaceTab === "databases" ? <DatabaseSection databases={databases} onRefresh={async () => refreshDatabases(currentProjectId)} /> : null}
    </section>
  );

  return (
    <section className="project-workspace-content">
      <header className="project-workspace-head">
        <div className="project-workspace-head-main">
          <div className="project-workspace-title-row">
            {projectRenameOpen ? (
              <div className="project-workspace-rename-row">
                <input
                  className="control-input project-workspace-title-input"
                  value={projectTitleDraft}
                  onChange={(event) => setProjectTitleDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void renameCurrentProject();
                    }
                    if (event.key === "Escape") {
                      setProjectRenameOpen(false);
                      setProjectTitleDraft(currentProject?.name || "");
                    }
                  }}
                  autoFocus
                />
                <button type="button" className="control-btn" disabled={renameProjectBusy} onClick={() => void renameCurrentProject()}>
                  {renameProjectBusy ? "保存中..." : "保存"}
                </button>
                <button
                  type="button"
                  className="control-btn"
                  onClick={() => {
                    setProjectRenameOpen(false);
                    setProjectTitleDraft(currentProject?.name || "");
                  }}
                >
                  取消
                </button>
              </div>
            ) : (
              <>
                <h1>{currentProject?.name || "未选择项目"}</h1>
                <div className="project-workspace-menu-wrap" ref={projectMenuRef}>
                  <button type="button" className="project-workspace-menu-trigger" aria-label="项目菜单" aria-expanded={projectMenuOpen} onClick={() => setProjectMenuOpen((open) => !open)}>
                    <EllipsisHorizontalIcon className="sidebar-nav-menu-icon" />
                  </button>
                  {projectMenuOpen ? (
                    <div className="project-workspace-menu">
                      <button
                        type="button"
                        className="project-workspace-menu-item"
                        onClick={() => {
                          setProjectRenameOpen(true);
                          setProjectMenuOpen(false);
                        }}
                      >
                        重命名项目
                      </button>
                    </div>
                  ) : null}
                </div>
              </>
            )}
          </div>
          {currentProject?.description ? <p className="project-workspace-description">{currentProject.description}</p> : null}
        </div>
      </header>
      {projectBody}
    </section>
  );
}
