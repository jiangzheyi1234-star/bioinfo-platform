"use client";

import { useEffect, useMemo, useState } from "react";
import {
  WorkbenchConfiguredDatabases,
  WorkbenchContent,
  WorkbenchExecutionTrace,
  WorkbenchSidebar,
} from "./workbench_panel_sections";
import type {
  ConfiguredDatabasePath,
  ResultTab,
  ViewSourceMode,
  WorkbenchConfig,
  WorkbenchFeature,
  WorkbenchHistoryRow,
  WorkbenchView,
} from "./workbench_panel_types";
import {
  apiBase,
  asText,
  getViewToolId,
  isRecord,
  normalizeArtifacts,
  normalizeCharts,
  normalizeProvenanceItems,
  normalizeSummaryItems,
  normalizeTableModel,
  parseWorkbenchFeatures,
  parseWorkbenchViews,
  readJsonOrThrow,
  resolveDefaultResultTab,
  summarizePairs,
  toConfiguredDatabasePath,
  toWorkbenchHistoryRow,
} from "./workbench_panel_utils";

type WorkbenchPanelProps = {
  currentProjectId: string;
  onError: (message: string) => void;
  onAfterRun: () => Promise<void>;
};

export function WorkbenchPanel({ currentProjectId, onError, onAfterRun }: WorkbenchPanelProps) {
  const [workbenchConfig, setWorkbenchConfig] = useState<WorkbenchConfig | null>(null);
  const [workbenchHistoryRows, setWorkbenchHistoryRows] = useState<WorkbenchHistoryRow[]>([]);
  const [historyViews, setHistoryViews] = useState<Record<string, WorkbenchView>>({});
  const [historyPinned, setHistoryPinned] = useState<Record<string, boolean>>({});
  const [historyClosed, setHistoryClosed] = useState<Record<string, boolean>>({});

  const [workbenchExecutionId, setWorkbenchExecutionId] = useState<string>("");
  const [workbenchResult, setWorkbenchResult] = useState<Record<string, unknown> | null>(null);
  const [workbenchRemoteStatus, setWorkbenchRemoteStatus] = useState<Record<string, unknown> | null>(null);

  const [workbenchToolId, setWorkbenchToolId] = useState<string>("unknown_sample_detection");
  const [workbenchParamsJson, setWorkbenchParamsJson] = useState<string>('{"sample_name":"wb_sample"}');
  const [workbenchMsg, setWorkbenchMsg] = useState<string>("");
  const [deletingExecutionId, setDeletingExecutionId] = useState<string>("");
  const [configuredDatabases, setConfiguredDatabases] = useState<ConfiguredDatabasePath[]>([]);

  const [analysisCollapsed, setAnalysisCollapsed] = useState<boolean>(false);
  const [historyCollapsed, setHistoryCollapsed] = useState<boolean>(false);
  const [sourceMode, setSourceMode] = useState<ViewSourceMode>("workflow");
  const [selectedWorkflowFeatureId, setSelectedWorkflowFeatureId] = useState<string>("");
  const [selectedHistoryExecutionId, setSelectedHistoryExecutionId] = useState<string>("");
  const [activeResultTab, setActiveResultTab] = useState<ResultTab>("table");

  const features = useMemo(() => parseWorkbenchFeatures(workbenchConfig), [workbenchConfig]);
  const views = useMemo(() => parseWorkbenchViews(workbenchConfig), [workbenchConfig]);

  const featureById = useMemo(() => {
    const result: Record<string, WorkbenchFeature> = {};
    for (const feature of features) {
      result[feature.id] = feature;
    }
    return result;
  }, [features]);

  const selectedWorkflowFeature = selectedWorkflowFeatureId ? (featureById[selectedWorkflowFeatureId] ?? null) : null;
  const selectedWorkflowView = selectedWorkflowFeatureId ? (views[selectedWorkflowFeatureId] ?? null) : null;

  const selectedHistoryRow = selectedHistoryExecutionId
    ? workbenchHistoryRows.find((row) => row.execution_id === selectedHistoryExecutionId) ?? null
    : null;
  const selectedHistoryView = selectedHistoryExecutionId ? (historyViews[selectedHistoryExecutionId] ?? null) : null;
  const selectedHistoryFeatureId = asText(selectedHistoryView?.feature_id) || asText(selectedHistoryRow?.tool_id);
  const selectedHistoryFeature = selectedHistoryFeatureId ? (featureById[selectedHistoryFeatureId] ?? null) : null;

  const selectedFeature = sourceMode === "history" ? selectedHistoryFeature : selectedWorkflowFeature;
  const selectedView = sourceMode === "history" ? selectedHistoryView : selectedWorkflowView;

  const summaryItems = normalizeSummaryItems(selectedView?.summary);
  const summaryPairs = summaryItems.length > 0 ? [] : summarizePairs(selectedView?.summary);
  const tableModel = normalizeTableModel(selectedView);
  const artifactItems = normalizeArtifacts(selectedView);
  const provenanceItems = normalizeProvenanceItems(selectedView);
  const chartItems = normalizeCharts(selectedView);

  const resultSummary = summarizePairs(workbenchResult);
  const remoteSummary = summarizePairs(workbenchRemoteStatus);

  const visibleHistoryRows = useMemo(
    () => workbenchHistoryRows.filter((row) => historyPinned[row.execution_id] || !historyClosed[row.execution_id]),
    [workbenchHistoryRows, historyPinned, historyClosed]
  );

  const htmlPreviewArtifact = artifactItems.find(
    (item) => item.available && item.local_path && (item.viewer_hint === "html" || item.name.toLowerCase().endsWith(".html"))
  );

  useEffect(() => {
    if (features.length === 0) {
      setSelectedWorkflowFeatureId("");
      return;
    }
    const exists = features.some((feature) => feature.id === selectedWorkflowFeatureId);
    if (!exists) {
      const defaultFeatureId = features[0].id;
      setSelectedWorkflowFeatureId(defaultFeatureId);
      const defaultView = views[defaultFeatureId] ?? null;
      setActiveResultTab(resolveDefaultResultTab(defaultView));
    }
  }, [features, selectedWorkflowFeatureId, views]);

  useEffect(() => {
    const nextToolId = getViewToolId(selectedFeature, selectedView);
    if (nextToolId) {
      setWorkbenchToolId(nextToolId);
    }
  }, [selectedFeature, selectedView]);

  const refreshWorkbenchConfig = async (projectId: string) => {
    if (!projectId) {
      setWorkbenchConfig(null);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/workbench/config`);
    const data = await readJsonOrThrow(resp);
    const item = data?.item;
    setWorkbenchConfig(item && typeof item === "object" ? (item as WorkbenchConfig) : null);
  };

  const refreshWorkbenchHistory = async (projectId: string) => {
    if (!projectId) {
      setWorkbenchHistoryRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/workbench/history`);
    const data = await readJsonOrThrow(resp);
    const items: WorkbenchHistoryRow[] = Array.isArray(data.items)
      ? data.items
          .map(toWorkbenchHistoryRow)
          .filter((item: WorkbenchHistoryRow | null): item is WorkbenchHistoryRow => !!item)
      : [];
    setWorkbenchHistoryRows(items);

    const knownExecutionIds = new Set(items.map((item) => item.execution_id));
    setHistoryViews((prev) => {
      const next: Record<string, WorkbenchView> = {};
      for (const [executionId, view] of Object.entries(prev)) {
        if (knownExecutionIds.has(executionId)) {
          next[executionId] = view;
        }
      }
      return next;
    });
  };

  const refreshConfiguredDatabases = async (projectId: string) => {
    if (!projectId) {
      setConfiguredDatabases([]);
      return;
    }
    const resp = await fetch(
      `${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/workbench/configured-databases`
    );
    const data = await readJsonOrThrow(resp);
    const items: ConfiguredDatabasePath[] = Array.isArray(data.items)
      ? data.items
          .map(toConfiguredDatabasePath)
          .filter((item: ConfiguredDatabasePath | null): item is ConfiguredDatabasePath => !!item)
      : [];
    setConfiguredDatabases(items);
  };

  useEffect(() => {
    const run = async () => {
      if (!currentProjectId) {
        setWorkbenchConfig(null);
        setWorkbenchHistoryRows([]);
        setHistoryViews({});
        setConfiguredDatabases([]);
        setWorkbenchResult(null);
        setWorkbenchRemoteStatus(null);
        setSelectedHistoryExecutionId("");
        setSourceMode("workflow");
        return;
      }
      try {
        await refreshWorkbenchConfig(currentProjectId);
        await refreshWorkbenchHistory(currentProjectId);
        await refreshConfiguredDatabases(currentProjectId);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        onError(msg);
      }
    };
    void run();
  }, [currentProjectId, onError]);

  const runWorkbenchTool = async () => {
    if (!currentProjectId) {
      onError("No active project selected.");
      return;
    }
    setWorkbenchMsg("");
    try {
      const parsed = workbenchParamsJson.trim() ? JSON.parse(workbenchParamsJson) : {};
      const resp = await fetch(`${apiBase()}/api/v1/workbench/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          tool_id: workbenchToolId,
          params: parsed,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const item = data?.item ?? {};
      const executionId = asText(item.execution_id);
      setWorkbenchExecutionId(executionId);
      setWorkbenchMsg(executionId ? `已提交高级工作流任务: ${executionId}` : "已提交高级工作流任务");
      await refreshWorkbenchHistory(currentProjectId);
      await onAfterRun();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(msg);
    }
  };

  const loadWorkbenchResult = async (executionIdOverride?: string): Promise<WorkbenchView | null> => {
    const executionId = asText(executionIdOverride || workbenchExecutionId).trim();
    if (!currentProjectId || !executionId) {
      onError("请输入 execution_id 并确保已选择项目。");
      return null;
    }
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/workbench/executions/${encodeURIComponent(
          executionId
        )}/result`
      );
      const data = await readJsonOrThrow(resp);
      const payload = data?.item;
      if (!isRecord(payload)) {
        throw new Error("workbench result payload invalid");
      }
      setWorkbenchResult(payload);
      const view = isRecord(payload.view) ? (payload.view as WorkbenchView) : null;
      return view;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(msg);
      return null;
    }
  };

  const loadWorkbenchRemoteStatus = async (executionIdOverride?: string) => {
    const executionId = asText(executionIdOverride || workbenchExecutionId).trim();
    if (!currentProjectId || !executionId) {
      onError("请输入 execution_id 并确保已选择项目。");
      return;
    }
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/workbench/executions/${encodeURIComponent(
          executionId
        )}/remote-status`
      );
      const data = await readJsonOrThrow(resp);
      const item = data?.item;
      setWorkbenchRemoteStatus(item && typeof item === "object" ? (item as Record<string, unknown>) : null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(msg);
    }
  };

  const selectWorkflowFeature = (featureId: string) => {
    setSourceMode("workflow");
    setSelectedWorkflowFeatureId(featureId);
    setSelectedHistoryExecutionId("");
    const view = views[featureId] ?? null;
    setActiveResultTab(resolveDefaultResultTab(view));
  };

  const selectHistoryResult = async (row: WorkbenchHistoryRow) => {
    if (!currentProjectId) {
      onError("No active project selected.");
      return;
    }

    const executionId = row.execution_id;
    setWorkbenchExecutionId(executionId);

    let view = historyViews[executionId] ?? null;
    if (!view) {
      const loaded = await loadWorkbenchResult(executionId);
      if (!loaded) {
        return;
      }
      view = loaded;
      setHistoryViews((prev) => ({ ...prev, [executionId]: loaded }));
    }

    setSourceMode("history");
    setSelectedHistoryExecutionId(executionId);
    setActiveResultTab(resolveDefaultResultTab(view));
  };

  const togglePinHistoryResult = (executionId: string) => {
    setHistoryPinned((prev) => ({ ...prev, [executionId]: !prev[executionId] }));
  };

  const closeHistoryResult = (executionId: string) => {
    setHistoryClosed((prev) => ({ ...prev, [executionId]: true }));
    if (sourceMode === "history" && selectedHistoryExecutionId === executionId) {
      setSourceMode("workflow");
      setSelectedHistoryExecutionId("");
      const fallbackView = selectedWorkflowFeatureId ? views[selectedWorkflowFeatureId] ?? null : null;
      setActiveResultTab(resolveDefaultResultTab(fallbackView));
    }
  };

  const clearUnpinnedHistoryResults = () => {
    const pinnedExecutionIds = new Set(
      Object.entries(historyPinned)
        .filter((entry) => entry[1])
        .map((entry) => entry[0])
    );

    setHistoryViews((prev) => {
      const next: Record<string, WorkbenchView> = {};
      for (const [executionId, view] of Object.entries(prev)) {
        if (pinnedExecutionIds.has(executionId)) {
          next[executionId] = view;
        }
      }
      return next;
    });

    setHistoryClosed((prev) => {
      const next = { ...prev };
      for (const row of workbenchHistoryRows) {
        if (!pinnedExecutionIds.has(row.execution_id)) {
          next[row.execution_id] = true;
        }
      }
      return next;
    });

    if (sourceMode === "history" && selectedHistoryExecutionId && !pinnedExecutionIds.has(selectedHistoryExecutionId)) {
      setSourceMode("workflow");
      setSelectedHistoryExecutionId("");
      const fallbackView = selectedWorkflowFeatureId ? views[selectedWorkflowFeatureId] ?? null : null;
      setActiveResultTab(resolveDefaultResultTab(fallbackView));
    }
  };

  const deleteWorkbenchExecution = async (executionId: string) => {
    if (!currentProjectId) {
      onError("No active project selected.");
      return;
    }
    setDeletingExecutionId(executionId);
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/workbench/executions/${encodeURIComponent(
          executionId
        )}`,
        { method: "DELETE" }
      );
      await readJsonOrThrow(resp);
      await refreshWorkbenchHistory(currentProjectId);
      await onAfterRun();
      if (workbenchExecutionId === executionId) {
        setWorkbenchExecutionId("");
      }
      setHistoryViews((prev) => {
        const next = { ...prev };
        delete next[executionId];
        return next;
      });
      setHistoryPinned((prev) => {
        const next = { ...prev };
        delete next[executionId];
        return next;
      });
      setHistoryClosed((prev) => {
        const next = { ...prev };
        delete next[executionId];
        return next;
      });
      if (selectedHistoryExecutionId === executionId) {
        setSourceMode("workflow");
        setSelectedHistoryExecutionId("");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(msg);
    } finally {
      setDeletingExecutionId("");
    }
  };

  return (
    <div className="panel workbench-panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Integrated Result Workbench</h3>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={() => void refreshWorkbenchConfig(currentProjectId)}>
            刷新配置
          </button>
          <button className="btn" onClick={() => void refreshWorkbenchHistory(currentProjectId)}>
            刷新历史
          </button>
        </div>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        分析功能 {features.length} 项，历史任务 {workbenchHistoryRows.length} 项，数据库路径 {configuredDatabases.length} 项。
      </p>

      <div className="integrated-shell-react">
        <WorkbenchSidebar
          features={features}
          sourceMode={sourceMode}
          selectedWorkflowFeatureId={selectedWorkflowFeatureId}
          analysisCollapsed={analysisCollapsed}
          onToggleAnalysis={() => setAnalysisCollapsed((prev) => !prev)}
          onSelectWorkflowFeature={selectWorkflowFeature}
          visibleHistoryRows={visibleHistoryRows}
          historyCollapsed={historyCollapsed}
          onToggleHistory={() => setHistoryCollapsed((prev) => !prev)}
          onClearUnpinned={clearUnpinnedHistoryResults}
          historyPinned={historyPinned}
          selectedHistoryExecutionId={selectedHistoryExecutionId}
          onSelectHistoryResult={(row) => {
            void selectHistoryResult(row);
          }}
          onTogglePinHistoryResult={togglePinHistoryResult}
          onCloseHistoryResult={closeHistoryResult}
          deletingExecutionId={deletingExecutionId}
          onDeleteWorkbenchExecution={(executionId) => {
            void deleteWorkbenchExecution(executionId);
          }}
        />

        <WorkbenchContent
          sourceMode={sourceMode}
          selectedFeature={selectedFeature}
          selectedView={selectedView}
          activeResultTab={activeResultTab}
          onChangeResultTab={setActiveResultTab}
          onRun={() => {
            void runWorkbenchTool();
          }}
          summaryItems={summaryItems}
          summaryPairs={summaryPairs}
          tableModel={tableModel}
          chartItems={chartItems}
          htmlPreviewArtifact={htmlPreviewArtifact}
          artifactItems={artifactItems}
          provenanceItems={provenanceItems}
        />
      </div>

      <WorkbenchExecutionTrace
        workbenchExecutionId={workbenchExecutionId}
        setWorkbenchExecutionId={setWorkbenchExecutionId}
        onLoadResult={() => {
          void loadWorkbenchResult();
        }}
        onLoadRemoteStatus={() => {
          void loadWorkbenchRemoteStatus();
        }}
        workbenchToolId={workbenchToolId}
        setWorkbenchToolId={setWorkbenchToolId}
        workbenchParamsJson={workbenchParamsJson}
        setWorkbenchParamsJson={setWorkbenchParamsJson}
        onRunWorkbenchTool={() => {
          void runWorkbenchTool();
        }}
        workbenchMsg={workbenchMsg}
        remoteSummary={remoteSummary}
        resultSummary={resultSummary}
        workbenchRemoteStatus={workbenchRemoteStatus}
        workbenchResult={workbenchResult}
      />

      <WorkbenchConfiguredDatabases configuredDatabases={configuredDatabases} />
    </div>
  );
}
