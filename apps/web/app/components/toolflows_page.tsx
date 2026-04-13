"use client";

import { useEffect, useMemo, useState } from "react";

import type { ToolDescriptor, ToolSummary } from "./detection_workspace_types";
import { apiBase, isRecord, readJsonOrThrow, safeText, toToolSummary } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import type { SummaryPair, TableModel, WorkbenchConfig, WorkbenchFeature, WorkbenchView } from "./workbench_panel_types";
import {
  normalizeSummaryItems,
  normalizeTableModel,
  parseWorkbenchFeatures,
  parseWorkbenchViews,
  summarizePairs,
} from "./workbench_panel_utils";
import { useWorkspaceShell } from "./workspace_shell_context";

type CatalogMode = "tools" | "flows";

function formatFlowPairs(view: WorkbenchView | null): SummaryPair[] {
  const summaryItems = normalizeSummaryItems(view?.summary);
  if (summaryItems.length > 0) {
    return summaryItems.map((item) => ({ key: item.label, value: item.value }));
  }
  return summarizePairs(view?.summary);
}

function FlowPreview({
  feature,
  view,
}: {
  feature: WorkbenchFeature | null;
  view: WorkbenchView | null;
}) {
  if (!feature) {
    return <WorkspaceEmptyState mark="Flow" label="请选择流程" hint="左侧流程目录会驱动这里的流程说明和视图摘要。" />;
  }

  const summaryPairs = formatFlowPairs(view);
  const tableModel: TableModel = normalizeTableModel(view);

  return (
    <div className="toolflows-detail-stack">
      <WorkspaceSectionHeader
        title={feature.title}
        description={feature.description || "当前流程未提供额外说明。"}
        aside={
          <div className="meta-row">
            {feature.badge ? <span className="badge">{feature.badge}</span> : null}
            <span className="badge">{feature.status || "unknown"}</span>
          </div>
        }
      />

      {summaryPairs.length === 0 ? (
        <WorkspaceEmptyState mark="Flow" label="当前流程暂无摘要" hint="流程解析成功，但没有可展示的 summary 字段。" compact />
      ) : (
        <div className="toolflows-summary-grid">
          {summaryPairs.map((item) => (
            <article key={item.key} className="toolflows-summary-card">
              <span className="toolflows-summary-label">{item.key}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
      )}

      <section className="toolflows-detail-panel">
        <WorkspaceSectionHeader title={tableModel.title} description={tableModel.subtitle} aside={<span className="badge">{tableModel.rows.length}</span>} titleAs="h4" />
        {tableModel.columns.length === 0 || tableModel.rows.length === 0 ? (
          <WorkspaceEmptyState mark="Tbl" label="当前流程暂无表格预览" hint="如果流程配置里提供 table 结构，这里会展示首批结果列。" compact />
        ) : (
          <div className="toolflows-table-wrap">
            <table className="toolflows-table">
              <thead>
                <tr>
                  {tableModel.columns.map((column) => (
                    <th key={column.key}>{column.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableModel.rows.slice(0, 8).map((row, index) => (
                  <tr key={`${index}_${row[tableModel.columns[0]?.key] ?? "row"}`}>
                    {tableModel.columns.map((column) => (
                      <td key={column.key}>{row[column.key]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function ToolflowsPage() {
  const { currentProject, currentProjectId, setShellError } = useWorkspaceShell();

  const [mode, setMode] = useState<CatalogMode>("tools");
  const [search, setSearch] = useState("");
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [selectedToolId, setSelectedToolId] = useState("");
  const [selectedDescriptor, setSelectedDescriptor] = useState<ToolDescriptor | null>(null);
  const [toolRunMsg, setToolRunMsg] = useState("");
  const [workbenchConfig, setWorkbenchConfig] = useState<WorkbenchConfig | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState("");

  const features = useMemo(() => parseWorkbenchFeatures(workbenchConfig), [workbenchConfig]);
  const views = useMemo(() => parseWorkbenchViews(workbenchConfig), [workbenchConfig]);
  const selectedFlow = selectedFlowId ? features.find((feature) => feature.id === selectedFlowId) ?? null : null;
  const selectedFlowView = selectedFlowId ? (views[selectedFlowId] ?? null) : null;

  const visibleTools = useMemo(() => {
    const query = search.trim().toLowerCase();
    return tools.filter((tool) => {
      if (!query) {
        return true;
      }
      return `${tool.id} ${tool.name} ${tool.category} ${tool.description}`.toLowerCase().includes(query);
    });
  }, [search, tools]);

  const visibleFlows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return features.filter((feature) => {
      if (!query) {
        return true;
      }
      return `${feature.id} ${feature.title} ${feature.description} ${feature.badge} ${feature.status}`.toLowerCase().includes(query);
    });
  }, [features, search]);

  const refreshTools = async () => {
    const resp = await fetch(`${apiBase()}/api/v1/tools`);
    const data = (await readJsonOrThrow(resp)) as { items?: unknown[] };
    const items = Array.isArray(data.items)
      ? data.items.map(toToolSummary).filter((item: ToolSummary | null): item is ToolSummary => !!item)
      : [];
    setTools(items);
    setSelectedToolId((prev) => (prev && items.some((tool) => tool.id === prev) ? prev : items[0]?.id || ""));
  };

  const loadToolDescriptor = async (toolId: string) => {
    const normalized = safeText(toolId);
    if (!normalized) {
      setSelectedDescriptor(null);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/tools/${encodeURIComponent(normalized)}/descriptor`);
    const data = await readJsonOrThrow(resp);
    setSelectedDescriptor(isRecord(data?.item) ? (data.item as ToolDescriptor) : null);
  };

  const refreshFlows = async (projectId: string) => {
    if (!projectId) {
      setWorkbenchConfig(null);
      setSelectedFlowId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/workbench/config`);
    const data = await readJsonOrThrow(resp);
    const item = data?.item;
    const config = item && typeof item === "object" ? (item as WorkbenchConfig) : null;
    setWorkbenchConfig(config);
    const nextFeatures = parseWorkbenchFeatures(config);
    setSelectedFlowId((prev) => (prev && nextFeatures.some((feature) => feature.id === prev) ? prev : nextFeatures[0]?.id || ""));
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshTools();
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [setShellError]);

  useEffect(() => {
    if (!selectedToolId) {
      setSelectedDescriptor(null);
      return;
    }
    void (async () => {
      try {
        await loadToolDescriptor(selectedToolId);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [selectedToolId, setShellError]);

  useEffect(() => {
    void (async () => {
      try {
        await refreshFlows(currentProjectId);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId, setShellError]);

  useEffect(() => {
    setSearch("");
  }, [mode]);

  return (
    <section className="toolflows-page">
      <input className="control-input toolflows-hero-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={mode === "tools" ? "搜索工具" : "搜索流程"} aria-label={mode === "tools" ? "搜索工具" : "搜索流程"} />

      <div className="toolflows-mode-tabs" role="tablist" aria-label="工具和流程切换">
        <button type="button" className={`toolflows-mode-tab${mode === "tools" ? " active" : ""}`} onClick={() => setMode("tools")}>
          工具
        </button>
        <button type="button" className={`toolflows-mode-tab${mode === "flows" ? " active" : ""}`} onClick={() => setMode("flows")}>
          流程
        </button>
      </div>

      {mode === "tools" ? (
        <section className="toolflows-layout">
          <section className="toolflows-catalog">
            <div className="toolflows-section-head">
              <h3>工具目录</h3>
              <span className="badge">{visibleTools.length}</span>
            </div>
            {visibleTools.length === 0 ? (
              <WorkspaceEmptyState mark="Tool" label="未找到可用工具" hint="调整搜索关键字或筛选项后重试。" compact />
            ) : (
              <div className="toolflows-card-grid">
                {visibleTools.map((tool) => (
                  <button key={tool.id} type="button" className={`toolflows-card${selectedToolId === tool.id ? " active" : ""}`} onClick={() => setSelectedToolId(tool.id)}>
                    <div className="toolflows-card-head">
                      <strong>{tool.name}</strong>
                      {tool.category ? <span className="badge">{tool.category}</span> : null}
                    </div>
                    <p>{tool.description || "当前工具未提供描述。"}</p>
                    <span className="toolflows-card-meta">{tool.id}</span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="toolflows-detail">
            {!selectedDescriptor ? (
              <WorkspaceEmptyState mark="Tool" label="请选择工具" hint="选中左侧工具后，这里会展示工具说明和执行表单。" />
            ) : (
              <div className="toolflows-detail-stack">
                <WorkspaceSectionHeader
                  title={safeText(selectedDescriptor.name, selectedToolId)}
                  description={safeText(selectedDescriptor.description, "当前工具未提供描述。")}
                  aside={
                    <div className="meta-row">
                      <span className="badge">{safeText(selectedDescriptor.id, selectedToolId)}</span>
                      <span className="badge">{safeText(selectedDescriptor.category, "unknown")}</span>
                    </div>
                  }
                />
                <section className="toolflows-detail-panel">
                  <WorkspaceEmptyState
                    mark="WF"
                    label="工具目录现在只提供只读浏览"
                    hint="新的分析提交统一迁移到 /workspace 的 workflow/run 主线；这里不再直接运行旧工具。"
                    compact
                  />
                  {toolRunMsg ? <p className="ok-text">{toolRunMsg}</p> : null}
                </section>
              </div>
            )}
          </section>
        </section>
      ) : (
        <section className="toolflows-layout">
          <section className="toolflows-catalog">
            <div className="toolflows-section-head">
              <h3>流程目录</h3>
              <span className="badge">{visibleFlows.length}</span>
            </div>
            {!currentProjectId ? (
              <WorkspaceEmptyState mark="Flow" label="尚未选择项目" hint="先选择项目，再加载该项目下的流程目录。" compact />
            ) : visibleFlows.length === 0 ? (
              <WorkspaceEmptyState mark="Flow" label="当前项目暂无流程" hint="该项目的 workbench/config 尚未提供可解析的 feature。" compact />
            ) : (
              <div className="toolflows-card-grid">
                {visibleFlows.map((feature) => (
                  <button key={feature.id} type="button" className={`toolflows-card${selectedFlowId === feature.id ? " active" : ""}`} onClick={() => setSelectedFlowId(feature.id)}>
                    <div className="toolflows-card-head">
                      <strong>{feature.title}</strong>
                      {feature.badge ? <span className="badge">{feature.badge}</span> : null}
                    </div>
                    <p>{feature.description || "当前流程未提供描述。"}</p>
                    <span className="toolflows-card-meta">{feature.status || feature.id}</span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="toolflows-detail">
            <FlowPreview feature={selectedFlow} view={selectedFlowView} />
          </section>
        </section>
      )}
    </section>
  );
}
