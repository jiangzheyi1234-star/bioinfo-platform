"use client";

import type {
  ArtifactItem,
  ConfiguredDatabasePath,
  ProvenanceItem,
  ResultTab,
  SummaryItem,
  SummaryPair,
  TableModel,
  ViewSourceMode,
  WorkbenchFeature,
  WorkbenchHistoryRow,
  WorkbenchView,
} from "./workbench_panel_types";
import { asText, compactPreview, localPathToFileUrl } from "./workbench_panel_utils";

type SidebarProps = {
  features: WorkbenchFeature[];
  sourceMode: ViewSourceMode;
  selectedWorkflowFeatureId: string;
  analysisCollapsed: boolean;
  onToggleAnalysis: () => void;
  onSelectWorkflowFeature: (featureId: string) => void;
  visibleHistoryRows: WorkbenchHistoryRow[];
  historyCollapsed: boolean;
  onToggleHistory: () => void;
  onClearUnpinned: () => void;
  historyPinned: Record<string, boolean>;
  selectedHistoryExecutionId: string;
  onSelectHistoryResult: (row: WorkbenchHistoryRow) => void;
  onTogglePinHistoryResult: (executionId: string) => void;
  onCloseHistoryResult: (executionId: string) => void;
  deletingExecutionId: string;
  onDeleteWorkbenchExecution: (executionId: string) => void;
};

export function WorkbenchSidebar(props: SidebarProps) {
  return (
    <aside className="integrated-sidebar-react">
      <section className="integrated-sidebar-section-react">
        <button type="button" className="integrated-section-toggle-react" onClick={props.onToggleAnalysis}>
          <span>分析功能</span>
          <span className="badge">{props.features.length}</span>
        </button>
        {!props.analysisCollapsed ? (
          <div className="integrated-feature-list-react">
            {props.features.map((feature) => {
              const active = props.sourceMode === "workflow" && props.selectedWorkflowFeatureId === feature.id;
              return (
                <button
                  type="button"
                  key={feature.id}
                  className={`integrated-feature-item-react${active ? " active" : ""}`}
                  onClick={() => props.onSelectWorkflowFeature(feature.id)}
                >
                  <div className="integrated-feature-row-react">
                    <span className="integrated-feature-name-react">{feature.title}</span>
                    {feature.badge ? <span className="badge">{feature.badge}</span> : null}
                  </div>
                  <div className="integrated-feature-desc-react">{feature.description}</div>
                </button>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className="integrated-sidebar-section-react">
        <div className="row" style={{ marginBottom: 6 }}>
          <button type="button" className="integrated-section-toggle-react" onClick={props.onToggleHistory}>
            <span>历史结果</span>
            <span className="badge">{props.visibleHistoryRows.length}</span>
          </button>
          <button className="btn" onClick={props.onClearUnpinned}>
            清理未固定
          </button>
        </div>
        {!props.historyCollapsed ? (
          <div className="integrated-feature-list-react">
            {props.visibleHistoryRows.length === 0 ? <div className="muted">暂无历史结果</div> : null}
            {props.visibleHistoryRows.map((row) => {
              const pinned = Boolean(props.historyPinned[row.execution_id]);
              const active = props.sourceMode === "history" && props.selectedHistoryExecutionId === row.execution_id;
              return (
                <div
                  key={row.execution_id}
                  className={`integrated-feature-item-react integrated-feature-item-history${active ? " active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => props.onSelectHistoryResult(row)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      props.onSelectHistoryResult(row);
                    }
                  }}
                >
                  <div className="integrated-feature-row-react">
                    <span className="integrated-feature-name-react">{row.sample_name || row.sample_id || row.execution_id}</span>
                    <span className="badge">{row.status}</span>
                  </div>
                  <div className="integrated-feature-desc-react">
                    {row.tool_id} · {row.execution_id}
                  </div>
                  <div className="integrated-action-row-react">
                    <button
                      className="btn"
                      onClick={(event) => {
                        event.stopPropagation();
                        props.onTogglePinHistoryResult(row.execution_id);
                      }}
                    >
                      {pinned ? "取消固定" : "固定"}
                    </button>
                    <button
                      className="btn"
                      onClick={(event) => {
                        event.stopPropagation();
                        props.onCloseHistoryResult(row.execution_id);
                      }}
                    >
                      关闭
                    </button>
                    <button
                      className="btn"
                      disabled={props.deletingExecutionId === row.execution_id}
                      onClick={(event) => {
                        event.stopPropagation();
                        props.onDeleteWorkbenchExecution(row.execution_id);
                      }}
                    >
                      {props.deletingExecutionId === row.execution_id ? "归档中..." : "归档"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </section>
    </aside>
  );
}

type ContentProps = {
  sourceMode: ViewSourceMode;
  selectedFeature: WorkbenchFeature | null;
  selectedView: WorkbenchView | null;
  activeResultTab: ResultTab;
  onChangeResultTab: (tab: ResultTab) => void;
  onRun: () => void;
  summaryItems: SummaryItem[];
  summaryPairs: SummaryPair[];
  tableModel: TableModel;
  chartItems: unknown[];
  htmlPreviewArtifact?: ArtifactItem;
  artifactItems: ArtifactItem[];
  provenanceItems: ProvenanceItem[];
};

export function WorkbenchContent(props: ContentProps) {
  const htmlPreviewUrl = localPathToFileUrl(props.htmlPreviewArtifact?.local_path || "");

  if (!props.selectedView) {
    return (
      <section className="integrated-content-react">
        <div className="integrated-empty-react">
          <div className="placeholder-mark">Result</div>
          <div className="muted">请选择分析功能或历史结果以查看详情。</div>
        </div>
      </section>
    );
  }

  return (
    <section className="integrated-content-react">
      <header className="integrated-header-react">
        <div>
          <div className="muted">{props.sourceMode === "history" ? "Result Shell · history" : "Workflow Entry"}</div>
          <h4 style={{ marginTop: 6, marginBottom: 4 }}>
            {asText(props.selectedView.title) || props.selectedFeature?.title || props.selectedFeature?.id || "未命名功能"}
          </h4>
          <p className="muted" style={{ margin: 0 }}>
            {asText(props.selectedView.description) || props.selectedFeature?.description || "暂无描述"}
          </p>
        </div>
        <button className="btn" onClick={props.onRun}>
          {props.sourceMode === "history" ? "重新运行" : "启动分析"}
        </button>
      </header>

      <div className="integrated-summary-grid-react">
        {props.summaryItems.length > 0
          ? props.summaryItems.map((item) => (
              <div className="integrated-summary-item-react" key={`${item.label}_${item.tone}`}>
                <div className="muted">{item.label}</div>
                <strong>{item.value}</strong>
              </div>
            ))
          : null}
        {props.summaryItems.length === 0 && props.summaryPairs.length > 0
          ? props.summaryPairs.map((item) => (
              <div className="integrated-summary-item-react" key={item.key}>
                <div className="muted">{item.key}</div>
                <strong>{item.value}</strong>
              </div>
            ))
          : null}
        {props.summaryItems.length === 0 && props.summaryPairs.length === 0 ? <div className="muted">暂无 summary 信息</div> : null}
      </div>

      <div className="integrated-tabs-react" role="tablist" aria-label="结果视图切换">
        <button
          type="button"
          className={`integrated-tab-btn-react${props.activeResultTab === "table" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("table")}
        >
          数据表格
        </button>
        <button
          type="button"
          className={`integrated-tab-btn-react${props.activeResultTab === "chart" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("chart")}
        >
          图表
        </button>
        <button
          type="button"
          className={`integrated-tab-btn-react${props.activeResultTab === "artifacts" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("artifacts")}
        >
          产物文件
        </button>
        <button
          type="button"
          className={`integrated-tab-btn-react${props.activeResultTab === "provenance" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("provenance")}
        >
          溯源信息
        </button>
      </div>

      {props.activeResultTab === "table" ? (
        <section className="integrated-panel-react">
          <div className="row">
            <h5 style={{ margin: 0 }}>{props.tableModel.title || "分析结果"}</h5>
            <span className="badge">rows: {props.tableModel.rows.length}</span>
          </div>
          <p className="muted" style={{ marginTop: 6 }}>
            {props.tableModel.subtitle || "分析结果将在此处展示。"}
          </p>
          {props.tableModel.columns.length === 0 ? <div className="muted">当前 execution 未提供表格结果。</div> : null}
          {props.tableModel.columns.length > 0 ? (
            <div className="workbench-table-wrap-react">
              <table className="workbench-result-table-react">
                <thead>
                  <tr>
                    {props.tableModel.columns.map((column) => (
                      <th key={column.key}>{column.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {props.tableModel.rows.length === 0 ? (
                    <tr>
                      <td colSpan={Math.max(1, props.tableModel.columns.length)} className="muted">
                        当前 execution 未提供表格结果。
                      </td>
                    </tr>
                  ) : (
                    props.tableModel.rows.map((row, rowIndex) => (
                      <tr key={`row_${rowIndex + 1}`}>
                        {props.tableModel.columns.map((column) => (
                          <td key={`${rowIndex + 1}_${column.key}`}>{asText(row[column.key], "-")}</td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {props.activeResultTab === "chart" ? (
        <section className="integrated-panel-react">
          <div className="row">
            <h5 style={{ margin: 0 }}>图表与 HTML 预览</h5>
            <span className="badge">charts: {props.chartItems.length}</span>
          </div>
          {props.chartItems.length === 0 ? <div className="muted">暂无图表数据。</div> : null}
          {props.chartItems.map((chart, index) => (
            <pre className="json-preview" key={`chart_${index + 1}`}>
              {compactPreview(chart)}
            </pre>
          ))}
          {props.htmlPreviewArtifact ? (
            <div className="html-preview-react">
              <div className="row">
                <strong>{props.htmlPreviewArtifact.name}</strong>
                <a className="btn" href={htmlPreviewUrl || "#"} target="_blank" rel="noreferrer">
                  打开文件
                </a>
              </div>
              {htmlPreviewUrl ? (
                <iframe className="html-frame-react" src={htmlPreviewUrl} title="HTML preview" />
              ) : (
                <div className="muted">HTML 文件已同步，但当前无法生成可预览地址。</div>
              )}
            </div>
          ) : null}
        </section>
      ) : null}

      {props.activeResultTab === "artifacts" ? (
        <section className="integrated-panel-react">
          <div className="row">
            <h5 style={{ margin: 0 }}>结果文件</h5>
            <span className="badge">{props.artifactItems.length}</span>
          </div>
          {props.artifactItems.length === 0 ? <div className="muted">暂无结果文件。</div> : null}
          <div className="artifact-list-react">
            {props.artifactItems.map((artifact) => {
              const fileUrl = localPathToFileUrl(artifact.local_path);
              return (
                <div key={`${artifact.name}_${artifact.local_path}`} className="artifact-item-react">
                  <div>
                    <strong>{artifact.name}</strong>
                    <div className="muted">{artifact.display_role || "result"}</div>
                  </div>
                  <div className="artifact-actions-react">
                    <span className="badge">{artifact.available ? "available" : "missing"}</span>
                    {artifact.local_path ? (
                      <a className="btn" href={fileUrl || "#"} target="_blank" rel="noreferrer">
                        本地打开
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {props.activeResultTab === "provenance" ? (
        <section className="integrated-panel-react">
          <div className="row">
            <h5 style={{ margin: 0 }}>运行追溯</h5>
            <span className="badge">{props.provenanceItems.length}</span>
          </div>
          {props.provenanceItems.length === 0 ? <div className="muted">暂无运行追溯信息。</div> : null}
          <div className="kv-list">
            {props.provenanceItems.map((item) => (
              <div key={`${item.label}_${item.value}`} className="kv-row">
                <span className="kv-key">{item.label}</span>
                <span className="kv-value">{item.value}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}

type ExecutionTraceProps = {
  workbenchExecutionId: string;
  setWorkbenchExecutionId: (value: string) => void;
  onLoadResult: () => void;
  onLoadRemoteStatus: () => void;
  workbenchToolId: string;
  setWorkbenchToolId: (value: string) => void;
  workbenchParamsJson: string;
  setWorkbenchParamsJson: (value: string) => void;
  onRunWorkbenchTool: () => void;
  workbenchMsg: string;
  remoteSummary: SummaryPair[];
  resultSummary: SummaryPair[];
  workbenchRemoteStatus: Record<string, unknown> | null;
  workbenchResult: Record<string, unknown> | null;
};

export function WorkbenchExecutionTrace(props: ExecutionTraceProps) {
  return (
    <section className="integrated-panel-react" style={{ marginTop: 12 }}>
      <div className="row">
        <h5 style={{ margin: 0 }}>执行追踪与回归</h5>
        <span className="badge">execution</span>
      </div>
      <div className="row" style={{ justifyContent: "flex-start", marginTop: 8 }}>
        <input
          className="input-control"
          style={{ maxWidth: 320, margin: 0 }}
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

      <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <label className="muted">Tool ID</label>
          <input className="input-control" value={props.workbenchToolId} onChange={(event) => props.setWorkbenchToolId(event.target.value)} />
          <label className="muted">Params JSON</label>
          <textarea
            className="input-control textarea-control"
            value={props.workbenchParamsJson}
            onChange={(event) => props.setWorkbenchParamsJson(event.target.value)}
          />
          <button className="btn" onClick={props.onRunWorkbenchTool}>
            提交高级工作流
          </button>
          {props.workbenchMsg ? <p className="ok-text">{props.workbenchMsg}</p> : null}
        </div>

        <div style={{ flex: 1 }}>
          <div className="split-title">远端状态摘要</div>
          <div className="kv-list">
            {props.remoteSummary.length === 0 ? <div className="muted">暂无远端状态</div> : null}
            {props.remoteSummary.map((entry) => (
              <div key={`remote_${entry.key}`} className="kv-row">
                <span className="kv-key">{entry.key}</span>
                <span className="kv-value">{entry.value}</span>
              </div>
            ))}
          </div>

          <div className="split-title" style={{ marginTop: 10 }}>
            结果摘要
          </div>
          <div className="kv-list">
            {props.resultSummary.length === 0 ? <div className="muted">暂无结果数据</div> : null}
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

type DatabasesProps = {
  configuredDatabases: ConfiguredDatabasePath[];
};

export function WorkbenchConfiguredDatabases(props: DatabasesProps) {
  return (
    <section className="integrated-panel-react" style={{ marginTop: 12 }}>
      <div className="row">
        <h5 style={{ margin: 0 }}>数据库路径</h5>
        <span className="badge">{props.configuredDatabases.length}</span>
      </div>
      {props.configuredDatabases.length === 0 ? <p className="muted">暂无数据库路径配置</p> : null}
      {props.configuredDatabases.slice(0, 12).map((entry) => (
        <div key={entry.key} className="history-row">
          <div className="row">
            <strong>{asText(entry.label || entry.key, "unknown_db_key")}</strong>
            <span className="badge">{asText(entry.key, "unknown")}</span>
          </div>
          <div className="muted">{asText(entry.path, "(empty path)")}</div>
        </div>
      ))}
    </section>
  );
}
