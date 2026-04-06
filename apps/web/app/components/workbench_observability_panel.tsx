"use client";

import { useEffect, useMemo, useState } from "react";

import type { AppLogPayload, RuntimeEvent } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toAppLogPayload, toRuntimeEvent } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

type WorkbenchObservabilityPanelProps = {
  onError: (message: string) => void;
};

type ObservabilityTab = "events" | "logs";

export function WorkbenchObservabilityPanel({ onError }: WorkbenchObservabilityPanelProps) {
  const [activeTab, setActiveTab] = useState<ObservabilityTab>("events");
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [latestSeq, setLatestSeq] = useState<number>(0);
  const [logs, setLogs] = useState<AppLogPayload>({ path: "", lines: [] });
  const [tailLines, setTailLines] = useState<number>(200);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [failedOnly, setFailedOnly] = useState<boolean>(false);

  const visibleEvents = useMemo(() => {
    if (!failedOnly) {
      return events;
    }
    return events.filter((item) => item.event_type.includes("failed"));
  }, [events, failedOnly]);

  const refreshEvents = async (incremental = false) => {
    try {
      const afterSeq = incremental ? latestSeq : 0;
      const resp = await fetch(`${apiBase()}/api/v1/events/executions?after_seq=${afterSeq}&limit=200`);
      const data = await readJsonOrThrow(resp);
      const items = Array.isArray(data?.item?.items)
        ? data.item.items.map(toRuntimeEvent).filter((item: RuntimeEvent | null): item is RuntimeEvent => !!item)
        : [];
      const nextLatestSeq = Number(data?.item?.latest_seq || 0);
      setLatestSeq(nextLatestSeq);
      setEvents((prev) => {
        if (!incremental || afterSeq === 0) {
          return items;
        }
        return [...prev, ...items].slice(-200);
      });
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  const refreshLogs = async (nextTailLines = tailLines) => {
    try {
      const resp = await fetch(`${apiBase()}/api/v1/logs/app?tail_lines=${nextTailLines}`);
      const data = await readJsonOrThrow(resp);
      setLogs(toAppLogPayload(data?.item));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    void refreshEvents(false);
    void refreshLogs(tailLines);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!autoRefresh) {
      return;
    }
    const handle = window.setInterval(() => {
      void refreshEvents(true);
      if (activeTab === "logs") {
        void refreshLogs(tailLines);
      }
    }, 5000);
    return () => window.clearInterval(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, autoRefresh, latestSeq, tailLines]);

  return (
    <section className="workbench-panel-card workbench-support-card observability-panel">
      <WorkspaceSectionHeader
        title="运行观测"
        description="集中查看执行事件与应用日志，不额外新增一级页面。"
        aside={
          <div className="observability-toolbar">
            <label className="checkbox-row">
              <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
              <span>自动刷新</span>
            </label>
            <button className="btn" onClick={() => void refreshEvents(false)}>
              刷新事件
            </button>
            <button className="btn" onClick={() => void refreshLogs(tailLines)}>
              刷新日志
            </button>
          </div>
        }
        titleAs="h5"
      />

      <div className="observability-tabs">
        <button type="button" className={`observability-tab${activeTab === "events" ? " active" : ""}`} onClick={() => setActiveTab("events")}>
          Events
        </button>
        <button type="button" className={`observability-tab${activeTab === "logs" ? " active" : ""}`} onClick={() => setActiveTab("logs")}>
          App Logs
        </button>
      </div>

      {activeTab === "events" ? (
        <div className="observability-stack">
          <div className="observability-inline-controls">
            <span className="badge">latest_seq {latestSeq}</span>
            <label className="checkbox-row">
              <input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} />
              <span>仅失败事件</span>
            </label>
          </div>
          <div className="observability-feed">
            {visibleEvents.length === 0 ? (
              <WorkspaceEmptyState
                mark="Evt"
                label="暂无执行事件"
                hint="工作台任务开始、完成或失败后，事件会在这里持续累积。"
                compact
              />
            ) : null}
            {visibleEvents.map((event) => (
              <article key={`${event.seq}_${event.event_type}`} className="observability-item">
                <div className="row">
                  <strong>{event.event_type}</strong>
                  <span className="badge">#{event.seq}</span>
                </div>
                <div className="muted">
                  {event.timestamp ? new Date(event.timestamp * 1000).toLocaleString("zh-CN") : "unknown time"}
                </div>
                <div className="muted">
                  execution_id: {safeText(event.payload.execution_id, "-")}
                  {event.payload.error ? ` · error: ${safeText(event.payload.error)}` : ""}
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {activeTab === "logs" ? (
        <div className="observability-stack">
          <div className="observability-inline-controls">
            <label className="field-label" htmlFor="tail-lines">
              Tail Lines
            </label>
            <select
              id="tail-lines"
              className="control-input observability-select"
              value={tailLines}
              onChange={(event) => {
                const nextValue = Number(event.target.value || 200);
                setTailLines(nextValue);
                void refreshLogs(nextValue);
              }}
            >
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
            </select>
            <span className="muted observability-log-path">{logs.path || "未找到日志文件"}</span>
          </div>
          {logs.lines.length === 0 ? (
            <WorkspaceEmptyState
              mark="Log"
              label="暂无日志内容"
              hint="如果日志文件尚未生成或当前为空，这里会保持空态。"
              compact
            />
          ) : (
            <pre className="observability-log-view">{logs.lines.join("\n")}</pre>
          )}
        </div>
      ) : null}
    </section>
  );
}
