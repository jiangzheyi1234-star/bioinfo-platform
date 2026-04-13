"use client";

import { useEffect, useRef, useState } from "react";
import { ArchiveBoxIcon, ChevronRightIcon, EllipsisHorizontalIcon, FolderIcon, PlusIcon, TrashIcon } from "@heroicons/react/24/outline";

import type { Execution, Project } from "./detection_workspace_types";

type ProjectSidebarSectionProps = {
  projects: Project[];
  currentProjectId: string;
  executionItemsByProject?: Record<string, Execution[]>;
  executionLoadingByProject?: Record<string, boolean>;
  selectedExecutionId?: string;
  createProjectBusy?: boolean;
  projectActionBusyId?: string;
  onOpenProject: (projectId: string) => Promise<void>;
  onSelectProjectSummary?: (projectId: string) => void;
  onSelectTask?: (taskId: string) => void;
  onSelectExecution?: (execution: Execution) => void;
  onCreateProject: (name: string, description: string) => Promise<void>;
  onArchiveProject: (projectId: string) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  onLoadProjectExecutions?: (projectId: string) => Promise<void>;
};

function mapTaskStatusLabel(status: string): string {
  const normalized = status.trim();
  if (normalized === "queued") return "排队中";
  if (normalized === "in_progress") return "执行中";
  if (normalized === "completed") return "已完成";
  if (normalized === "failed") return "失败";
  if (normalized === "cancelled") return "已取消";
  return normalized || "待处理";
}

function isRunningStatus(status: string): boolean {
  const normalized = status.trim();
  return normalized === "queued" || normalized === "in_progress" || normalized === "running";
}

export function ProjectSidebarSection({
  projects,
  currentProjectId,
  executionItemsByProject = {},
  executionLoadingByProject = {},
  selectedExecutionId = "",
  createProjectBusy = false,
  projectActionBusyId = "",
  onOpenProject,
  onSelectProjectSummary,
  onSelectTask,
  onSelectExecution,
  onCreateProject,
  onArchiveProject,
  onDeleteProject,
  onLoadProjectExecutions,
}: ProjectSidebarSectionProps) {
  const [creatorOpen, setCreatorOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [expandedProjectIds, setExpandedProjectIds] = useState<Record<string, boolean>>({});
  const [openMenuProjectId, setOpenMenuProjectId] = useState("");
  const [pendingDeleteProject, setPendingDeleteProject] = useState<Project | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const submitCreate = async () => {
    await onCreateProject(projectName, projectDescription);
    setProjectName("");
    setProjectDescription("");
    setCreatorOpen(false);
  };

  useEffect(() => {
    if (!currentProjectId) {
      return;
    }
    setExpandedProjectIds((prev) => ({ ...prev, [currentProjectId]: true }));
  }, [currentProjectId]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpenMenuProjectId("");
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  return (
    <section className="sidebar-project-section" aria-label="项目和任务">
      <div className="sidebar-project-head">
        <span className="sidebar-project-title">
          <FolderIcon className="sidebar-project-title-icon" />
          <span>项目</span>
        </span>
        <button
          type="button"
          className="sidebar-project-create-btn"
          aria-label="新建项目"
          onClick={() => setCreatorOpen((open) => !open)}
        >
          <PlusIcon className="sidebar-project-create-icon" />
        </button>
      </div>

      {creatorOpen ? (
        <div className="sidebar-project-creator" aria-label="新建项目表单">
          <label className="sidebar-project-field">
            <input
              className="sidebar-project-inline-input"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="输入项目名称"
            />
          </label>
          <label className="sidebar-project-field">
            <textarea
              className="sidebar-project-inline-input sidebar-project-textarea"
              value={projectDescription}
              onChange={(event) => setProjectDescription(event.target.value)}
              placeholder="可选：记录项目目标"
            />
          </label>
          <div className="sidebar-project-creator-actions">
            <button
              type="button"
              className="sidebar-project-inline-action sidebar-project-inline-action--primary"
              disabled={createProjectBusy}
              onClick={() => {
                void submitCreate();
              }}
            >
              {createProjectBusy ? "创建中..." : "创建项目"}
            </button>
            <button
              type="button"
              className="sidebar-project-inline-action"
              onClick={() => setCreatorOpen(false)}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}

      <div className="sidebar-project-list">
        {projects.length === 0 ? <div className="sidebar-task-empty">暂无项目</div> : null}
        {projects.map((project) => {
          const activeProject = project.project_id === currentProjectId;
          const expanded = expandedProjectIds[project.project_id] ?? activeProject;
          const hasExecutionCache = Object.prototype.hasOwnProperty.call(executionItemsByProject, project.project_id);
          const projectExecutionItems = executionItemsByProject[project.project_id] ?? [];
          const projectExecutionLoading = executionLoadingByProject[project.project_id] === true;
          const showExecutionSummary = typeof onLoadProjectExecutions === "function" || projectExecutionItems.length > 0;
          const menuOpen = openMenuProjectId === project.project_id;
          const actionBusy = projectActionBusyId === project.project_id;
          return (
            <div key={project.project_id} className="sidebar-project-entry">
              <div className={`sidebar-project-row${activeProject ? " active" : ""}`}>
                <button
                  type="button"
                  className={`sidebar-project-current${activeProject ? " active" : ""}`}
                  onClick={() => {
                    if (activeProject && showExecutionSummary && projectExecutionItems.length > 0) {
                      onSelectProjectSummary?.(project.project_id);
                      return;
                    }
                    if (!activeProject) {
                      void onOpenProject(project.project_id);
                    }
                  }}
                >
                  <span className="sidebar-project-current-label" title={project.name}>
                    {project.name}
                  </span>
                </button>
                <div className="sidebar-project-actions" ref={menuOpen ? menuRef : null}>
                  <button
                    type="button"
                    className="sidebar-project-menu-trigger"
                    aria-label="项目操作"
                    aria-expanded={menuOpen}
                    onClick={() => {
                      setOpenMenuProjectId((current) => (current === project.project_id ? "" : project.project_id));
                    }}
                  >
                    <EllipsisHorizontalIcon className="sidebar-project-menu-icon" />
                  </button>
                  {menuOpen ? (
                    <div className="sidebar-project-menu">
                      <button
                        type="button"
                        className="sidebar-project-menu-item"
                        disabled={actionBusy}
                        onClick={() => {
                          setOpenMenuProjectId("");
                          void onArchiveProject(project.project_id);
                        }}
                      >
                        <ArchiveBoxIcon className="sidebar-project-menu-item-icon" />
                        <span>{actionBusy ? "处理中..." : "归档"}</span>
                      </button>
                      <button
                        type="button"
                        className="sidebar-project-menu-item sidebar-project-menu-item--danger"
                        disabled={actionBusy}
                        onClick={() => {
                          setOpenMenuProjectId("");
                          setPendingDeleteProject(project);
                        }}
                      >
                        <TrashIcon className="sidebar-project-menu-item-icon" />
                        <span>{actionBusy ? "处理中..." : "彻底删除"}</span>
                      </button>
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="sidebar-project-toggle"
                  aria-label={expanded ? "折叠项目" : "展开项目"}
                  aria-expanded={expanded}
                  onClick={() => {
                    const nextExpanded = !expanded;
                    setExpandedProjectIds((prev) => ({
                      ...prev,
                      [project.project_id]: nextExpanded,
                    }));
                    if (
                      nextExpanded &&
                      showExecutionSummary &&
                      !hasExecutionCache &&
                      !projectExecutionLoading &&
                      onLoadProjectExecutions
                    ) {
                      void onLoadProjectExecutions(project.project_id);
                    }
                  }}
                >
                  <ChevronRightIcon className={`sidebar-project-toggle-icon${expanded ? " expanded" : ""}`} />
                </button>
              </div>

              {activeProject && expanded && showExecutionSummary ? (
                <div className="sidebar-task-list">
                  {projectExecutionLoading ? (
                    <div className="sidebar-task-empty">加载中...</div>
                  ) : null}
                  {!projectExecutionLoading && hasExecutionCache && projectExecutionItems.length === 0 ? (
                    <div className="sidebar-task-empty">当前项目暂无执行记录</div>
                  ) : null}
                  {!projectExecutionLoading && projectExecutionItems.map((execution) => {
                    const active = execution.execution_id === selectedExecutionId;
                    const running = isRunningStatus(execution.status);
                    const label = execution.sample_name || execution.sample_id || execution.execution_id;
                    return (
                      <div
                        key={execution.execution_id}
                        className={`sidebar-task-item${active ? " active" : ""}${running ? " running" : ""}`}
                      >
                        <button
                          type="button"
                          className="sidebar-task-main sidebar-task-main-btn"
                          onClick={() => {
                            if (execution.task_id && onSelectTask) {
                              onSelectTask(execution.task_id);
                            }
                            onSelectExecution?.(execution);
                          }}
                        >
                          <div className="sidebar-task-title-row">
                            <strong className="sidebar-task-title-text" title={label}>
                              {label}
                            </strong>
                            <span className="sidebar-task-trailing">
                              <span className={`sidebar-task-state${running ? " sidebar-task-state--running" : ""}`}>
                                {mapTaskStatusLabel(execution.status)}
                              </span>
                            </span>
                          </div>
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {pendingDeleteProject ? (
        <div className="workspace-confirm-overlay" role="presentation">
          <div className="workspace-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-project-title">
            <div className="workspace-confirm-copy">
              <strong id="delete-project-title">确认彻底删除项目“{pendingDeleteProject.name}”吗？</strong>
              <p>这会同时删除该项目下的任务历史、执行结果和相关文件，且不可恢复。</p>
            </div>
            <div className="workspace-confirm-actions">
              <button
                type="button"
                className="control-btn"
                onClick={() => setPendingDeleteProject(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="control-btn workspace-confirm-danger-btn"
                disabled={projectActionBusyId === pendingDeleteProject.project_id}
                onClick={() => {
                  const targetProject = pendingDeleteProject;
                  setPendingDeleteProject(null);
                  void onDeleteProject(targetProject.project_id);
                }}
              >
                {projectActionBusyId === pendingDeleteProject.project_id ? "删除中..." : "彻底删除"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
