"use client";

import { ToolRunForm } from "./tool_run_form";
import type { DatabaseEntry, Execution, ToolDescriptor, ToolSummary } from "./detection_workspace_types";

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

type ToolsSectionProps = {
  filteredTools: ToolSummary[];
  selectedToolId: string;
  selectedDescriptor: ToolDescriptor | null;
  toolSearch: string;
  onToolSearchChange: (value: string) => void;
  onSelectTool: (toolId: string) => Promise<void>;
  toolRunBusy: boolean;
  onRunTool: (params: Record<string, unknown>) => Promise<void>;
  toolRunMsg: string;
};

export function ToolsSection({
  filteredTools,
  selectedToolId,
  selectedDescriptor,
  toolSearch,
  onToolSearchChange,
  onSelectTool,
  toolRunBusy,
  onRunTool,
  toolRunMsg,
}: ToolsSectionProps) {
  return (
    <div className="tools-page-grid">
      <section className="tools-catalog-panel">
        <div className="section-header-row">
          <div>
            <h3>工具目录</h3>
            <p>按名称、类别或 ID 搜索</p>
          </div>
          <span className="badge">{filteredTools.length}</span>
        </div>
        <input
          type="text"
          className="control-input"
          placeholder="搜索工具"
          value={toolSearch}
          onChange={(event) => onToolSearchChange(event.target.value)}
          aria-label="搜索工具"
        />
        <div className="tools-catalog-list">
          {filteredTools.map((tool) => (
            <button
              key={tool.id}
              className={`tool-list-item${selectedToolId === tool.id ? " selected" : ""}`}
              onClick={() => void onSelectTool(tool.id)}
            >
              <strong>{tool.name}</strong>
              <span>{tool.description || tool.category}</span>
              <em>{tool.id}</em>
            </button>
          ))}
        </div>
      </section>

      <section className="tools-config-panel">
        {!selectedDescriptor ? (
          <div className="panel-placeholder">
            <div className="placeholder-mark">Tool</div>
            <p>请选择左侧工具以配置参数并执行</p>
          </div>
        ) : (
          <>
            <div className="section-header-row">
              <div>
                <h3>{safeText(selectedDescriptor.name, selectedToolId)}</h3>
                <p>{safeText(selectedDescriptor.description, "当前工具未提供描述")}</p>
              </div>
              <div className="meta-row">
                <span className="badge">{safeText(selectedDescriptor.id, selectedToolId)}</span>
                <span className="badge">v{safeText(selectedDescriptor.version, "unknown")}</span>
                <span className="badge">{safeText(selectedDescriptor.category, "unknown")}</span>
              </div>
            </div>
            <ToolRunForm descriptor={selectedDescriptor} toolId={selectedToolId} onRun={onRunTool} busy={toolRunBusy} />
            {toolRunMsg ? <p className="ok-text">{toolRunMsg}</p> : null}
          </>
        )}
      </section>
    </div>
  );
}

type HistorySectionProps = {
  historyRows: Execution[];
  historySearch: string;
  busyArchiveId: string;
  onHistorySearchChange: (value: string) => void;
  onRefresh: () => Promise<void>;
  onArchiveExecution: (executionId: string) => Promise<void>;
};

export function HistorySection({
  historyRows,
  historySearch,
  busyArchiveId,
  onHistorySearchChange,
  onRefresh,
  onArchiveExecution,
}: HistorySectionProps) {
  const query = historySearch.trim().toLowerCase();
  const visibleRows = historyRows.filter((row) => {
    if (!query) {
      return true;
    }
    const content = `${row.execution_id} ${row.tool_id} ${row.sample_name || row.sample_id}`.toLowerCase();
    return content.includes(query);
  });

  return (
    <div className="stack-layout">
      <div className="section-header-row">
        <div>
          <h3>执行历史</h3>
          <p>查看状态、样本、工具与归档动作</p>
        </div>
        <button className="control-btn" onClick={() => void onRefresh()}>
          刷新
        </button>
      </div>
      <input
        className="control-input"
        type="text"
        placeholder="搜索 execution_id / tool / sample"
        value={historySearch}
        onChange={(event) => onHistorySearchChange(event.target.value)}
        aria-label="搜索历史"
      />

      <div className="history-list-grid">
        {visibleRows.length === 0 ? <div className="empty-row">暂无执行记录</div> : null}
        {visibleRows.map((row) => (
          <article key={row.execution_id} className="history-item-card">
            <div className="row">
              <code>{row.execution_id}</code>
              <span className="badge">{row.status}</span>
            </div>
            <div className="muted">{row.tool_id}</div>
            <div className="muted">{row.sample_name || row.sample_id || "unknown_sample"}</div>
            <button
              className="control-btn"
              disabled={busyArchiveId === row.execution_id}
              onClick={() => void onArchiveExecution(row.execution_id)}
            >
              {busyArchiveId === row.execution_id ? "归档中..." : "归档"}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}

type DatabaseSectionProps = {
  databases: DatabaseEntry[];
  onRefresh: () => Promise<void>;
};

export function DatabaseSection({ databases, onRefresh }: DatabaseSectionProps) {
  return (
    <div className="stack-layout">
      <div className="section-header-row">
        <div>
          <h3>数据库状态</h3>
          <p>确认本地路径、分类和状态消息</p>
        </div>
        <button className="control-btn" onClick={() => void onRefresh()}>
          刷新
        </button>
      </div>

      {databases.length === 0 ? <div className="empty-row">暂无数据库定义或未选择项目</div> : null}

      <div className="database-grid">
        {databases.map((db) => (
          <article key={db.db_id} className="database-card">
            <div className="row">
              <strong>{db.name}</strong>
              <span className="badge">{db.status || "n/a"}</span>
            </div>
            <div className="muted">{db.db_id}</div>
            <div className="muted">{db.category}</div>
            <div className="muted">path: {db.resolved_path || "(empty)"}</div>
            {db.status_message ? <div className="muted">{db.status_message}</div> : null}
          </article>
        ))}
      </div>
    </div>
  );
}
