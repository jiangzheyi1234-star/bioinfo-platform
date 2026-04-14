"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import type { Project, TabId, Task } from "./detection_workspace_types";
import { apiBase, parseSSHStatus, readJsonOrThrow } from "./detection_workspace_utils";
import { WorkspaceShellSidebar } from "./workspace_shell_sidebar";

const LEFT_SIDEBAR_STORAGE_KEY = "h2ometa:left-sidebar-width";
const DEFAULT_LEFT_SIDEBAR_WIDTH = 272;
const MIN_LEFT_SIDEBAR_WIDTH = 200;
const MAX_LEFT_SIDEBAR_WIDTH = 350;
const AUTO_CONNECT_NOTICE_STORAGE_KEY = "h2ometa:auto-connect-notice-key";

export const NAV_ITEMS: Array<{ id: TabId; href: string; label: string; note: string; hotkey: string }> = [
  { id: "connect", href: "/connect", label: "连接", note: "SSH 与远端状态", hotkey: "Alt+6" },
  { id: "workspace", href: "/workspace", label: "工作台", note: "Project → Task → Workbench", hotkey: "Alt+7" },
  { id: "settings", href: "/settings", label: "系统设置", note: "全局配置与偏好", hotkey: "Alt+0" },
];

const TAB_TITLES: Record<TabId, string> = {
  connect: "远端连接",
  workspace: "工作台",
  settings: "系统设置",
};

const TAB_DESCRIPTIONS: Record<TabId, string> = {
  connect: "管理 SSH 连接、测试与远端会话状态。",
  workspace: "围绕当前 Task Workbench 完成 Workflow、Runs 与 Results 主链路。",
  settings: "维护系统配置和本地工作台偏好。",
};

const TAB_BREADCRUMB_LABELS: Record<TabId, string> = {
  connect: "连接",
  workspace: "Task Workbench",
  settings: "设置",
};

type DetectionWorkspaceShellProps = {
  activeTab: TabId;
  pageTitle?: string;
  pageDescription?: string;
  hidePageHeader?: boolean;
  hidePageMeta?: boolean;
  hideFooterNote?: boolean;
  hideErrorNotice?: boolean;
  currentProject?: Project;
  currentProjectId: string;
  projects: Project[];
  tasks?: Task[];
  selectedTaskId?: string;
  error?: string;
  isSshConnected?: boolean;
  isEditingConnection?: boolean;
  onOpenConnectionEditor?: () => void;
  sidebarContent?: ReactNode;
  projectSelect?: ReactNode;
  onRefreshProjects?: () => void;
  onSelectProject?: (projectId: string) => void;
  onSelectTask?: (taskId: string) => void;
  children?: ReactNode;
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
  hidePageHeader = false,
  hidePageMeta = false,
  hideFooterNote = false,
  hideErrorNotice = false,
  currentProject,
  currentProjectId,
  projects,
  tasks = [],
  selectedTaskId = "",
  error = "",
  isSshConnected = false,
  isEditingConnection = false,
  onOpenConnectionEditor,
  sidebarContent,
  projectSelect,
  onRefreshProjects,
  onSelectProject,
  onSelectTask,
  children,
}: DetectionWorkspaceShellProps) {
  const router = useRouter();
  const [sidebarWidth, setSidebarWidth] = useState<number>(DEFAULT_LEFT_SIDEBAR_WIDTH);
  const [connectionMenuOpen, setConnectionMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [navSshConnected, setNavSshConnected] = useState<boolean>(isSshConnected);
  const [startupNotice, setStartupNotice] = useState<{ key: string; message: string } | null>(null);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const hasUserResizedRef = useRef(false);
  const connectionMenuRef = useRef<HTMLDivElement | null>(null);
  const settingsMenuRef = useRef<HTMLDivElement | null>(null);

  const resolvedCurrentProject = useMemo(
    () => currentProject ?? projects.find((project) => project.project_id === currentProjectId),
    [currentProject, currentProjectId, projects]
  );
  const resolvedCurrentTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId]
  );
  const showPageActions = !!projectSelect || !!onRefreshProjects;
  const resolvedSshConnected = isEditingConnection ? false : isSshConnected || navSshConnected;
  const workspaceMeta = [
    resolvedCurrentProject?.name || "未选择项目",
    resolvedCurrentTask?.title ? `Task: ${resolvedCurrentTask.title}` : tasks.length > 0 ? `${tasks.length} Tasks` : "",
    currentProjectId || "",
  ].filter(Boolean);
  const breadcrumbs = useMemo(() => {
    const items = [{ label: "Workspace", tone: "muted" as const }];

    if (activeTab === "workspace" && resolvedCurrentProject?.name) {
      items.push({ label: resolvedCurrentProject.name, tone: "default" as const });
      if (resolvedCurrentTask?.title) {
        items.push({ label: resolvedCurrentTask.title, tone: "default" as const });
      }
    }

    items.push({
      label: TAB_BREADCRUMB_LABELS[activeTab],
      tone: "current" as const,
    });

    return items;
  }, [activeTab, resolvedCurrentProject?.name, resolvedCurrentTask?.title]);

  useEffect(() => {
    setSidebarWidth(readStoredSidebarWidth());
  }, []);

  useEffect(() => {
    if (isEditingConnection) {
      setNavSshConnected(false);
      return;
    }
    if (isSshConnected) {
      setNavSshConnected(true);
      return;
    }

    void (async () => {
      try {
        const resp = await fetch(`${apiBase()}/api/v1/ssh/status`);
        const data = await readJsonOrThrow(resp);
        const nextStatus = parseSSHStatus(data?.item);
        setNavSshConnected(nextStatus?.connected === true);
        if (nextStatus?.auto_connect_failed && nextStatus.auto_connect_notice_key) {
          const handledKey = window.sessionStorage.getItem(AUTO_CONNECT_NOTICE_STORAGE_KEY);
          if (handledKey !== nextStatus.auto_connect_notice_key) {
            setStartupNotice({
              key: nextStatus.auto_connect_notice_key,
              message: nextStatus.auto_connect_error || "SSH 自动连接失败",
            });
            window.sessionStorage.setItem(AUTO_CONNECT_NOTICE_STORAGE_KEY, nextStatus.auto_connect_notice_key);
          }
        }
      } catch {
        setNavSshConnected(false);
      }
    })();
  }, [activeTab, isEditingConnection, isSshConnected]);

  useEffect(() => {
    if (!startupNotice) {
      return;
    }
    const timer = window.setTimeout(() => {
      setStartupNotice((current) => (current?.key === startupNotice.key ? null : current));
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [startupNotice]);

  useEffect(() => {
    if (!hasUserResizedRef.current) {
      return;
    }
    window.localStorage.setItem(LEFT_SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    setConnectionMenuOpen(false);
    setSettingsMenuOpen(false);
  }, [activeTab, resolvedSshConnected, isEditingConnection]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!connectionMenuRef.current?.contains(event.target as Node)) {
        setConnectionMenuOpen(false);
      }
      if (!settingsMenuRef.current?.contains(event.target as Node)) {
        setSettingsMenuOpen(false);
      }
    };

    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

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
      <WorkspaceShellSidebar
        activeTab={activeTab}
        resolvedSshConnected={resolvedSshConnected}
        isEditingConnection={isEditingConnection}
        connectionMenuOpen={connectionMenuOpen}
        settingsMenuOpen={settingsMenuOpen}
        connectionMenuRef={connectionMenuRef}
        settingsMenuRef={settingsMenuRef}
        sidebarContent={sidebarContent}
        sidebarWidth={sidebarWidth}
        onToggleConnectionMenu={() => setConnectionMenuOpen((open) => !open)}
        onToggleSettingsMenu={() => setSettingsMenuOpen((open) => !open)}
        onOpenConnectionEditor={onOpenConnectionEditor}
        onOpenSettings={() => router.push("/settings")}
        onBeginResize={(clientX) => {
          dragStateRef.current = { startX: clientX, startWidth: sidebarWidth };
          document.body.classList.add("sidebar-resizing");
        }}
      />

      <section className="app-main">
        <header className="workspace-topbar">
          <div className="workspace-topbar-copy">
            <nav className="workspace-breadcrumbs" aria-label="页面路径">
              {breadcrumbs.map((item, index) => (
                <span key={`${item.label}-${index}`} className={`workspace-breadcrumb workspace-breadcrumb--${item.tone}`}>
                  <span>{item.label}</span>
                  {index < breadcrumbs.length - 1 ? <span className="workspace-breadcrumb-separator">/</span> : null}
                </span>
              ))}
            </nav>
            {!hidePageHeader ? (
              <div className="workspace-topbar-detail">
                <strong>{pageTitle ?? TAB_TITLES[activeTab]}</strong>
                <p>{pageDescription ?? TAB_DESCRIPTIONS[activeTab]}</p>
              </div>
            ) : null}
            {!hidePageMeta && workspaceMeta.length > 0 ? (
              <div className="workspace-context-meta">
                {workspaceMeta.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            ) : null}
          </div>
          {showPageActions ? (
            <div className="workspace-topbar-actions">
              {projectSelect}
              {onRefreshProjects ? (
                <button className="control-btn" onClick={onRefreshProjects}>
                  刷新项目
                </button>
              ) : null}
            </div>
          ) : null}
        </header>

        {!hideErrorNotice && error ? (
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
      {startupNotice ? (
        <div className="workspace-status-toast" role="status" aria-live="polite">
          <div className="workspace-status-toast-copy">
            <strong>SSH 自动连接失败</strong>
            <p>{startupNotice.message}</p>
          </div>
          <button type="button" className="workspace-status-toast-close" aria-label="关闭提示" onClick={() => setStartupNotice(null)}>
            ×
          </button>
        </div>
      ) : null}
    </main>
  );
}
