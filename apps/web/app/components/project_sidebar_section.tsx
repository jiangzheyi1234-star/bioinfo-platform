"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArchiveBoxIcon, EllipsisHorizontalIcon, PlusIcon, TrashIcon } from "@heroicons/react/24/outline";

import type { Project, Task } from "./detection_workspace_types";

type ProjectSidebarSectionProps = {
  projects: Project[];
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  createProjectBusy?: boolean;
  createTaskBusy?: boolean;
  projectActionBusyId?: string;
  onOpenProject: (projectId: string) => Promise<void>;
  onOpenTask: (taskId: string) => void;
  onCreateProject: (name: string, description: string) => Promise<void>;
  onCreateTask: (title: string, description?: string) => Promise<void>;
  onArchiveProject: (projectId: string) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
};

export function ProjectSidebarSection({
  projects,
  currentProjectId,
  tasks,
  selectedTaskId,
  createProjectBusy = false,
  createTaskBusy = false,
  projectActionBusyId = "",
  onOpenProject,
  onOpenTask,
  onCreateProject,
  onCreateTask,
  onArchiveProject,
  onDeleteProject,
}: ProjectSidebarSectionProps) {
  const [creatorOpen, setCreatorOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectDescription, setProjectDescription] = useState("");
  const [openMenuProjectId, setOpenMenuProjectId] = useState("");
  const [pendingDeleteProject, setPendingDeleteProject] = useState<Project | null>(null);
  const [taskCreatorOpen, setTaskCreatorOpen] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const menuRef = useRef<HTMLDivElement | null>(null);

  const deleteProjectDialog = pendingDeleteProject ? (
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
  ) : null;

  const submitCreate = async () => {
    await onCreateProject(projectName, projectDescription);
    setProjectName("");
    setProjectDescription("");
    setCreatorOpen(false);
  };

  const submitCreateTask = async () => {
    await onCreateTask(taskTitle, taskDescription);
    setTaskTitle("");
    setTaskDescription("");
    setTaskCreatorOpen(false);
  };

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
        <div className="sidebar-project-head-copy">
          <span className="sidebar-project-title">Projects</span>
          <span className="sidebar-project-count">{projects.length}</span>
        </div>
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
          const menuOpen = openMenuProjectId === project.project_id;
          const actionBusy = projectActionBusyId === project.project_id;
          return (
            <div key={project.project_id} className="sidebar-project-entry">
              <div className={`sidebar-project-row${activeProject ? " active" : ""}`}>
                <button
                  type="button"
                  className={`sidebar-project-current${activeProject ? " active" : ""}`}
                  onClick={() => {
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
              </div>
              {activeProject ? (
                <>
                  <div className="sidebar-project-subhead">
                    <span className="sidebar-project-subtitle">Tasks</span>
                    <span className="sidebar-project-subcount">{tasks.length}</span>
                  </div>
                  {taskCreatorOpen ? (
                    <div className="sidebar-project-creator" aria-label="新建任务表单">
                      <label className="sidebar-project-field">
                        <input
                          className="sidebar-project-inline-input"
                          value={taskTitle}
                          onChange={(event) => setTaskTitle(event.target.value)}
                          placeholder="输入 Task 名称"
                        />
                      </label>
                      <label className="sidebar-project-field">
                        <textarea
                          className="sidebar-project-inline-input sidebar-project-textarea"
                          value={taskDescription}
                          onChange={(event) => setTaskDescription(event.target.value)}
                          placeholder="可选：记录 Task 目标"
                        />
                      </label>
                      <div className="sidebar-project-creator-actions">
                        <button
                          type="button"
                          className="sidebar-project-inline-action sidebar-project-inline-action--primary"
                          disabled={createTaskBusy}
                          onClick={() => {
                            void submitCreateTask();
                          }}
                        >
                          {createTaskBusy ? "创建中..." : "创建 Task"}
                        </button>
                        <button
                          type="button"
                          className="sidebar-project-inline-action"
                          onClick={() => setTaskCreatorOpen(false)}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="sidebar-project-creator-actions sidebar-project-task-actions">
                      <button
                        type="button"
                        className="sidebar-project-inline-action"
                        onClick={() => setTaskCreatorOpen(true)}
                      >
                        + 新建 Task
                      </button>
                    </div>
                  )}
                  <div className="sidebar-task-list">
                    {tasks.length === 0 ? <div className="sidebar-task-empty">暂无任务</div> : null}
                    {tasks.map((task) => {
                      const activeTask = task.task_id === selectedTaskId;
                      const running = task.status === "running" || task.status === "in_progress";
                      return (
                        <button
                          key={task.task_id}
                          type="button"
                          className={`sidebar-task-item${activeTask ? " active" : ""}${running ? " running" : ""}`}
                          onClick={() => onOpenTask(task.task_id)}
                        >
                          <div className="sidebar-task-main">
                            <div className="sidebar-task-title-row">
                              <span className="sidebar-task-title-text" title={task.title}>
                                {task.title}
                              </span>
                              <span className={`sidebar-task-state${running ? " sidebar-task-state--running" : ""}`}>
                                {task.status}
                              </span>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </>
              ) : null}
            </div>
          );
        })}
      </div>
      {deleteProjectDialog && typeof document !== "undefined" ? createPortal(deleteProjectDialog, document.body) : null}
    </section>
  );
}
