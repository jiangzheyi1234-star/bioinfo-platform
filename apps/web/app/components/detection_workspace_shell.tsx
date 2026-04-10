"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ArchiveBoxIcon, Cog6ToothIcon, EllipsisHorizontalIcon, LinkIcon, RectangleStackIcon } from "@heroicons/react/24/outline";

import type { Project, TabId, Task } from "./detection_workspace_types";
import { apiBase, parseSSHStatus, readJsonOrThrow } from "./detection_workspace_utils";

const LEFT_SIDEBAR_STORAGE_KEY = "h2ometa:left-sidebar-width";
const DEFAULT_LEFT_SIDEBAR_WIDTH = 272;
const MIN_LEFT_SIDEBAR_WIDTH = 200;
const MAX_LEFT_SIDEBAR_WIDTH = 350;
const AUTO_CONNECT_NOTICE_STORAGE_KEY = "h2ometa:auto-connect-notice-key";

export const NAV_ITEMS: Array<{ id: TabId; href: string; label: string; note: string; hotkey: string }> = [
  { id: "connect", href: "/connect", label: "连接", note: "SSH 与远端状态", hotkey: "Alt+6" },
  { id: "toolflows", href: "/toolflows", label: "工具和流程", note: "工具目录与流程视图", hotkey: "Alt+7" },
  { id: "settings", href: "/settings", label: "系统设置", note: "全局配置与偏好", hotkey: "Alt+7" },
];

const TAB_TITLES: Record<TabId, string> = {
  projects: "项目工作台",
  samples: "样本管理",
  runs: "执行中心",
  history: "历史归档",
  databases: "数据库状态",
  connect: "远端连接",
  toolflows: "工具和流程",
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
  toolflows: "集中查看生信工具目录与当前项目流程。",
  settings: "维护系统配置和本地工作台偏好。",
  workbench: "聚合视图、结果、产物与远程状态。",
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
  toolsCount?: number;
  historyCount?: number;
  databasesCount?: number;
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
  toolsCount,
  historyCount,
  databasesCount,
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
  const showPageActions = !!projectSelect || !!onRefreshProjects;
  const resolvedSshConnected = isEditingConnection ? false : isSshConnected || navSshConnected;
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
      <aside className="app-sidebar" aria-label="主导航">
        <nav className="sidebar-nav sidebar-nav--top">
          <div className="sidebar-nav-row" ref={connectionMenuRef}>
            <Link
              className={`sidebar-nav-link sidebar-nav-link--connect${activeTab === "connect" ? " active" : ""}${resolvedSshConnected ? " connected" : ""}`}
              href="/connect"
            >
              <LinkIcon className="sidebar-nav-icon" />
              <span className="sidebar-nav-title">连接</span>
            </Link>
            {resolvedSshConnected && !isEditingConnection && onOpenConnectionEditor ? (
              <div className="sidebar-nav-menu-wrap">
                <button
                  type="button"
                  className="sidebar-nav-menu-trigger"
                  aria-label="连接菜单"
                  aria-expanded={connectionMenuOpen}
                  onClick={() => setConnectionMenuOpen((open) => !open)}
                >
                  <EllipsisHorizontalIcon className="sidebar-nav-menu-icon" />
                </button>
                {connectionMenuOpen ? (
                  <div className="sidebar-nav-menu">
                    <button
                      type="button"
                      className="sidebar-nav-menu-item"
                      onClick={() => {
                        setConnectionMenuOpen(false);
                        onOpenConnectionEditor();
                      }}
                    >
                      修改连接
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
          <Link className={`sidebar-nav-link${activeTab === "toolflows" ? " active" : ""}`} href="/toolflows">
            <RectangleStackIcon className="sidebar-nav-icon" />
            <span className="sidebar-nav-title">工具和流程</span>
          </Link>
        </nav>
        {sidebarContent ? <div className="sidebar-content-slot">{sidebarContent}</div> : null}
        <div className="sidebar-footer sidebar-footer--nav">
          {resolvedSshConnected ? (
            <div className="sidebar-footer-menu-wrap" ref={settingsMenuRef}>
              <button
                type="button"
                className={`sidebar-nav-link${activeTab === "settings" ? " active" : ""}`}
                aria-expanded={settingsMenuOpen}
                onClick={() => setSettingsMenuOpen((open) => !open)}
              >
                <Cog6ToothIcon className="sidebar-nav-icon" />
                <span className="sidebar-nav-title">设置</span>
              </button>
              {settingsMenuOpen ? (
                <div className="sidebar-footer-menu">
                  <button
                    type="button"
                    className="sidebar-footer-menu-item"
                    onClick={() => {
                      setSettingsMenuOpen(false);
                      router.push("/settings");
                    }}
                  >
                    <ArchiveBoxIcon className="sidebar-footer-menu-icon" />
                    <span>查看归档项目</span>
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="sidebar-nav-link sidebar-nav-link--disabled" aria-disabled="true">
              <Cog6ToothIcon className="sidebar-nav-icon" />
              <span className="sidebar-nav-title">设置</span>
            </div>
          )}
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
        {!hidePageHeader ? (
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
        ) : null}

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
