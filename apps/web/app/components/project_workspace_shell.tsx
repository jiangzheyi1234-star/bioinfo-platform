"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { Project, Task } from "./detection_workspace_types";
import { apiBase } from "./detection_workspace_utils";

type ProjectWorkspaceShellProps = {
  activeView: "workspace" | "results" | "settings";
  projects: Project[];
  currentProjectId: string;
  tasks: Task[];
  selectedTaskId: string;
  error: string;
  onSelectProject: (projectId: string) => void;
  onSelectTask: (taskId: string) => void;
  projectControls?: ReactNode;
  taskToolbar?: ReactNode;
  children: ReactNode;
};

function navClass(active: boolean): string {
  return `project-shell-nav-link${active ? " active" : ""}`;
}

function taskClass(active: boolean): string {
  return `project-task-item${active ? " active" : ""}`;
}

export function ProjectWorkspaceShell({
  activeView,
  projects,
  currentProjectId,
  tasks,
  selectedTaskId,
  error,
  onSelectProject,
  onSelectTask,
  projectControls,
  taskToolbar,
  children,
}: ProjectWorkspaceShellProps) {
  return (
    <main className="project-shell">
      <aside className="project-shell-sidebar" aria-label="项目与任务导航">
        <div className="project-shell-brand">
          <div>
            <h1>H2OMeta</h1>
            <p>Project Workspace</p>
          </div>
          <div className="project-shell-nav">
            <Link className={navClass(activeView === "workspace")} href="/projects">
              工作区
            </Link>
            <Link className={navClass(activeView === "results")} href="/results">
              结果
            </Link>
            <Link className={navClass(activeView === "settings")} href="/settings">
              设置
            </Link>
          </div>
        </div>

        <section className="project-sidebar-section">
          <div className="project-sidebar-section-head">
            <strong>项目</strong>
            <span className="badge">{projects.length}</span>
          </div>
          <div className="project-sidebar-list">
            {projects.map((project) => {
              const active = project.project_id === currentProjectId;
              return (
                <button
                  key={project.project_id}
                  className={`project-sidebar-item${active ? " active" : ""}`}
                  onClick={() => onSelectProject(project.project_id)}
                >
                  <span className="project-sidebar-item-title">{project.name}</span>
                  <span className="project-sidebar-item-meta">{project.project_id}</span>
                </button>
              );
            })}
          </div>
          {projectControls ? <div className="project-sidebar-controls">{projectControls}</div> : null}
        </section>

        {taskToolbar ? (
          <section className="project-sidebar-section">
            <div className="project-sidebar-section-head">
              <strong>任务工具栏</strong>
              <span className="badge">focus</span>
            </div>
            <div className="project-sidebar-controls">{taskToolbar}</div>
          </section>
        ) : null}

        <section className="project-sidebar-section project-sidebar-section--fill">
          <div className="project-sidebar-section-head">
            <strong>任务列表</strong>
            <span className="badge">{tasks.length}</span>
          </div>
          <div className="project-task-list">
            {tasks.map((task) => (
              <button
                key={task.task_id}
                className={taskClass(task.task_id === selectedTaskId)}
                onClick={() => onSelectTask(task.task_id)}
              >
                <span className={`project-task-status project-task-status--${task.status}`} aria-hidden="true" />
                <span className="project-task-copy">
                  <strong>{task.title}</strong>
                  <span>{task.summary || task.status}</span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <footer className="project-shell-footer">
          <p>{apiBase()}</p>
        </footer>
      </aside>

      <section className="project-shell-main">
        {error ? (
          <div className="notice-error" role="alert">
            <strong>API Error</strong>
            <pre>{error}</pre>
          </div>
        ) : null}
        {children}
      </section>
    </main>
  );
}
