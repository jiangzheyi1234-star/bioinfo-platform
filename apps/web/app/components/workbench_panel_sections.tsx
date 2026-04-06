"use client";

import type {
  ArtifactItem,
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
import { asText } from "./workbench_panel_utils";
import { WorkspaceEmptyState as WorkspacePanelEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import {
  WorkbenchArtifactsPanel,
  WorkbenchChartPanel,
  WorkbenchProvenancePanel,
  WorkbenchTablePanel,
  WorkspaceEmptyState,
} from "./workbench_result_panels";

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
    <aside className="workbench-sidebar">
      <section className="workbench-sidebar-section">
        <button type="button" className="workbench-section-toggle" onClick={props.onToggleAnalysis}>
          <span>分析功能</span>
          <span className="badge">{props.features.length}</span>
        </button>
        {!props.analysisCollapsed ? (
          <div className="workbench-feature-list">
            {props.features.map((feature) => {
              const active = props.sourceMode === "workflow" && props.selectedWorkflowFeatureId === feature.id;
              return (
                <button
                  type="button"
                  key={feature.id}
                  className={`workbench-feature-item${active ? " active" : ""}`}
                  onClick={() => props.onSelectWorkflowFeature(feature.id)}
                >
                  <div className="workbench-feature-row">
                    <span className="workbench-feature-name">{feature.title}</span>
                    {feature.badge ? <span className="badge">{feature.badge}</span> : null}
                  </div>
                  <div className="workbench-feature-desc">{feature.description}</div>
                </button>
              );
            })}
          </div>
        ) : null}
      </section>

      <section className="workbench-sidebar-section">
        <div className="row workbench-sidebar-header-row">
          <button type="button" className="workbench-section-toggle" onClick={props.onToggleHistory}>
            <span>历史结果</span>
            <span className="badge">{props.visibleHistoryRows.length}</span>
          </button>
          <button className="btn" onClick={props.onClearUnpinned}>
            清理未固定
          </button>
        </div>
        {!props.historyCollapsed ? (
          <div className="workbench-feature-list">
            {props.visibleHistoryRows.length === 0 ? (
              <WorkspacePanelEmptyState
                mark="Hist"
                label="暂无历史结果"
                hint="工作台运行后的结果会保留在这里，支持固定、关闭和归档。"
                compact
              />
            ) : null}
            {props.visibleHistoryRows.map((row) => {
              const pinned = Boolean(props.historyPinned[row.execution_id]);
              const active = props.sourceMode === "history" && props.selectedHistoryExecutionId === row.execution_id;
              return (
                <div
                  key={row.execution_id}
                  className={`workbench-feature-item workbench-feature-item--history${active ? " active" : ""}`}
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
                  <div className="workbench-feature-row">
                    <span className="workbench-feature-name">{row.sample_name || row.sample_id || row.execution_id}</span>
                    <span className="badge">{row.status}</span>
                  </div>
                  <div className="workbench-feature-desc">
                    {row.tool_id} · {row.execution_id}
                  </div>
                  <div className="workbench-action-row">
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
  if (!props.selectedView) {
    return (
      <section className="workbench-content">
        <WorkspacePanelEmptyState
          className="workbench-empty"
          mark="Result"
          label="请选择分析功能或历史结果以查看详情。"
          hint="右侧结果区会保持固定布局，表格、图表、产物和溯源会在同一位置切换。"
        />
      </section>
    );
  }

  return (
    <section className="workbench-content">
      <header className="workbench-content-header">
        <WorkspaceSectionHeader
          title={asText(props.selectedView.title) || props.selectedFeature?.title || props.selectedFeature?.id || "未命名功能"}
          description={asText(props.selectedView.description) || props.selectedFeature?.description || "暂无描述"}
          titleAs="h4"
          aside={
            <button className="btn" onClick={props.onRun}>
              {props.sourceMode === "history" ? "重新运行" : "启动分析"}
            </button>
          }
          className="workbench-content-heading"
        />
        <div className="muted workbench-content-mode">{props.sourceMode === "history" ? "历史结果视图" : "工作流功能视图"}</div>
      </header>

      <div className="workbench-summary-grid">
        {props.summaryItems.length > 0
          ? props.summaryItems.map((item) => (
              <div className="workbench-summary-item" key={`${item.label}_${item.tone}`}>
                <div className="muted">{item.label}</div>
                <strong>{item.value}</strong>
              </div>
            ))
          : null}
        {props.summaryItems.length === 0 && props.summaryPairs.length > 0
          ? props.summaryPairs.map((item) => (
              <div className="workbench-summary-item" key={item.key}>
                <div className="muted">{item.key}</div>
                <strong>{item.value}</strong>
              </div>
            ))
          : null}
        {props.summaryItems.length === 0 && props.summaryPairs.length === 0 ? <WorkspaceEmptyState label="暂无 summary 信息" /> : null}
      </div>

      <div className="workbench-reading-flow-intro">
        <span>结果页按阅读顺序展示结论、数据、预览、文件与追溯。</span>
      </div>

      <div className="workbench-tabs" role="tablist" aria-label="结果锚点">
        <button
          type="button"
          className={`workbench-tab-btn${props.activeResultTab === "table" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("table")}
        >
          数据表格
        </button>
        <button
          type="button"
          className={`workbench-tab-btn${props.activeResultTab === "chart" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("chart")}
        >
          图表
        </button>
        <button
          type="button"
          className={`workbench-tab-btn${props.activeResultTab === "artifacts" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("artifacts")}
        >
          产物文件
        </button>
        <button
          type="button"
          className={`workbench-tab-btn${props.activeResultTab === "provenance" ? " active" : ""}`}
          onClick={() => props.onChangeResultTab("provenance")}
        >
          溯源信息
        </button>
      </div>

      <div className="workbench-reading-flow">
        {(props.tableModel.columns.length > 0 || props.tableModel.rows.length > 0) ? (
          <WorkbenchTablePanel tableModel={props.tableModel} active={props.activeResultTab === "table"} />
        ) : null}
        {(props.chartItems.length > 0 || props.htmlPreviewArtifact) ? (
          <WorkbenchChartPanel
            chartItems={props.chartItems}
            htmlPreviewArtifact={props.htmlPreviewArtifact}
            active={props.activeResultTab === "chart"}
          />
        ) : null}
        {props.artifactItems.length > 0 ? (
          <WorkbenchArtifactsPanel artifactItems={props.artifactItems} active={props.activeResultTab === "artifacts"} />
        ) : null}
        {props.provenanceItems.length > 0 ? (
          <WorkbenchProvenancePanel provenanceItems={props.provenanceItems} active={props.activeResultTab === "provenance"} />
        ) : null}
        {props.tableModel.columns.length === 0 &&
        props.tableModel.rows.length === 0 &&
        props.chartItems.length === 0 &&
        !props.htmlPreviewArtifact &&
        props.artifactItems.length === 0 &&
        props.provenanceItems.length === 0 ? (
          <WorkspaceEmptyState label="当前结果尚未生成可读内容。" />
        ) : null}
      </div>
    </section>
  );
}
