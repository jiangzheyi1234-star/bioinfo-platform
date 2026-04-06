"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { Project, TabId } from "./detection_workspace_types";
import { apiBase } from "./detection_workspace_utils";

export const NAV_ITEMS: Array<{ id: TabId; href: string; label: string; note: string; hotkey: string }> = [
  { id: "projects", href: "/projects", label: "项目", note: "创建、切换、管理", hotkey: "Alt+1" },
  { id: "samples", href: "/samples", label: "样本", note: "列表与录入", hotkey: "Alt+2" },
  { id: "runs", href: "/runs", label: "执行", note: "工具与参数提交", hotkey: "Alt+3" },
  { id: "history", href: "/history", label: "历史", note: "记录与归档", hotkey: "Alt+4" },
  { id: "databases", href: "/databases", label: "数据库", note: "路径与状态", hotkey: "Alt+5" },
  { id: "settings", href: "/settings", label: "系统设置", note: "连接与配置", hotkey: "Alt+6" },
  { id: "workbench", href: "/workbench", label: "高级工作流", note: "观测与结果台", hotkey: "Alt+7" },
];

const TAB_TITLES: Record<TabId, string> = {
  projects: "项目工作台",
  samples: "样本管理",
  runs: "执行中心",
  history: "历史归档",
  databases: "数据库状态",
  settings: "系统设置",
  workbench: "高级工作流",
};

const TAB_DESCRIPTIONS: Record<TabId, string> = {
  projects: "管理项目生命周期，确定当前上下文与执行目标。",
  samples: "维护样本清单、来源和元数据，为执行与追踪提供稳定上下文。",
  runs: "按工具配置参数并提交任务，保持执行语义一致。",
  history: "追踪执行记录与归档状态，快速过滤与定位。",
  databases: "确认数据库路径、类别和可用状态。",
  settings: "维护系统配置，并显式管理 SSH 生命周期。",
  workbench: "聚合视图、结果、产物与远程状态。",
};

type DetectionWorkspaceShellProps = {
  activeTab: TabId;
  currentProject: Project | undefined;
  currentProjectId: string;
  projects: Project[];
  toolsCount: number;
  historyCount: number;
  databasesCount: number;
  error: string;
  projectSelect: ReactNode;
  onRefreshProjects: () => void;
  children: ReactNode;
};

export function DetectionWorkspaceShell({
  activeTab,
  currentProject,
  currentProjectId,
  projects,
  toolsCount,
  historyCount,
  databasesCount,
  error,
  projectSelect,
  onRefreshProjects,
  children,
}: DetectionWorkspaceShellProps) {
  return (
    <main className="app-shell">
      <aside className="app-sidebar" aria-label="主导航">
        <div className="sidebar-brand">
          <h1>H2OMeta</h1>
          <p>Desktop Workspace</p>
        </div>
        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <Link key={item.id} className={`sidebar-nav-link${activeTab === item.id ? " active" : ""}`} href={item.href}>
              <span className="sidebar-nav-title">{item.label}</span>
              <span className="sidebar-nav-note">{item.note}</span>
              <span className="sidebar-nav-hotkey">{item.hotkey}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <p>快捷键：Alt + 1/2/3/4/5/6/7</p>
          <p>后端：{apiBase()}</p>
        </div>
      </aside>

      <section className="app-main">
        <header className="page-head">
          <div className="page-head-copy">
            <h2>{TAB_TITLES[activeTab]}</h2>
            <p>{TAB_DESCRIPTIONS[activeTab]}</p>
            <div className="workspace-context-meta">
              <span>{currentProject?.name || "未选择项目"}</span>
              {currentProjectId ? <span>{currentProjectId}</span> : null}
              <span>{projects.length} projects</span>
              <span>{toolsCount} tools</span>
              <span>{historyCount} runs</span>
              <span>{databasesCount} databases</span>
            </div>
          </div>
          <div className="page-head-actions">
            {projectSelect}
            <button className="control-btn" onClick={onRefreshProjects}>
              刷新项目
            </button>
          </div>
        </header>

        {error ? (
          <div className="notice-error" role="alert">
            <strong>API Error</strong>
            <pre>{error}</pre>
          </div>
        ) : null}

        <section className="content-card">{children}</section>

        <footer className="page-footnote">
          {currentProject?.description ? currentProject.description : "当前页面使用同一项目上下文、同一 API 底座和同一交互语言。"}
        </footer>
      </section>
    </main>
  );
}
