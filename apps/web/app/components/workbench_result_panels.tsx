"use client";

import type { ArtifactItem, ProvenanceItem, SummaryPair, TableModel } from "./workbench_panel_types";
import { asText, compactPreview, localPathToFileUrl } from "./workbench_panel_utils";
import {
  WorkspaceEmptyState as WorkspaceEmptyStatePrimitive,
  WorkspaceSectionHeader,
} from "./workspace_section_primitives";

type TablePanelProps = {
  tableModel: TableModel;
  active?: boolean;
};

export function WorkbenchTablePanel({ tableModel, active = false }: TablePanelProps) {
  return (
    <section className={`workbench-result-section${active ? " is-active" : ""}`}>
      <WorkspaceSectionHeader
        title={tableModel.title || "分析结果"}
        description={tableModel.subtitle || "分析结果将在此处展示。"}
        aside={<span className="badge">rows: {tableModel.rows.length}</span>}
        titleAs="h5"
      />
      {tableModel.columns.length === 0 ? <div className="muted">当前 execution 未提供表格结果。</div> : null}
      {tableModel.columns.length > 0 ? (
        <div className="workbench-table-wrap-react">
          <table className="workbench-result-table-react">
            <thead>
              <tr>
                {tableModel.columns.map((column) => (
                  <th key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableModel.rows.length === 0 ? (
                <tr>
                  <td colSpan={Math.max(1, tableModel.columns.length)} className="muted">
                    当前 execution 未提供表格结果。
                  </td>
                </tr>
              ) : (
                tableModel.rows.map((row, rowIndex) => (
                  <tr key={`row_${rowIndex + 1}`}>
                    {tableModel.columns.map((column) => (
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
  );
}

type ChartPanelProps = {
  chartItems: unknown[];
  htmlPreviewArtifact?: ArtifactItem;
  active?: boolean;
};

export function WorkbenchChartPanel({ chartItems, htmlPreviewArtifact, active = false }: ChartPanelProps) {
  const htmlPreviewUrl = localPathToFileUrl(htmlPreviewArtifact?.local_path || "");

  return (
    <section className={`workbench-result-section${active ? " is-active" : ""}`}>
      <WorkspaceSectionHeader title="图表与 HTML 预览" aside={<span className="badge">charts: {chartItems.length}</span>} titleAs="h5" />
      {chartItems.length === 0 ? <div className="muted">暂无图表数据。</div> : null}
      {chartItems.map((chart, index) => (
        <pre className="json-preview" key={`chart_${index + 1}`}>
          {compactPreview(chart)}
        </pre>
      ))}
      {htmlPreviewArtifact ? (
        <div className="html-preview-react">
          <div className="row">
            <strong>{htmlPreviewArtifact.name}</strong>
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
  );
}

type ArtifactsPanelProps = {
  artifactItems: ArtifactItem[];
  active?: boolean;
};

export function WorkbenchArtifactsPanel({ artifactItems, active = false }: ArtifactsPanelProps) {
  return (
    <section className={`workbench-result-section${active ? " is-active" : ""}`}>
      <WorkspaceSectionHeader title="结果文件" aside={<span className="badge">{artifactItems.length}</span>} titleAs="h5" />
      {artifactItems.length === 0 ? <div className="muted">暂无结果文件。</div> : null}
      <div className="artifact-list-react">
        {artifactItems.map((artifact) => {
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
  );
}

type ProvenancePanelProps = {
  provenanceItems: ProvenanceItem[];
  active?: boolean;
};

export function WorkbenchProvenancePanel({ provenanceItems, active = false }: ProvenancePanelProps) {
  return (
    <section className={`workbench-result-section${active ? " is-active" : ""}`}>
      <WorkspaceSectionHeader title="运行追溯" aside={<span className="badge">{provenanceItems.length}</span>} titleAs="h5" />
      {provenanceItems.length === 0 ? <div className="muted">暂无运行追溯信息。</div> : null}
      <div className="kv-list">
        {provenanceItems.map((item) => (
          <div key={`${item.label}_${item.value}`} className="kv-row">
            <span className="kv-key">{item.label}</span>
            <span className="kv-value">{item.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

type EmptyPanelProps = {
  label: string;
};

export function WorkspaceEmptyState({ label }: EmptyPanelProps) {
  return <WorkspaceEmptyStatePrimitive label={label} compact className="workbench-inline-empty" />;
}
