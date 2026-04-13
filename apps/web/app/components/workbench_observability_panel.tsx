"use client";

import { useEffect, useMemo, useState } from "react";

import type { AppLogPayload, RuntimeEvent } from "./detection_workspace_types";
import type { WorkbenchRemoteExecutionStatus } from "./workbench_panel_types";
import { apiBase, readJsonOrThrow, safeText, toAppLogPayload, toRuntimeEvent } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

type WorkbenchObservabilityPanelProps = {
  onError: (message: string) => void;
  executionId: string;
  remoteStatus: WorkbenchRemoteExecutionStatus | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onRefreshRemoteStatus: () => void;
};

type ObservabilityTab = "remote" | "events" | "logs";

export function WorkbenchObservabilityPanel({
  onError,
  executionId,
  remoteStatus,
  collapsed,
  onToggleCollapsed,
  onRefreshRemoteStatus,
}: WorkbenchObservabilityPanelProps) {
  const [activeTab, setActiveTab] = useState<ObservabilityTab>("remote");
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
      if (executionId) {
        onRefreshRemoteStatus();
      }
      if (activeTab === "logs") {
        void refreshLogs(tailLines);
      }
    }, 5000);
    return () => window.clearInterval(handle);
  }, [activeTab, autoRefresh, executionId, latestSeq, onRefreshRemoteStatus, tailLines]);

  return (
    <section className={`workbench-panel-card workbench-support-card observability-panel remote-dock-panel${collapsed ? " is-collapsed" : ""}`}>
      <WorkspaceSectionHeader
        title="远端面板"
        description="集中观察远端任务状态、日志尾部与运行事件，只服务远端任务推进。"
        aside={
          <div className="observability-toolbar">
            <button className="btn" onClick={onToggleCollapsed}>
              {collapsed ? "展开面板" : "收起面板"}
            </button>
            <label className="checkbox-row">
              <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
              <span>自动刷新</span>
            </label>
            <button className="btn" onClick={onRefreshRemoteStatus}>
              刷新远端
            </button>
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

      <div className="observability-inline-controls">
        <span className="badge">execution {executionId || "-"}</span>
        {remoteStatus?.remote_status ? <span className="badge">remote {remoteStatus.remote_status}</span> : null}
        {remoteStatus ? <span className="badge">ssh {remoteStatus.ssh_connected ? "connected" : "disconnected"}</span> : null}
      </div>

      {!collapsed ? (
        <>
          <div className="observability-tabs">
            <button type="button" className={`observability-tab${activeTab === "remote" ? " active" : ""}`} onClick={() => setActiveTab("remote")}>
              Remote
            </button>
            <button type="button" className={`observability-tab${activeTab === "events" ? " active" : ""}`} onClick={() => setActiveTab("events")}>
              Events
            </button>
            <button type="button" className={`observability-tab${activeTab === "logs" ? " active" : ""}`} onClick={() => setActiveTab("logs")}>
              App Logs
            </button>
          </div>

          {activeTab === "remote" ? (
            <div className="observability-stack">
              {!remoteStatus ? (
                <WorkspaceEmptyState
                  mark="SSH"
                  label="暂无远端状态"
                  hint="先选择一条执行记录，或点击刷新远端状态以拉取最近的 screen / heartbeat / log tail 信息。"
                  compact
                />
              ) : (
                <>
                  <div className="workbench-remote-grid">
                    <div className="kv-list">
                      <div className="kv-row">
                        <span className="kv-key">local_status</span>
                        <span className="kv-value">{remoteStatus.local_status || "-"}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">remote_status</span>
                        <span className="kv-value">{remoteStatus.remote_status || "-"}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">screen_running</span>
                        <span className="kv-value">
                          {remoteStatus.screen_running === null ? "-" : remoteStatus.screen_running ? "running" : "stopped"}
                        </span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">heartbeat_age_sec</span>
                        <span className="kv-value">{remoteStatus.heartbeat_age_sec === null ? "-" : remoteStatus.heartbeat_age_sec}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">exit_code</span>
                        <span className="kv-value">{remoteStatus.exit_code || "-"}</span>
                      </div>
                    </div>
                    <div className="kv-list">
                      <div className="kv-row">
                        <span className="kv-key">task_dir</span>
                        <span className="kv-value">{remoteStatus.task_dir || "-"}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">tool_id</span>
                        <span className="kv-value">{remoteStatus.tool_id || "-"}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">sample_id</span>
                        <span className="kv-value">{remoteStatus.sample_id || "-"}</span>
                      </div>
                      <div className="kv-row">
                        <span className="kv-key">message</span>
                        <span className="kv-value">{remoteStatus.response_message || "-"}</span>
                      </div>
                    </div>
                  </div>
                  {remoteStatus.log_tail ? (
                    <pre className="observability-log-view workbench-remote-tail">{remoteStatus.log_tail}</pre>
                  ) : (
                    <WorkspaceEmptyState
                      mark="Tail"
                      label="暂无远端日志尾部"
                      hint="如果任务刚开始或尚未产生 task.log，这里会保持空态。"
                      compact
                    />
                  )}
                </>
              )}
            </div>
          ) : null}

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
                  <WorkspaceEmptyState mark="Evt" label="暂无执行事件" hint="工作台任务开始、完成或失败后，事件会在这里持续累积。" compact />
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
                <WorkspaceEmptyState mark="Log" label="暂无日志内容" hint="如果日志文件尚未生成或当前为空，这里会保持空态。" compact />
              ) : (
                <pre className="observability-log-view">{logs.lines.join("\n")}</pre>
              )}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
