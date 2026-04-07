"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Cog6ToothIcon, LinkIcon } from "@heroicons/react/24/outline";

import type { Project, TabId, Task } from "./detection_workspace_types";

const LEFT_SIDEBAR_STORAGE_KEY = "h2ometa:left-sidebar-width";
const DEFAULT_LEFT_SIDEBAR_WIDTH = 272;
const MIN_LEFT_SIDEBAR_WIDTH = 200;
const MAX_LEFT_SIDEBAR_WIDTH = 350;

export const NAV_ITEMS: Array<{ id: TabId; href: string; label: string; note: string; hotkey: string }> = [
  { id: "connect", href: "/connect", label: "连接", note: "SSH 与远端状态", hotkey: "Alt+6" },
  { id: "settings", href: "/settings", label: "系统设置", note: "全局配置与偏好", hotkey: "Alt+7" },
];

const TAB_TITLES: Record<TabId, string> = {
  projects: "项目工作台",
  samples: "样本管理",
  runs: "执行中心",
  history: "历史归档",
  databases: "数据库状态",
  connect: "远端连接",
  settings: "系统设置",
  workbench: "高级工作流",
};

const TAB_DESCRIPTIONS: Record<TabId, string> = {
  projects: "管理项目生命周期，确定当前上下文与执行目标。",
  samples: "维护样本清单、来源和元数据，为执行与追踪提供稳定上下文。",
  runs: "按工具配置参数并提交任务，保持执行语义一致。",
  history: "追踪执行记录与归档状态，快速过滤与定位。",
  databases: "确认数据库路径、类别和可用状态。",
  connect: "管理 SSH 连接、测试与远端会话状态。",
  settings: "维护系统配置和本地工作台偏好。",
  workbench: "聚合视图、结果、产物与远程状态。",
};

type DetectionWorkspaceShellProps = {
  activeTab: TabId;
  pageTitle?: string;
  pageDescription?: string;
  hidePageMeta?: boolean;
  hideFooterNote?: boolean;
  currentProject?: Project;
  currentProjectId: string;
  projects: Project[];
  tasks?: Task[];
  selectedTaskId?: string;
  toolsCount?: number;
  historyCount?: number;
  databasesCount?: number;
  error?: string;
  projectSelect?: ReactNode;
  onRefreshProjects?: () => void;
  onSelectProject?: (projectId: string) => void;
  onSelectTask?: (taskId: string) => void;
  children: ReactNode;
};

function clampSidebarWidth(value: number) {
  return Math.min(MAX_LEFT_SIDEBAR_WIDTH, Math.max(MIN_LEFT_SIDEBAR_WIDTH, Math.round(value)));
}

function readStoredSidebarWidth() {
  const stored = window.localStorage.getItem(LEFT_SIDEBAR_STORAGE_KEY);
  if (stored === null) {
    return DEFAULT_LEFT_SIDEBAR_WIDTH;
  }
  const parsed = Number(stored);
  if (!Number.isFinite(parsed)) {
    window.localStorage.removeItem(LEFT_SIDEBAR_STORAGE_KEY);
    return DEFAULT_LEFT_SIDEBAR_WIDTH;
  }
  return clampSidebarWidth(parsed);
}

export function DetectionWorkspaceShell({
  activeTab,
  pageTitle,
  pageDescription,
  hidePageMeta = false,
  hideFooterNote = false,
  currentProject,
  currentProjectId,
  projects,
  tasks = [],
  selectedTaskId = "",
  toolsCount,
  historyCount,
  databasesCount,
  error = "",
  projectSelect,
  onRefreshProjects,
  onSelectProject,
  onSelectTask,
  children,
}: DetectionWorkspaceShellProps) {
  const [sidebarWidth, setSidebarWidth] = useState<number>(DEFAULT_LEFT_SIDEBAR_WIDTH);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const hasUserResizedRef = useRef(false);

  const resolvedCurrentProject = useMemo(
    () => currentProject ?? projects.find((project) => project.project_id === currentProjectId),
    [currentProject, currentProjectId, projects]
  );
  const showPageActions = !!projectSelect || !!onRefreshProjects;
  const workspaceMeta = [
    resolvedCurrentProject?.name || "未选择项目",
    currentProjectId || "",
    typeof toolsCount === "number" ? `${toolsCount} tools` : "",
    typeof historyCount === "number" ? `${historyCount} runs` : "",
    typeof databasesCount === "number" ? `${databasesCount} databases` : "",
  ].filter(Boolean);

  useEffect(() => {
    setSidebarWidth(readStoredSidebarWidth());
  }, []);

  useEffect(() => {
    if (!hasUserResizedRef.current) {
      return;
    }
    window.localStorage.setItem(LEFT_SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const state = dragStateRef.current;
      if (!state) {
        return;
      }
      hasUserResizedRef.current = true;
      setSidebarWidth(clampSidebarWidth(state.startWidth + event.clientX - state.startX));
    };

    const stopDragging = () => {
      if (!dragStateRef.current) {
        return;
      }
      dragStateRef.current = null;
      document.body.classList.remove("sidebar-resizing");
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    window.addEventListener("blur", stopDragging);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
      window.removeEventListener("blur", stopDragging);
      document.body.classList.remove("sidebar-resizing");
    };
  }, []);

  return (
    <main className="app-shell" style={{ "--workspace-sidebar-width": `${sidebarWidth}px` } as CSSProperties}>
      <aside className="app-sidebar" aria-label="主导航">
        <nav className="sidebar-nav sidebar-nav--top">
          <Link className={`sidebar-nav-link${activeTab === "connect" ? " active" : ""}`} href="/connect">
            <LinkIcon className="sidebar-nav-icon" />
            <span className="sidebar-nav-title">连接</span>
          </Link>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-footer sidebar-footer--nav">
          <Link className={`sidebar-nav-link${activeTab === "settings" ? " active" : ""}`} href="/settings">
            <Cog6ToothIcon className="sidebar-nav-icon" />
            <span className="sidebar-nav-title">设置</span>
          </Link>
        </div>
        <div
          aria-hidden="true"
          className="app-sidebar-resizer"
          onPointerDown={(event) => {
            event.preventDefault();
            dragStateRef.current = { startX: event.clientX, startWidth: sidebarWidth };
            document.body.classList.add("sidebar-resizing");
          }}
        />
      </aside>

      <section className="app-main">
        <header className="page-head">
          <div className="page-head-copy">
            <h2>{pageTitle ?? TAB_TITLES[activeTab]}</h2>
            <p>{pageDescription ?? TAB_DESCRIPTIONS[activeTab]}</p>
            {!hidePageMeta && workspaceMeta.length > 0 ? (
              <div className="workspace-context-meta">
                {workspaceMeta.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            ) : null}
          </div>
          {showPageActions ? (
            <div className="page-head-actions">
              {projectSelect}
              {onRefreshProjects ? (
                <button className="control-btn" onClick={onRefreshProjects}>
                  刷新项目
                </button>
              ) : null}
            </div>
          ) : null}
        </header>

        {error ? (
          <div className="notice-error" role="alert">
            <strong>API Error</strong>
            <pre>{error}</pre>
          </div>
        ) : null}

        <section className="content-card">{children}</section>

        {!hideFooterNote ? (
          <footer className="page-footnote">
            {resolvedCurrentProject?.description
              ? resolvedCurrentProject.description
              : "当前页面使用同一项目上下文、同一 API 底座和同一交互语言。"}
          </footer>
        ) : null}
      </section>
    </main>
  );
}
