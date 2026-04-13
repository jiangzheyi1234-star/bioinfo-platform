"use client";

import { RectangleStackIcon } from "@heroicons/react/24/outline";

import type {
  ConfiguredDatabasePath,
  SummaryPair,
  WorkbenchHistoryRow,
  WorkbenchRemoteExecutionStatus,
  WorkbenchTaskGuidance,
} from "./workbench_panel_types";
import { asText } from "./workbench_panel_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";

type WorkbenchPageHeaderProps = {
  featureCount: number;
  historyCount: number;
  databaseCount: number;
  dockVisible: boolean;
  onRefreshConfig: () => void;
  onRefreshHistory: () => void;
  onToggleDock: () => void;
};

export function WorkbenchPageHeader(props: WorkbenchPageHeaderProps) {
  return (
    <>
      <WorkspaceSectionHeader
        title="高级工作流工作台"
        description="用更轻的目录、阅读流结果页和内嵌观测层组织分析功能与历史结果。"
        aside={
          <div className="workbench-header-actions">
            <button
              className={`btn workbench-dock-toggle-btn workbench-dock-toggle-icon-btn${props.dockVisible ? " is-active" : ""}`}
              onClick={props.onToggleDock}
              aria-label={props.dockVisible ? "收起远端面板" : "打开远端面板"}
              title={props.dockVisible ? "收起远端面板" : "打开远端面板"}
            >
              <RectangleStackIcon className="workbench-dock-toggle-icon" />
            </button>
            <button className="btn" onClick={props.onRefreshConfig}>
              刷新配置
            </button>
            <button className="btn" onClick={props.onRefreshHistory}>
              刷新历史
            </button>
          </div>
        }
        className="workbench-page-header"
      />
      <p className="muted workbench-page-meta">
        {props.featureCount} 个功能视图，{props.historyCount} 条历史结果，{props.databaseCount} 组数据库路径。
      </p>
      {!props.dockVisible ? (
        <div className="workbench-dock-entry-hint">
          <span className="badge">remote dock</span>
          <span>远端面板当前已收起。使用右上角“打开远端面板”即可查看日志尾部、远端状态和修复回显。</span>
        </div>
      ) : null}
    </>
  );
}

type WorkbenchTaskStatusCardProps = {
  selectedRow: WorkbenchHistoryRow | null;
  remoteStatus: WorkbenchRemoteExecutionStatus | null;
  guidance: WorkbenchTaskGuidance;
  dockVisible: boolean;
  onToggleDock: () => void;
  onRefreshRemoteStatus: () => void;
  onLoadResult: () => void;
};

export function WorkbenchTaskStatusCard(props: WorkbenchTaskStatusCardProps) {
  return (
    <section className="workbench-panel-card workbench-task-status-card">
      <WorkspaceSectionHeader
        title="远端任务推进"
        description="只面向远端任务的观察与修复，不提供通用本地终端。"
        titleAs="h5"
        aside={
          <div className="workbench-header-actions">
            <button className="btn" onClick={props.onRefreshRemoteStatus}>
              刷新远端状态
            </button>
            <button className="btn" onClick={props.onLoadResult}>
              加载结果
            </button>
            <button className="btn" onClick={props.onToggleDock}>
              {props.dockVisible ? "收起远端面板" : "打开远端面板"}
            </button>
          </div>
        }
      />

      <div className="workbench-task-status-grid">
        <div className="workbench-task-runtime-summary">
          <div className="workbench-task-state-row">
            <span className={`badge workbench-guidance-badge tone-${props.guidance.state}`}>{props.guidance.label}</span>
            {props.selectedRow ? <span className="badge">{props.selectedRow.status || "unknown"}</span> : null}
            {props.remoteStatus?.remote_status ? <span className="badge">{props.remoteStatus.remote_status}</span> : null}
          </div>
          <p className="workbench-task-summary-text">{props.guidance.summary}</p>
          <div className="workbench-task-action-hint">
            推荐动作：<strong>{props.guidance.recommended_action}</strong>
          </div>
        </div>

        <div className="workbench-task-runtime-meta">
          <div className="kv-list">
            <div className="kv-row">
              <span className="kv-key">Execution</span>
              <span className="kv-value">{props.selectedRow?.execution_id || props.remoteStatus?.execution_id || "-"}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Tool</span>
              <span className="kv-value">{props.selectedRow?.tool_id || props.remoteStatus?.tool_id || "-"}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">SSH</span>
              <span className="kv-value">{props.remoteStatus ? (props.remoteStatus.ssh_connected ? "connected" : "disconnected") : "-"}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Screen</span>
              <span className="kv-value">
                {props.remoteStatus?.screen_running === null ? "-" : props.remoteStatus?.screen_running ? "running" : "stopped"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="workbench-guidance-list">
        {props.guidance.details.length === 0 ? (
          <WorkspaceEmptyState label="暂无额外诊断细节" compact />
        ) : (
          props.guidance.details.map((detail, index) => (
            <div key={`${detail}_${index}`} className="workbench-guidance-item">
              {detail}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

type WorkbenchExecutionTraceProps = {
  workbenchExecutionId: string;
  setWorkbenchExecutionId: (value: string) => void;
  onLoadResult: () => void;
  onLoadRemoteStatus: () => void;
  workbenchToolId: string;
  setWorkbenchToolId: (value: string) => void;
  workbenchParamsJson: string;
  setWorkbenchParamsJson: (value: string) => void;
  workbenchMsg: string;
  remoteSummary: SummaryPair[];
  resultSummary: SummaryPair[];
  workbenchRemoteStatus: WorkbenchRemoteExecutionStatus | null;
  workbenchResult: Record<string, unknown> | null;
};

export function WorkbenchExecutionTrace(props: WorkbenchExecutionTraceProps) {
  return (
    <section className="workbench-panel-card workbench-support-card">
      <WorkspaceSectionHeader title="执行追踪与回归" aside={<span className="badge">execution</span>} titleAs="h5" />
      <div className="workbench-trace-toolbar">
        <input
          className="input-control workbench-execution-input"
          value={props.workbenchExecutionId}
          onChange={(event) => props.setWorkbenchExecutionId(event.target.value)}
          placeholder="execution_id"
        />
        <button className="btn" onClick={props.onLoadResult}>
          加载结果
        </button>
        <button className="btn" onClick={props.onLoadRemoteStatus}>
          远端状态
        </button>
      </div>

      <div className="workbench-trace-grid">
        <div className="workbench-trace-form workspace-form-surface">
          <div className="field-block">
            <label className="field-label">Tool ID</label>
            <input className="input-control" value={props.workbenchToolId} onChange={(event) => props.setWorkbenchToolId(event.target.value)} />
          </div>
          <div className="field-block">
            <label className="field-label">Params JSON</label>
            <textarea
              className="input-control textarea-control"
              value={props.workbenchParamsJson}
              onChange={(event) => props.setWorkbenchParamsJson(event.target.value)}
            />
          </div>
          <button className="btn" disabled>
            提交高级工作流已停用
          </button>
          <p className="muted">新的 workflow/run 提交统一迁移到 /workspace；这里仅保留 execution 回看与远端诊断。</p>
          {props.workbenchMsg ? <p className="ok-text">{props.workbenchMsg}</p> : null}
        </div>

        <div className="workbench-trace-summary workspace-form-surface">
          <div className="split-title">远端状态摘要</div>
          <div className="kv-list">
            {props.remoteSummary.length === 0 ? <WorkspaceEmptyState label="暂无远端状态" compact /> : null}
            {props.remoteSummary.map((entry) => (
              <div key={`remote_${entry.key}`} className="kv-row">
                <span className="kv-key">{entry.key}</span>
                <span className="kv-value">{entry.value}</span>
              </div>
            ))}
          </div>

          <div className="split-title workbench-trace-section-gap">结果摘要</div>
          <div className="kv-list">
            {props.resultSummary.length === 0 ? <WorkspaceEmptyState label="暂无结果数据" compact /> : null}
            {props.resultSummary.map((entry) => (
              <div key={`result_${entry.key}`} className="kv-row">
                <span className="kv-key">{entry.key}</span>
                <span className="kv-value">{entry.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {props.workbenchRemoteStatus ? <pre className="json-preview">{JSON.stringify(props.workbenchRemoteStatus, null, 2)}</pre> : null}
      {props.workbenchResult ? <pre className="json-preview">{JSON.stringify(props.workbenchResult, null, 2)}</pre> : null}
    </section>
  );
}

type WorkbenchConfiguredDatabasesProps = {
  configuredDatabases: ConfiguredDatabasePath[];
};

export function WorkbenchConfiguredDatabases(props: WorkbenchConfiguredDatabasesProps) {
  return (
    <section className="workbench-panel-card workbench-support-card">
      <WorkspaceSectionHeader title="数据库路径" aside={<span className="badge">{props.configuredDatabases.length}</span>} titleAs="h5" />
      {props.configuredDatabases.length === 0 ? (
        <WorkspaceEmptyState
          mark="DB"
          label="暂无数据库路径配置"
          hint="数据库路径加载后会继续保留在这里，便于和当前结果面板对照。"
          compact
        />
      ) : null}
      <div className="database-inline-list">
        {props.configuredDatabases.slice(0, 12).map((entry) => (
          <div key={entry.key} className="database-inline-row">
            <div>
              <strong>{asText(entry.label || entry.key, "unknown_db_key")}</strong>
              <div className="muted">{asText(entry.key, "unknown")}</div>
            </div>
            <div className="muted">{asText(entry.path, "(empty path)")}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
