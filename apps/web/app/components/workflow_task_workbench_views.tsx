"use client";

import { CheckIcon, ClipboardDocumentIcon, SparklesIcon } from "@heroicons/react/24/outline";
import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { Task, WorkflowArtifact, WorkflowCompilePreview, WorkflowResult, WorkflowRun } from "./detection_workspace_types";
import { readWorkflowRemoteValue } from "./workflow_console_state";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { formatDateTime, mapWorkflowRunStatus } from "./workflow_support";
import type { ProjectWorkspaceTab } from "./workspace_shell_context";

const shellSurfaceStyle: CSSProperties = {
  display: "grid",
  gap: 18,
};

const linearSectionStyle: CSSProperties = {
  display: "grid",
  gap: 14,
  paddingTop: 12,
  borderTop: "1px solid var(--workspace-line-soft)",
};

const responsiveGridStyle: CSSProperties = {
  display: "grid",
  gap: 18,
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
};

const softPanelStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  minWidth: 0,
};

const keyValueListStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};

const quickActionRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
};

const metricRowStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
};

const metricStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "12px 0",
  borderTop: "1px solid var(--workspace-line-soft)",
};

const metricLabelStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--workspace-ink-soft)",
};

const metricValueStyle: CSSProperties = {
  fontSize: 15,
  fontWeight: 600,
  color: "var(--text-main)",
};

const copyStyle: CSSProperties = {
  margin: 0,
  color: "var(--workspace-ink-soft)",
  fontSize: 13,
  lineHeight: 1.6,
};

const subtleCalloutStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: "14px 16px",
  borderRadius: 18,
  border: "1px solid rgba(205, 219, 245, 0.9)",
  background: "rgba(244, 248, 255, 0.92)",
};

const hintPillStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "6px 10px",
  borderRadius: 999,
  background: "rgba(233, 237, 243, 0.72)",
  color: "#45556f",
  fontSize: 12,
  fontWeight: 500,
};

const aiFabStyle: CSSProperties = {
  position: "fixed",
  right: 24,
  bottom: 24,
  zIndex: 35,
  width: "min(320px, calc(100vw - 32px))",
  display: "grid",
  justifyItems: "end",
  gap: 10,
  pointerEvents: "none",
};

const aiButtonBaseStyle: CSSProperties = {
  pointerEvents: "auto",
  border: "1px solid rgba(205, 219, 245, 0.95)",
  background: "rgba(255, 255, 255, 0.98)",
  boxShadow: "0 18px 48px rgba(15, 23, 42, 0.12)",
  color: "#173967",
};

const aiDockButtonStyle: CSSProperties = {
  ...aiButtonBaseStyle,
  display: "inline-flex",
  alignItems: "center",
  gap: 10,
  borderRadius: 999,
  padding: "12px 16px",
  fontWeight: 600,
};

const aiPanelStyle: CSSProperties = {
  ...aiButtonBaseStyle,
  width: "100%",
  borderRadius: 20,
  padding: 16,
  display: "grid",
  gap: 14,
};

const iconStyle: CSSProperties = {
  width: 18,
  height: 18,
  flexShrink: 0,
};

function WorkbenchMetric({ label, value }: { label: string; value: string }) {
  return (
    <div style={metricStyle}>
      <span style={metricLabelStyle}>{label}</span>
      <strong style={metricValueStyle}>{value || "未记录"}</strong>
    </div>
  );
}

function WorkbenchFact({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <span style={metricLabelStyle}>{label}</span>
      <strong style={{ fontSize: 13, color: "var(--text-main)", wordBreak: "break-word" }}>{value || "未记录"}</strong>
    </div>
  );
}

function ResultSignal({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const width = max > 0 ? `${Math.max(value > 0 ? 12 : 0, Math.round((value / max) * 100))}%` : "0%";

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12, color: "var(--workspace-ink-soft)" }}>
        <span>{label}</span>
        <strong style={{ color: "var(--text-main)" }}>{value}</strong>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "rgba(148, 163, 184, 0.18)", overflow: "hidden" }}>
        <div style={{ width, height: "100%", borderRadius: 999, background: tone }} />
      </div>
    </div>
  );
}

function WorkflowAiEntryShell({
  currentTask,
  latestRun,
  runtimeSummary,
  resultCount,
  artifactCount,
  onChangeTab,
}: {
  currentTask: Task;
  latestRun: WorkflowRun | null;
  runtimeSummary: string;
  resultCount: number;
  artifactCount: number;
  onChangeTab: (tab: ProjectWorkspaceTab) => void;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const taskBrief = useMemo(
    () =>
      [
        `Task: ${currentTask.title}`,
        `Status: ${currentTask.status}`,
        `Summary: ${currentTask.summary || currentTask.description || "暂无摘要"}`,
        `Latest run: ${latestRun ? `${latestRun.run_id} (${mapWorkflowRunStatus(latestRun.status)})` : "暂无 run"}`,
        `Runtime: ${runtimeSummary}`,
        `Results: ${resultCount}`,
        `Artifacts: ${artifactCount}`,
      ].join("\n"),
    [artifactCount, currentTask.description, currentTask.status, currentTask.summary, currentTask.title, latestRun, resultCount, runtimeSummary]
  );

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(taskBrief);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div style={aiFabStyle} aria-label="task ai entry shell">
      {open ? (
        <section style={aiPanelStyle}>
          <div style={{ display: "grid", gap: 6 }}>
            <span style={hintPillStyle}>
              <SparklesIcon style={iconStyle} />
              AI Entry
            </span>
            <div style={{ display: "grid", gap: 4 }}>
              <strong style={{ color: "var(--text-main)", fontSize: 15 }}>围绕当前任务的 AI 入口壳层</strong>
              <p style={copyStyle}>复制上下文后可直接发给 AI，也可以先跳回 Overview / Runs / Results 继续当前流程。</p>
            </div>
          </div>

          <div style={{ ...subtleCalloutStyle, gap: 6 }}>
            <strong style={{ color: "var(--text-main)", fontSize: 14 }}>{currentTask.title}</strong>
            <p style={copyStyle}>{currentTask.summary || currentTask.description || "当前任务暂无额外摘要。"}</p>
          </div>

          <div style={quickActionRowStyle}>
            <button type="button" className="control-btn control-btn--primary" onClick={() => void handleCopy()}>
              {copied ? (
                <>
                  <CheckIcon style={iconStyle} />
                  已复制上下文
                </>
              ) : (
                <>
                  <ClipboardDocumentIcon style={iconStyle} />
                  复制 AI Brief
                </>
              )}
            </button>
            <button type="button" className="control-btn" onClick={() => onChangeTab("overview")}>
              Overview
            </button>
            <button type="button" className="control-btn" onClick={() => onChangeTab("runs")}>
              Runs
            </button>
            <button type="button" className="control-btn" onClick={() => onChangeTab("results")}>
              Results
            </button>
          </div>

          <button type="button" className="control-btn" onClick={() => setOpen(false)}>
            收起入口
          </button>
        </section>
      ) : null}

      <button type="button" style={aiDockButtonStyle} onClick={() => setOpen((current) => !current)}>
        <SparklesIcon style={iconStyle} />
        {copied ? "AI Brief 已就绪" : "打开 AI 入口"}
      </button>
    </div>
  );
}

export function WorkflowTaskWorkbenchViews({
  currentTask,
  projectWorkspaceTab,
  latestRun,
  runtimeSummary,
  runHeadline,
  runs,
  selectedRunId,
  selectedRun,
  detailBusy,
  artifactsBusy,
  artifactsExpanded,
  detailTab,
  artifacts,
  results,
  resolvedConfig,
  compilePreview,
  artifactSummary,
  traceArtifacts,
  availableArtifacts,
  missingArtifacts,
  chartMax,
  onChangeTab,
  onSelectRun,
  onRefreshRun,
  onRefreshArtifacts,
  onRefreshConfig,
  onToggleArtifactsExpanded,
  onChangeDetailTab,
}: {
  currentTask: Task;
  projectWorkspaceTab: ProjectWorkspaceTab;
  latestRun: WorkflowRun | null;
  runtimeSummary: string;
  runHeadline: string;
  runs: WorkflowRun[];
  selectedRunId: string;
  selectedRun: WorkflowRun | null;
  detailBusy: boolean;
  artifactsBusy: boolean;
  artifactsExpanded: boolean;
  detailTab: "logs" | "artifacts" | "config" | "trace";
  artifacts: WorkflowArtifact[];
  results: WorkflowResult[];
  resolvedConfig: string;
  compilePreview: WorkflowCompilePreview | null;
  artifactSummary: string;
  traceArtifacts: WorkflowArtifact[];
  availableArtifacts: number;
  missingArtifacts: number;
  chartMax: number;
  onChangeTab: (tab: ProjectWorkspaceTab) => void;
  onSelectRun: (runId: string) => void;
  onRefreshRun: () => void;
  onRefreshArtifacts: () => void;
  onRefreshConfig: () => void;
  onToggleArtifactsExpanded: (open: boolean) => void;
  onChangeDetailTab: (tab: "logs" | "artifacts" | "config" | "trace") => void;
}) {
  return (
    <>
      {projectWorkspaceTab === "overview" ? (
        <section style={shellSurfaceStyle}>
          <section className="workflow-console-primary" style={{ gap: 18 }}>
            <WorkspaceSectionHeader
              title="Task Overview"
              description="围绕当前任务的单页简报与下一步动作。保留 task-scoped 流程，同时把信息压回更轻的线性工作台。"
              aside={<span style={hintPillStyle}>{runtimeSummary}</span>}
            />

            <div style={responsiveGridStyle}>
              <section style={softPanelStyle}>
                <div style={keyValueListStyle}>
                  <WorkbenchFact label="Task" value={currentTask.title} />
                  <WorkbenchFact label="Summary" value={currentTask.summary || currentTask.description || "当前任务暂无摘要。"} />
                </div>
                <div style={metricRowStyle}>
                  <WorkbenchMetric label="Task Status" value={currentTask.status} />
                  <WorkbenchMetric label="Latest Run" value={latestRun?.run_id || "暂无"} />
                  <WorkbenchMetric label="Results" value={String(results.length)} />
                  <WorkbenchMetric label="Artifacts" value={`${availableArtifacts}/${availableArtifacts + missingArtifacts}`} />
                </div>
              </section>

              <section style={softPanelStyle}>
                <div style={{ display: "grid", gap: 8 }}>
                  <strong style={{ color: "var(--text-main)", fontSize: 14 }}>下一步</strong>
                  <p style={copyStyle}>保持当前任务上下文不丢失：先组装 workflow，再看 run，再回到结果面板确认输出。</p>
                </div>
                <div style={quickActionRowStyle}>
                  <button type="button" className="control-btn control-btn--primary" onClick={() => onChangeTab("workflow")}>
                    进入 Workflow
                  </button>
                  <button type="button" className="control-btn" onClick={() => onChangeTab("runs")}>
                    查看 Runs
                  </button>
                  <button type="button" className="control-btn" onClick={() => onChangeTab("results")}>
                    查看 Results
                  </button>
                </div>
              </section>
            </div>

            <section style={linearSectionStyle}>
              <WorkspaceSectionHeader title="Task Context" description="保留关键任务事实，减少大卡片和 JSON 负担。" />
              <div style={responsiveGridStyle}>
                <WorkbenchFact label="Task ID" value={currentTask.task_id} />
                <WorkbenchFact label="Execution Count" value={String(currentTask.execution_count)} />
                <WorkbenchFact label="Latest Execution" value={currentTask.latest_execution_id || "暂无"} />
                <WorkbenchFact label="Latest Run Time" value={latestRun ? formatDateTime(latestRun.updated_at || latestRun.created_at) : "暂无"} />
              </div>
            </section>
          </section>
        </section>
      ) : null}

      {projectWorkspaceTab === "runs" ? (
        <section style={shellSurfaceStyle}>
          <section className="workflow-console-primary" style={{ gap: 18 }}>
            <WorkspaceSectionHeader
              title={selectedRun ? "当前 Run" : "Runs"}
              description={runHeadline}
              aside={
                selectedRun ? (
                  <div className="workflow-console-inline-actions">
                    <button type="button" className="control-btn" disabled={detailBusy} onClick={onRefreshRun}>
                      {detailBusy ? "刷新中..." : "刷新 Run"}
                    </button>
                    <button type="button" className="control-btn" disabled={artifactsBusy} onClick={onRefreshArtifacts}>
                      {artifactsBusy ? "同步中..." : "刷新产物"}
                    </button>
                    <button type="button" className="control-btn" onClick={onRefreshConfig}>
                      刷新 Config
                    </button>
                  </div>
                ) : null
              }
            />

            {runs.length > 0 ? (
              <div className="workflow-console-run-strip">
                {runs.map((run) => (
                  <button key={run.run_id} type="button" className={`workflow-console-run-chip${run.run_id === selectedRunId ? " active" : ""}`} onClick={() => onSelectRun(run.run_id)}>
                    <strong>{run.workflow_id || run.run_id}</strong>
                    <span>{mapWorkflowRunStatus(run.status)}</span>
                  </button>
                ))}
              </div>
            ) : null}

            {selectedRun ? (
              <div style={{ display: "grid", gap: 18 }}>
                <div style={metricRowStyle}>
                  <WorkbenchMetric label="Run ID" value={selectedRun.run_id} />
                  <WorkbenchMetric label="Profile" value={selectedRun.profile_id} />
                  <WorkbenchMetric label="Backend" value={selectedRun.backend_kind || selectedRun.executor || "未记录"} />
                  <WorkbenchMetric label="Updated" value={formatDateTime(selectedRun.updated_at || selectedRun.created_at)} />
                </div>

                <section style={subtleCalloutStyle}>
                  <strong style={{ color: "var(--text-main)", fontSize: 14 }}>{selectedRun.message || "Run 已提交，等待更多状态。"}</strong>
                  <p style={copyStyle}>{artifactSummary}</p>
                </section>

                <div style={responsiveGridStyle}>
                  <section style={softPanelStyle}>
                    <WorkspaceSectionHeader title="Runtime Snapshot" description="保留关键运行面与路径信息，不再把它们压进重卡片。" />
                    <div style={keyValueListStyle}>
                      <WorkbenchFact label="Packaging" value={selectedRun.packaging_mode || "未记录"} />
                      <WorkbenchFact label="Container" value={selectedRun.container_runtime || "未记录"} />
                      <WorkbenchFact label="Launcher PID" value={selectedRun.launcher_pid || "未记录"} />
                      <WorkbenchFact label="Nextflow PID" value={selectedRun.nextflow_pid || readWorkflowRemoteValue(selectedRun, "nextflow_pid") || "未记录"} />
                      <WorkbenchFact label="Heartbeat" value={readWorkflowRemoteValue(selectedRun, "heartbeat") || "等待 heartbeat"} />
                    </div>
                  </section>

                  <section style={softPanelStyle}>
                    <WorkspaceSectionHeader title="Paths" description="远端 / 本地路径保持可见，方便排障与追踪。" />
                    <div style={keyValueListStyle}>
                      <WorkbenchFact label="Bundle" value={selectedRun.local_bundle_dir || selectedRun.remote_bundle_dir || "未记录"} />
                      <WorkbenchFact label="Task Dir" value={selectedRun.remote_task_dir || selectedRun.local_run_dir || "未记录"} />
                      <WorkbenchFact label="Work Dir" value={selectedRun.remote_work_dir || "未记录"} />
                      <WorkbenchFact label="Output Dir" value={selectedRun.remote_output_dir || "未记录"} />
                    </div>
                  </section>
                </div>

                <section style={linearSectionStyle}>
                  <WorkspaceSectionHeader
                    title="Recent Log"
                    description={readWorkflowRemoteValue(selectedRun, "heartbeat") ? `heartbeat: ${readWorkflowRemoteValue(selectedRun, "heartbeat")}` : "等待 heartbeat"}
                  />
                  <pre className="workspace-json-surface">{readWorkflowRemoteValue(selectedRun, "log_tail") || "暂无日志"}</pre>
                </section>
              </div>
            ) : (
              <WorkspaceEmptyState mark="Run" label="当前还没有 Run" hint="从 Workflow tab 保存并提交一个新的 workflow run。" compact />
            )}
          </section>

          <details className="workflow-console-section" open={artifactsExpanded} onToggle={(event) => onToggleArtifactsExpanded(event.currentTarget.open)}>
            <summary className="workflow-console-section-summary">
              <div>
                <strong>Run Drawer</strong>
                <span>logs / resolved config / results / trace</span>
              </div>
              <span>{selectedRun ? detailTab : "等待 Run"}</span>
            </summary>

            <div className="workflow-detail-tabs">
              {[
                ["logs", "Logs"],
                ["artifacts", "Results"],
                ["config", "Resolved Config"],
                ["trace", "Trace"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`workflow-detail-tab${detailTab === key ? " active" : ""}`}
                  onClick={() => onChangeDetailTab(key as "logs" | "artifacts" | "config" | "trace")}
                >
                  {label}
                </button>
              ))}
            </div>

            {detailTab === "logs" ? (
              selectedRun ? (
                <div className="workflow-console-log">
                  <div className="workflow-console-log-head">
                    <strong>最近日志</strong>
                    <span>{readWorkflowRemoteValue(selectedRun, "heartbeat") ? `heartbeat: ${readWorkflowRemoteValue(selectedRun, "heartbeat")}` : "等待 heartbeat"}</span>
                  </div>
                  <pre className="workspace-json-surface">{readWorkflowRemoteValue(selectedRun, "log_tail") || "暂无日志"}</pre>
                </div>
              ) : (
                <WorkspaceEmptyState mark="Log" label="选择一个 Run 后查看日志" compact />
              )
            ) : null}

            {detailTab === "artifacts" ? (
              selectedRun ? (
                artifacts.length > 0 ? (
                  <div className="workflow-artifact-list">
                    {artifacts.map((artifact) => (
                      <div key={artifact.name} className="workflow-artifact-item">
                        <div className="workflow-artifact-copy">
                          <strong>{artifact.name}</strong>
                          <p>
                            {[artifact.kind || artifact.artifact_type, artifact.viewer_hint, artifact.available ? artifact.local_path || artifact.remote_path : artifact.error || "未找到远端文件"]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        </div>
                        <span className={`workflow-artifact-state${artifact.available ? " available" : ""}`}>{artifact.available ? "已同步" : "缺失"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <WorkspaceEmptyState mark="Art" label="当前 run 还没有可见产物" hint="先刷新状态；如果仍为空，请确认远端 run 已生成 report、timeline、trace 或 dag。" compact />
                )
              ) : (
                <WorkspaceEmptyState mark="Art" label="选择一个 Run 后查看产物" compact />
              )
            ) : null}

            {detailTab === "config" ? (
              selectedRun ? (
                <pre className="workspace-json-surface">{resolvedConfig || compilePreview?.files["resolved.config"] || "{}"}</pre>
              ) : (
                <WorkspaceEmptyState mark="Cfg" label="选择一个 Run 后查看 resolved config" compact />
              )
            ) : null}

            {detailTab === "trace" ? (
              selectedRun ? (
                traceArtifacts.length > 0 ? (
                  <div className="workflow-artifact-list">
                    {traceArtifacts.map((artifact) => (
                      <div key={artifact.name} className="workflow-artifact-item">
                        <div className="workflow-artifact-copy">
                          <strong>{artifact.name}</strong>
                          <p>{artifact.available ? artifact.local_path || artifact.remote_path : artifact.error || "未找到 trace/report 文件"}</p>
                        </div>
                        <span className={`workflow-artifact-state${artifact.available ? " available" : ""}`}>{artifact.available ? "可查看" : "缺失"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <WorkspaceEmptyState mark="Tr" label="当前 run 还没有 trace / timeline / report / dag 产物" compact />
                )
              ) : (
                <WorkspaceEmptyState mark="Tr" label="选择一个 Run 后查看 trace 相关产物" compact />
              )
            ) : null}
          </details>
        </section>
      ) : null}

      {projectWorkspaceTab === "results" ? (
        <section style={shellSurfaceStyle}>
          <section className="workflow-console-primary" style={{ gap: 18 }}>
            <WorkspaceSectionHeader title="Results" description="结果摘要保持在线性工作台里：先看信号，再看最新结果，再看产物列表。" />

            <section style={responsiveGridStyle}>
              <div style={softPanelStyle}>
                <strong style={{ color: "var(--text-main)", fontSize: 14 }}>Result Signals</strong>
                <ResultSignal label="Results" value={results.length} max={chartMax} tone="#2563eb" />
                <ResultSignal label="Available Artifacts" value={availableArtifacts} max={chartMax} tone="#15803d" />
                <ResultSignal label="Missing Artifacts" value={missingArtifacts} max={chartMax} tone="#dc2626" />
              </div>

              <div style={softPanelStyle}>
                <strong style={{ color: "var(--text-main)", fontSize: 14 }}>Latest Result</strong>
                {results[0] ? (
                  <div style={keyValueListStyle}>
                    <WorkbenchFact label="Result ID" value={results[0].result_id} />
                    <WorkbenchFact label="Run ID" value={results[0].run_id} />
                    <WorkbenchFact label="Viewer" value={results[0].viewer_kind || "未记录"} />
                    <WorkbenchFact label="Content" value={results[0].content_type || results[0].kind} />
                  </div>
                ) : (
                  <p style={copyStyle}>当前任务还没有最新结果；先运行任务，再回到 Results 查看输出。</p>
                )}
              </div>
            </section>

            <section style={linearSectionStyle}>
              <WorkspaceSectionHeader title="Published Results" description="保留结果清单，但使用更轻的列表布局。" />
              <div className="workflow-artifact-list">
                {results.length > 0 ? (
                  results.map((result) => (
                    <div key={result.result_id} className="workflow-artifact-item">
                      <div className="workflow-artifact-copy">
                        <strong>{result.kind}</strong>
                        <p>{[result.viewer_kind, result.content_type, result.run_id, formatDateTime(result.updated_at || result.created_at)].filter(Boolean).join(" · ")}</p>
                      </div>
                      <span className="workflow-artifact-state available">Result</span>
                    </div>
                  ))
                ) : (
                  <WorkspaceEmptyState mark="Res" label="当前任务还没有结果摘要" hint="先运行任务，再回到 Results tab 查看产物和图表。" compact />
                )}
              </div>
            </section>
          </section>
        </section>
      ) : null}

      <WorkflowAiEntryShell
        currentTask={currentTask}
        latestRun={latestRun}
        runtimeSummary={runtimeSummary}
        resultCount={results.length}
        artifactCount={availableArtifacts}
        onChangeTab={onChangeTab}
      />
    </>
  );
}
