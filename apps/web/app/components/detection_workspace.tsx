"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type {
  DatabaseEntry,
  Execution,
  Project,
  TabId,
  ToolDescriptor,
  ToolSummary,
} from "./detection_workspace_types";
import { DatabaseSection, HistorySection, ToolsSection } from "./detection_workspace_sections";
import { WorkbenchPanel } from "./workbench_panel";

const NAV_ITEMS: Array<{ id: TabId; href: string; label: string; note: string; hotkey: string }> = [
  { id: "tools", href: "/tools", label: "执行中心", note: "工具选择与参数运行", hotkey: "Alt+1" },
  { id: "history", href: "/history", label: "历史归档", note: "记录、检索、归档", hotkey: "Alt+2" },
  { id: "integrated", href: "/integrated", label: "结果工作台", note: "综合结果与状态", hotkey: "Alt+3" },
  { id: "database", href: "/database", label: "数据与配置", note: "数据库与运行资源", hotkey: "Alt+4" },
];

const TAB_TITLES: Record<TabId, string> = {
  tools: "执行中心",
  history: "历史归档",
  integrated: "结果工作台",
  database: "数据与配置",
};

const TAB_DESCRIPTIONS: Record<TabId, string> = {
  tools: "按工具配置参数并提交任务，保持与旧流程一致的执行语义。",
  history: "追踪执行记录与归档状态，快速过滤并管理历史任务。",
  integrated: "聚合工作流结果、摘要、产物与远端状态，作为主操作台。",
  database: "查看数据库路径和可用状态，确认运行依赖是否就绪。",
};

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
}

async function readJsonOrThrow(resp: Response): Promise<unknown> {
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof (payload as { detail?: unknown })?.detail === "string" ? (payload as { detail: string }).detail : "";
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return payload;
}

function safeText(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return fallback;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function toProject(value: unknown): Project | null {
  if (!isRecord(value)) {
    return null;
  }
  const projectId = safeText(value.project_id);
  if (!projectId) {
    return null;
  }
  return {
    project_id: projectId,
    name: safeText(value.name, "unnamed"),
    status: safeText(value.status, "unknown"),
    description: safeText(value.description),
    last_opened_at: Number(value.last_opened_at || 0),
  };
}

function toExecution(value: unknown): Execution | null {
  if (!isRecord(value)) {
    return null;
  }
  const executionId = safeText(value.execution_id);
  if (!executionId) {
    return null;
  }
  return {
    execution_id: executionId,
    tool_id: safeText(value.tool_id, "unknown_tool"),
    sample_id: safeText(value.sample_id),
    status: safeText(value.status, "unknown"),
    created_at: Number(value.created_at || 0),
    sample_name: safeText(value.sample_name) || undefined,
    parameters: safeText(value.parameters) || undefined,
    error: safeText(value.error) || undefined,
  };
}

function toDatabaseEntry(value: unknown): DatabaseEntry | null {
  if (!isRecord(value)) {
    return null;
  }
  const dbId = safeText(value.db_id);
  if (!dbId) {
    return null;
  }
  return {
    db_id: dbId,
    name: safeText(value.name, "unnamed db"),
    category: safeText(value.category, "unknown"),
    resolved_path: safeText(value.resolved_path),
    configured_override: safeText(value.configured_override),
    installable: Boolean(value.installable),
    status: safeText(value.status) || undefined,
    status_message: safeText(value.status_message) || undefined,
  };
}

function toToolSummary(value: unknown): ToolSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = safeText(value.id || value.tool_id);
  if (!id) {
    return null;
  }
  return {
    id,
    name: safeText(value.name, id),
    category: safeText(value.category, "unknown"),
    description: safeText(value.description),
  };
}

export function DetectionWorkspace({ activeTab }: { activeTab: TabId }) {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string>("");
  const [historyRows, setHistoryRows] = useState<Execution[]>([]);
  const [databases, setDatabases] = useState<DatabaseEntry[]>([]);
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [selectedToolId, setSelectedToolId] = useState<string>("");
  const [selectedDescriptor, setSelectedDescriptor] = useState<ToolDescriptor | null>(null);
  const [toolSearch, setToolSearch] = useState<string>("");
  const [historySearch, setHistorySearch] = useState<string>("");
  const [toolRunMsg, setToolRunMsg] = useState<string>("");
  const [toolRunBusy, setToolRunBusy] = useState<boolean>(false);
  const [busyArchiveId, setBusyArchiveId] = useState<string>("");
  const [error, setError] = useState<string>("");

  const currentProject = useMemo(
    () => projects.find((project) => project.project_id === currentProjectId),
    [projects, currentProjectId]
  );

  const filteredTools = useMemo(() => {
    const query = toolSearch.trim().toLowerCase();
    if (!query) {
      return tools;
    }
    return tools.filter((tool) => {
      const content = `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase();
      return content.includes(query);
    });
  }, [toolSearch, tools]);

  const refreshProjects = async () => {
    const projectResp = await fetch(`${apiBase()}/api/v1/projects`);
    const projectData = (await readJsonOrThrow(projectResp)) as { items?: unknown[] };
    const projectItems: Project[] = Array.isArray(projectData.items)
      ? projectData.items.map(toProject).filter((item: Project | null): item is Project => !!item)
      : [];
    setProjects(projectItems);

    const currentResp = await fetch(`${apiBase()}/api/v1/projects/current`);
    const currentData = (await readJsonOrThrow(currentResp)) as { item?: Record<string, unknown> };
    const pid = safeText(currentData?.item?.project_id) || projectItems[0]?.project_id || "";
    if (pid) {
      await openProject(pid);
    } else {
      setCurrentProjectId("");
    }
  };

  const openProject = async (projectId: string) => {
    const normalizedProjectId = safeText(projectId);
    if (!normalizedProjectId) {
      setCurrentProjectId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/open`, {
      method: "POST",
    });
    await readJsonOrThrow(resp);
    setCurrentProjectId(normalizedProjectId);
  };

  const refreshHistory = async (projectId: string) => {
    if (!projectId) {
      setHistoryRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/history?limit=50`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: Execution[] = Array.isArray(data.items)
      ? data.items.map(toExecution).filter((item: Execution | null): item is Execution => !!item)
      : [];
    setHistoryRows(items);
  };

  const refreshDatabases = async (projectId: string) => {
    if (!projectId) {
      setDatabases([]);
      return;
    }
    const resp = await fetch(
      `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/databases?include_status=true`
    );
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: DatabaseEntry[] = Array.isArray(data.items)
      ? data.items
          .map(toDatabaseEntry)
          .filter((item: DatabaseEntry | null): item is DatabaseEntry => !!item)
      : [];
    setDatabases(items);
  };

  const refreshTools = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/tools`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items: ToolSummary[] = Array.isArray(data.items)
      ? data.items.map(toToolSummary).filter((item: ToolSummary | null): item is ToolSummary => !!item)
      : [];
    setTools(items);
    if (items.length > 0 && !selectedToolId) {
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
    const data = (await readJsonOrThrow(resp)) as { item?: unknown };
    const item = data?.item;
    if (isRecord(item)) {
      setSelectedDescriptor(item as ToolDescriptor);
    } else {
      setSelectedDescriptor(null);
    }
  };

  const runSelectedTool = async (params: Record<string, unknown>) => {
    if (!currentProjectId) {
      setError("No active project selected.");
      return;
    }
    if (!selectedToolId) {
      setError("请选择工具。");
      return;
    }
    setError("");
    setToolRunMsg("");
    setToolRunBusy(true);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/workbench/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          tool_id: selectedToolId,
          params,
        }),
      });
      const data = (await readJsonOrThrow(resp)) as { item?: Record<string, unknown> };
      const executionId = safeText(data?.item?.execution_id);
      setToolRunMsg(executionId ? `已提交任务: ${executionId}` : "已提交任务");
      await refreshHistory(currentProjectId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setToolRunBusy(false);
    }
  };

  const archiveExecution = async (executionId: string) => {
    if (!currentProjectId) {
      return;
    }
    setBusyArchiveId(executionId);
    setError("");
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/executions/${encodeURIComponent(
          executionId
        )}/archive`,
        { method: "POST" }
      );
      await readJsonOrThrow(resp);
      await refreshHistory(currentProjectId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusyArchiveId("");
    }
  };

  useEffect(() => {
    const run = async () => {
      try {
        await refreshProjects();
        await refreshTools();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    };
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const run = async () => {
      if (!currentProjectId) {
        setHistoryRows([]);
        setDatabases([]);
        return;
      }
      try {
        await refreshHistory(currentProjectId);
        await refreshDatabases(currentProjectId);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      }
    };
    void run();
  }, [currentProjectId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTypingTarget = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
      if (isTypingTarget) {
        return;
      }

      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }

      switch (event.key) {
        case "1":
          event.preventDefault();
          router.push("/tools");
          return;
        case "2":
          event.preventDefault();
          router.push("/history");
          return;
        case "3":
          event.preventDefault();
          router.push("/integrated");
          return;
        case "4":
          event.preventDefault();
          router.push("/database");
          return;
        default:
          return;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [router]);

  return (
    <main className="app-shell">
      <aside className="app-sidebar" aria-label="主导航">
        <div className="sidebar-brand">
          <h1>H2OMeta</h1>
          <p>Desktop Workbench</p>
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
          <p>快捷键：Alt + 1/2/3/4</p>
          <p>后端：{apiBase()}</p>
        </div>
      </aside>

      <section className="app-main">
        <header className="page-head">
          <div>
            <h2>{TAB_TITLES[activeTab]}</h2>
            <p>{TAB_DESCRIPTIONS[activeTab]}</p>
          </div>
          <div className="page-head-actions">
            <select
              className="control-select"
              value={currentProjectId}
              onChange={(event) => void openProject(event.target.value)}
              aria-label="选择项目"
            >
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.name} ({project.project_id})
                </option>
              ))}
            </select>
            <button className="control-btn" onClick={() => void refreshProjects()}>
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

        <section className="overview-grid" aria-label="概览">
          <article className="overview-card">
            <span>当前项目</span>
            <strong>{currentProject ? currentProject.name : "none"}</strong>
            <em>{currentProject?.project_id || "未选择"}</em>
          </article>
          <article className="overview-card">
            <span>可用工具</span>
            <strong>{tools.length}</strong>
            <em>已按类别聚合</em>
          </article>
          <article className="overview-card">
            <span>历史记录</span>
            <strong>{historyRows.length}</strong>
            <em>最近 50 条</em>
          </article>
          <article className="overview-card">
            <span>数据库项</span>
            <strong>{databases.length}</strong>
            <em>含状态采集</em>
          </article>
        </section>

        <section className="content-card">
          {activeTab === "tools" ? (
            <ToolsSection
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
                await refreshHistory(currentProjectId);
              }}
              onArchiveExecution={archiveExecution}
            />
          ) : null}

          {activeTab === "integrated" ? (
            <WorkbenchPanel
              currentProjectId={currentProjectId}
              onError={setError}
              onAfterRun={async () => {
                await refreshHistory(currentProjectId);
              }}
            />
          ) : null}

          {activeTab === "database" ? (
            <DatabaseSection
              databases={databases}
              onRefresh={async () => {
                await refreshDatabases(currentProjectId);
              }}
            />
          ) : null}
        </section>

        <footer className="page-footnote">
          当前项目状态：{currentProject?.status || "none"}
          {currentProject?.description ? ` · ${currentProject.description}` : ""}
        </footer>
      </section>
    </main>
  );
}
