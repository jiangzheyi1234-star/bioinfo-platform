"use client";

import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { WorkflowEdgeListEditor } from "./workflow_edge_list_editor";
import { WorkflowGraphEditor } from "./workflow_graph_editor";
import { WorkflowNodeListEditor } from "./workflow_node_list_editor";
import { formatDateTime, mapWorkflowRunStatus, normalizeFieldValue } from "./workflow_support";
import { describeRuntimeReadiness, readWorkflowRemoteValue, useWorkflowConsoleState } from "./workflow_console_state";

function TechnicalItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="workflow-console-stat">
      <span>{label}</span>
      <strong>{value || "未记录"}</strong>
    </div>
  );
}

function WorkbenchTabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`workflow-detail-tab${active ? " active" : ""}`} onClick={onClick}>
      {label}
    </button>
  );
}

function ResultChartBar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const width = max > 0 ? `${Math.max(12, Math.round((value / max) * 100))}%` : "0%";
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12, color: "#475569" }}>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "rgba(148, 163, 184, 0.18)", overflow: "hidden" }}>
        <div style={{ width, height: "100%", background: tone, borderRadius: 999 }} />
      </div>
    </div>
  );
}

export function WorkflowConsolePage() {
  const {
    currentProject,
    currentProjectId,
    currentTask,
    projectWorkspaceTab,
    workflow,
    schemaDraft,
    params,
    compatibilityError,
    compatibilityBusy,
    compilePreview,
    saveBusy,
    compileBusy,
    runBusy,
    workflowMessage,
    runs,
    selectedRunId,
    selectedRun,
    detailBusy,
    actionBusy,
    artifacts,
    results,
    resolvedConfig,
    artifactsBusy,
    workflowExpanded,
    artifactsExpanded,
    technicalExpanded,
    selectedNodeId,
    selectedNode,
    detailTab,
    schemaSummary,
    compatibilitySummary,
    launchProfile,
    artifactSummary,
    traceArtifacts,
    router,
    setWorkflow,
    setProjectWorkspaceTab,
    setSchemaDraft,
    setParams,
    setSelectedRunId,
    setWorkflowExpanded,
    setArtifactsExpanded,
    setTechnicalExpanded,
    setSelectedNodeId,
    setDetailTab,
    refreshRuns,
    refreshRunDetail,
    fetchArtifacts,
    fetchResolvedConfig,
    cancelRun,
    updateNode,
    updateNodePosition,
    addNode,
    removeNode,
    updateEdge,
    connectNodes,
    removeEdge,
    runCompile,
    saveWorkflow,
    submitRun,
  } = useWorkflowConsoleState();

  if (!currentProjectId || !currentProject) {
    return <WorkspaceEmptyState mark="WF" label="先选择一个项目" hint="工作台会围绕当前任务展开。" />;
  }

  if (!currentTask) {
    return <WorkspaceEmptyState mark="Task" label="先选择一个任务" hint="从左侧 Project → Task 树中选择任务，进入 Task Workbench。" />;
  }

  const runtimeSummary = describeRuntimeReadiness(compatibilitySummary, compatibilityError);
  const latestRun = runs[0] || null;
  const nodeCount = workflow?.nodes.length || 0;
  const edgeCount = workflow?.edges.length || 0;
  const availableArtifacts = artifacts.filter((item) => item.available).length;
  const missingArtifacts = artifacts.length - availableArtifacts;
  const chartMax = Math.max(results.length, availableArtifacts, missingArtifacts, 1);
  const runHeadline = selectedRun
    ? `${mapWorkflowRunStatus(selectedRun.status)} · ${formatDateTime(selectedRun.updated_at || selectedRun.created_at)}`
    : "当前任务还没有 workflow run。";

  return (
    <div className="project-workspace-content">
      <WorkspaceSectionHeader
        title={currentTask.title}
        description={currentTask.summary || "围绕当前任务完成组装 Workflow、保存、编译、运行与结果查看。"}
        aside={
          <div className="workflow-console-topbar">
            <span className="workflow-console-inline-note">{runtimeSummary}</span>
            <button type="button" className="control-btn" onClick={() => void refreshRuns(selectedRunId)}>
              刷新任务
            </button>
            {(projectWorkspaceTab === "workflow" || projectWorkspaceTab === "runs") && (
              <button type="button" className="control-btn control-btn--primary" onClick={() => setWorkflowExpanded(true)}>
                新建 Run
              </button>
            )}
            {projectWorkspaceTab === "runs" && selectedRun ? (
              <button
                type="button"
                className="control-btn"
                disabled={actionBusy === selectedRun.run_id || ["completed", "failed", "cancelled"].includes(selectedRun.status)}
                onClick={() => void cancelRun(selectedRun.run_id)}
              >
                {actionBusy === selectedRun.run_id ? "取消中..." : "取消 Run"}
              </button>
            ) : null}
          </div>
        }
      />

      <div className="workflow-detail-tabs" style={{ marginBottom: 16 }}>
        <WorkbenchTabButton active={projectWorkspaceTab === "overview"} label="Overview" onClick={() => setProjectWorkspaceTab("overview")} />
        <WorkbenchTabButton active={projectWorkspaceTab === "workflow"} label="Workflow" onClick={() => setProjectWorkspaceTab("workflow")} />
        <WorkbenchTabButton active={projectWorkspaceTab === "runs"} label="Runs" onClick={() => setProjectWorkspaceTab("runs")} />
        <WorkbenchTabButton active={projectWorkspaceTab === "results"} label="Results" onClick={() => setProjectWorkspaceTab("results")} />
      </div>

      <section className="workflow-console-shell">
        {projectWorkspaceTab === "overview" ? (
          <section className="workflow-console-primary">
            <WorkspaceSectionHeader title="Task Overview" description="围绕 happy path 的任务总览与下一步引导。" />
            <div className="workflow-console-stat-row">
              <TechnicalItem label="Task Status" value={currentTask.status} />
              <TechnicalItem label="Latest Run" value={latestRun?.run_id || "暂无"} />
              <TechnicalItem label="Results" value={String(results.length)} />
              <TechnicalItem label="Runtime Ready" value={compatibilitySummary.preflight?.ok ? "已就绪" : compatibilityError ? "待修复" : "待检测"} />
            </div>
            <div className="workflow-preview-grid">
              <div className="workflow-preview-card">
                <strong>当前任务摘要</strong>
                <pre className="workspace-json-surface">
                  {JSON.stringify(
                    {
                      task_id: currentTask.task_id,
                      title: currentTask.title,
                      status: currentTask.status,
                      summary: currentTask.summary,
                      execution_count: currentTask.execution_count,
                      latest_execution_id: currentTask.latest_execution_id,
                    },
                    null,
                    2
                  )}
                </pre>
              </div>
              <div className="workflow-preview-card">
                <strong>下一步</strong>
                <div style={{ display: "grid", gap: 10 }}>
                  <button type="button" className="control-btn control-btn--primary" onClick={() => setProjectWorkspaceTab("workflow")}>
                    进入 Workflow 组装 / 保存
                  </button>
                  <button type="button" className="control-btn" onClick={() => setProjectWorkspaceTab("runs")}>
                    查看 Runs
                  </button>
                  <button type="button" className="control-btn" onClick={() => setProjectWorkspaceTab("results")}>
                    查看 Results
                  </button>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {projectWorkspaceTab === "workflow" ? (
          <>
            <section className="workflow-console-primary">
              <WorkspaceSectionHeader
                title="DAG Overview"
                description="组装 Workflow、保存、编译，并为后续运行准备 task workflow snapshot。"
                aside={
                  <div className="workflow-console-inline-note">
                    {nodeCount} nodes · {edgeCount} edges{selectedNode ? ` · selected ${selectedNode.label}` : ""}
                  </div>
                }
              />
              <WorkflowGraphEditor
                workflow={workflow}
                selectedRun={selectedRun}
                compilePreview={compilePreview}
                artifacts={artifacts}
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                onConnectNodes={connectNodes}
                onPersistNodePosition={updateNodePosition}
                onDeleteEdge={removeEdge}
              />
            </section>

            <details className="workflow-console-section" open={workflowExpanded} onToggle={(event) => setWorkflowExpanded(event.currentTarget.open)}>
              <summary className="workflow-console-section-summary">
                <div>
                  <strong>Workflow 规格</strong>
                  <span>编辑 DAG、参数 schema，并保存/编译/提交运行。</span>
                </div>
                <span>{workflow ? `${workflow.nodes.length} steps` : "等待 workflow 初始化"}</span>
              </summary>
              <div className="workflow-panel-grid">
                <div className="workflow-panel-stack">
                  <label className="control-field">
                    <span>Workflow 名称</span>
                    <input
                      className="control-input"
                      value={workflow?.name || ""}
                      onChange={(event) => setWorkflow((current) => (current ? { ...current, name: event.target.value } : current))}
                      placeholder="New Workflow"
                    />
                  </label>

                  <WorkflowNodeListEditor
                    workflow={workflow}
                    selectedNodeId={selectedNodeId}
                    onSelectNode={setSelectedNodeId}
                    onAddNode={addNode}
                    onUpdateNode={updateNode}
                    onRemoveNode={removeNode}
                  />
                  <WorkflowEdgeListEditor workflow={workflow} onUpdateEdge={updateEdge} onRemoveEdge={removeEdge} />
                </div>

                <div className="workflow-panel-stack">
                  <label className="control-field">
                    <span>Params Schema</span>
                    <textarea className="control-textarea workflow-schema-textarea" value={schemaDraft} onChange={(event) => setSchemaDraft(event.target.value)} spellCheck={false} />
                  </label>

                  <div className="workflow-param-panel">
                    <div className="workflow-node-list-head">
                      <strong>参数面板</strong>
                      <span className="muted">{launchProfile?.profile_id || "未选定 profile"}</span>
                    </div>
                    {schemaSummary.unsupported.length > 0 ? <p className="workflow-panel-error">以下字段类型暂不支持表单渲染：{schemaSummary.unsupported.join(", ")}</p> : null}
                    {schemaSummary.fields.map((field) => (
                      <label key={field.key} className="control-field">
                        <span>
                          {field.label}
                          {field.required ? " *" : ""}
                        </span>
                        {field.enumValues.length > 0 ? (
                          <select
                            className="control-select"
                            value={String(params[field.key] ?? field.defaultValue)}
                            onChange={(event) => setParams((current) => ({ ...current, [field.key]: normalizeFieldValue(field.kind, event.target.value) }))}
                          >
                            {field.enumValues.map((item) => (
                              <option key={item} value={item}>
                                {item}
                              </option>
                            ))}
                          </select>
                        ) : field.kind === "boolean" ? (
                          <label className="control-checkbox">
                            <input
                              type="checkbox"
                              checked={Boolean(params[field.key])}
                              onChange={(event) => setParams((current) => ({ ...current, [field.key]: event.target.checked }))}
                            />
                            <span>{field.description || "布尔参数"}</span>
                          </label>
                        ) : (
                          <input
                            className="control-input"
                            type={field.kind === "string" ? "text" : "number"}
                            value={String(params[field.key] ?? field.defaultValue)}
                            onChange={(event) => setParams((current) => ({ ...current, [field.key]: normalizeFieldValue(field.kind, event.target.value) }))}
                          />
                        )}
                        {field.description ? <small className="muted">{field.description}</small> : null}
                      </label>
                    ))}
                  </div>

                  <div className="workflow-param-panel">
                    <div className="workflow-node-list-head">
                      <strong>Profile 兼容性</strong>
                      <span className="muted">{compatibilitySummary.selection_reason}</span>
                    </div>
                    {compatibilityBusy ? <p className="workflow-console-inline-note">正在同步后端兼容性…</p> : null}
                    <div className="workflow-compatibility-grid">
                      <div>
                        <strong>服务器可用</strong>
                        <ul className="workflow-compatibility-list">
                          {compatibilitySummary.server_profiles.map((item) => (
                            <li key={`server-${item.profile.profile_id}`}>
                              <span>{item.profile.profile_id}</span>
                              <small className="muted">
                                {item.profile.executor} / {item.profile.packaging_mode}
                              </small>
                            </li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <strong>当前 workflow 可用</strong>
                        <ul className="workflow-compatibility-list">
                          {compatibilitySummary.workflow_profiles.map((item) => (
                            <li key={`workflow-${item.profile.profile_id}`}>
                              <span>
                                {item.profile.profile_id} {item.compatible_with_workflow ? "✅" : "❌"}
                              </span>
                              <small className="muted">{item.support_level}</small>
                              {item.incompatibility_reasons.length > 0 ? <small className="workflow-panel-error">{item.incompatibility_reasons.join("；")}</small> : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>

                  <div className="workflow-action-row">
                    <button type="button" className="control-btn" disabled={saveBusy || compatibilityBusy} onClick={() => void saveWorkflow()}>
                      {saveBusy ? "保存中..." : "保存 Workflow"}
                    </button>
                    <button type="button" className="control-btn" disabled={compileBusy || compatibilityBusy} onClick={() => void runCompile()}>
                      {compileBusy ? "编译中..." : "保存并编译"}
                    </button>
                    <button type="button" className="control-btn control-btn--primary" disabled={runBusy || compatibilityBusy} onClick={() => void submitRun()}>
                      {runBusy ? "提交中..." : "保存并运行"}
                    </button>
                  </div>
                  {workflowMessage ? <p className="workflow-console-inline-note">{workflowMessage}</p> : null}
                </div>
              </div>
            </details>

            <details className="workflow-console-section" open={technicalExpanded} onToggle={(event) => setTechnicalExpanded(event.currentTarget.open)}>
              <summary className="workflow-console-section-summary">
                <div>
                  <strong>技术详情</strong>
                  <span>Compile preview、runtime 状态、路径与结果摘要。</span>
                </div>
              </summary>
              <div className="workflow-preview-grid">
                <div className="workflow-preview-card">
                  <strong>Compile Preview</strong>
                  <div className="workflow-console-stat-row">
                    <TechnicalItem label="Bundle" value={compilePreview?.bundle_id || ""} />
                    <TechnicalItem label="文件数" value={String(Object.keys(compilePreview?.files || {}).length)} />
                  </div>
                  <pre className="workspace-json-surface">{compilePreview?.files["main.nf"]?.split("\n").slice(0, 24).join("\n") || "{}"}</pre>
                </div>
                <div className="workflow-preview-card">
                  <strong>Manifest</strong>
                  <div className="workflow-console-stat-row">
                    <TechnicalItem label="Manifest Keys" value={String(Object.keys(compilePreview?.manifest || {}).length)} />
                    <TechnicalItem label="Results" value={String(results.length)} />
                  </div>
                  <pre className="workspace-json-surface">{JSON.stringify(compilePreview?.manifest || {}, null, 2)}</pre>
                </div>
                <div className="workflow-preview-card">
                  <strong>Resolved Config</strong>
                  <pre className="workspace-json-surface">{resolvedConfig || compilePreview?.files["resolved.config"] || "{}"}</pre>
                </div>
                <div className="workflow-preview-card">
                  <strong>Run Detail</strong>
                  {selectedRun ? (
                    <>
                      <div className="workflow-console-stat-row">
                        <TechnicalItem label="Backend" value={selectedRun.backend_kind || selectedRun.executor || ""} />
                        <TechnicalItem label="Packaging" value={selectedRun.packaging_mode || ""} />
                        <TechnicalItem label="Container" value={selectedRun.container_runtime || ""} />
                      </div>
                      <div className="workflow-console-stat-row">
                        <TechnicalItem label="Launcher PID" value={selectedRun.launcher_pid || ""} />
                        <TechnicalItem label="Nextflow PID" value={selectedRun.nextflow_pid || readWorkflowRemoteValue(selectedRun, "nextflow_pid") || ""} />
                        <TechnicalItem label="Heartbeat" value={readWorkflowRemoteValue(selectedRun, "heartbeat")} />
                      </div>
                      <pre className="workspace-json-surface">
                        {JSON.stringify(
                          {
                            local_bundle_dir: selectedRun.local_bundle_dir || "",
                            local_run_dir: selectedRun.local_run_dir || "",
                            remote_bundle_dir: selectedRun.remote_bundle_dir || "",
                            remote_task_dir: selectedRun.remote_task_dir || "",
                            remote_work_dir: selectedRun.remote_work_dir || "",
                            remote_output_dir: selectedRun.remote_output_dir || "",
                            resolved_config_path: selectedRun.resolved_config_path || "",
                            remote_status: selectedRun.remote_status || {},
                          },
                          null,
                          2
                        )}
                      </pre>
                    </>
                  ) : (
                    <pre className="workspace-json-surface">{JSON.stringify({}, null, 2)}</pre>
                  )}
                </div>
              </div>
            </details>
          </>
        ) : null}

        {projectWorkspaceTab === "runs" ? (
          <>
            <section className="workflow-console-primary">
              <WorkspaceSectionHeader
                title={selectedRun ? "当前 Run" : "Runs"}
                description={runHeadline}
                aside={
                  selectedRun ? (
                    <div className="workflow-console-inline-actions">
                      <button type="button" className="control-btn" disabled={detailBusy} onClick={() => void refreshRunDetail(selectedRun.run_id)}>
                        {detailBusy ? "刷新中..." : "刷新 Run"}
                      </button>
                      <button type="button" className="control-btn" disabled={artifactsBusy} onClick={() => void fetchArtifacts(selectedRun.run_id)}>
                        {artifactsBusy ? "同步中..." : "刷新产物"}
                      </button>
                      <button type="button" className="control-btn" onClick={fetchResolvedConfig}>
                        刷新 Config
                      </button>
                    </div>
                  ) : null
                }
              />

              {runs.length > 0 ? (
                <div className="workflow-console-run-strip">
                  {runs.map((run) => (
                    <button
                      key={run.run_id}
                      type="button"
                      className={`workflow-console-run-chip${run.run_id === selectedRunId ? " active" : ""}`}
                      onClick={() => {
                        setSelectedRunId(run.run_id);
                        router.replace(`/workspace?run_id=${encodeURIComponent(run.run_id)}`);
                      }}
                    >
                      <strong>{run.workflow_id || run.run_id}</strong>
                      <span>{mapWorkflowRunStatus(run.status)}</span>
                    </button>
                  ))}
                </div>
              ) : null}

              {selectedRun ? (
                <div className="workflow-console-run-panel">
                  <div className="workflow-console-stat-row">
                    <TechnicalItem label="Run ID" value={selectedRun.run_id} />
                    <TechnicalItem label="Profile" value={selectedRun.profile_id} />
                    <TechnicalItem label="Backend" value={selectedRun.backend_kind || selectedRun.executor || ""} />
                    <TechnicalItem label="Bundle" value={selectedRun.bundle_id || ""} />
                    <TechnicalItem label="更新时间" value={formatDateTime(selectedRun.updated_at || selectedRun.created_at)} />
                  </div>

                  <div className="workflow-console-callout">
                    <strong>{selectedRun.message || "Run 已提交，等待更多状态。"}</strong>
                    <p>{artifactSummary}</p>
                  </div>

                  <div className="workflow-console-log">
                    <div className="workflow-console-log-head">
                      <strong>最近日志</strong>
                      <span>{readWorkflowRemoteValue(selectedRun, "heartbeat") ? `heartbeat: ${readWorkflowRemoteValue(selectedRun, "heartbeat")}` : "等待 heartbeat"}</span>
                    </div>
                    <pre className="workspace-json-surface">{readWorkflowRemoteValue(selectedRun, "log_tail") || "暂无日志"}</pre>
                  </div>
                </div>
              ) : (
                <WorkspaceEmptyState mark="Run" label="当前还没有 Run" hint="从 Workflow tab 保存并提交一个新的 workflow run。" compact />
              )}
            </section>

            <details className="workflow-console-section" open={artifactsExpanded} onToggle={(event) => setArtifactsExpanded(event.currentTarget.open)}>
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
                    onClick={() => setDetailTab(key as "logs" | "artifacts" | "config" | "trace")}
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
          </>
        ) : null}

        {projectWorkspaceTab === "results" ? (
          <section className="workflow-console-primary">
            <WorkspaceSectionHeader title="Results" description="结果展示与最小图表闭环。" />
            <div className="workflow-preview-grid">
              <div className="workflow-preview-card">
                <strong>Result Summary</strong>
                <div style={{ display: "grid", gap: 12 }}>
                  <ResultChartBar label="Results" value={results.length} max={chartMax} tone="#2563eb" />
                  <ResultChartBar label="Available Artifacts" value={availableArtifacts} max={chartMax} tone="#15803d" />
                  <ResultChartBar label="Missing Artifacts" value={missingArtifacts} max={chartMax} tone="#dc2626" />
                </div>
              </div>
              <div className="workflow-preview-card">
                <strong>Latest Result</strong>
                <pre className="workspace-json-surface">
                  {JSON.stringify(
                    results[0]
                      ? {
                          result_id: results[0].result_id,
                          run_id: results[0].run_id,
                          kind: results[0].kind,
                          viewer_kind: results[0].viewer_kind,
                          content_type: results[0].content_type,
                          content_url: results[0].content_url,
                        }
                      : {},
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>
            <div className="workflow-artifact-list">
              {results.length > 0 ? (
                results.map((result) => (
                  <div key={result.result_id} className="workflow-artifact-item">
                    <div className="workflow-artifact-copy">
                      <strong>{result.kind}</strong>
                      <p>{[result.viewer_kind, result.content_type, result.run_id].filter(Boolean).join(" · ")}</p>
                    </div>
                    <span className="workflow-artifact-state available">Result</span>
                  </div>
                ))
              ) : (
                <WorkspaceEmptyState mark="Res" label="当前任务还没有结果摘要" hint="先运行任务，再回到 Results tab 查看产物和图表。" compact />
              )}
            </div>
          </section>
        ) : null}
      </section>
    </div>
  );
}
