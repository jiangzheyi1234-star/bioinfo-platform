"use client";

import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { WorkflowEdgeListEditor } from "./workflow_edge_list_editor";
import { WorkflowGraphEditor } from "./workflow_graph_editor";
import { WorkflowNodeListEditor } from "./workflow_node_list_editor";
import { WorkflowTaskWorkbenchViews } from "./workflow_task_workbench_views";
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
        {projectWorkspaceTab === "workflow" ? (
          <>
            <section className="workflow-console-primary workflow-console-primary--graph">
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
                  <strong>Workflow controls</strong>
                  <span>保持 DAG 为主视图；仅在需要时展开 schema、参数与兼容性设置。</span>
                </div>
                <span>{workflow ? `${workflow.nodes.length} steps` : "等待 workflow 初始化"}</span>
              </summary>
              <div className="workflow-panel-grid">
                <div className="workflow-panel-stack">
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

                <div className="workflow-panel-stack workflow-panel-stack--supporting">
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

                  <details className="workflow-drawer-panel" open>
                    <summary className="workflow-drawer-summary">
                      <div>
                        <strong>Workflow draft</strong>
                        <span>名称与 schema 保持近手边，但不再长期占据主画布。</span>
                      </div>
                    </summary>
                    <div className="workflow-drawer-content">
                      <label className="control-field">
                        <span>Workflow 名称</span>
                        <input
                          className="control-input"
                          value={workflow?.name || ""}
                          onChange={(event) => setWorkflow((current) => (current ? { ...current, name: event.target.value } : current))}
                          placeholder="New Workflow"
                        />
                      </label>

                      <label className="control-field">
                        <span>Params Schema</span>
                        <textarea className="control-textarea workflow-schema-textarea" value={schemaDraft} onChange={(event) => setSchemaDraft(event.target.value)} spellCheck={false} />
                      </label>
                    </div>
                  </details>

                  <details className="workflow-drawer-panel">
                    <summary className="workflow-drawer-summary">
                      <div>
                        <strong>Launch parameters</strong>
                        <span>{launchProfile?.profile_id || "未选定 profile"}</span>
                      </div>
                      <span>{schemaSummary.fields.length} fields</span>
                    </summary>
                    <div className="workflow-drawer-content workflow-param-panel">
                      {schemaSummary.unsupported.length > 0 ? <p className="workflow-panel-error">以下字段类型暂不支持表单渲染：{schemaSummary.unsupported.join(", ")}</p> : null}
                      {schemaSummary.fields.length === 0 ? <p className="workflow-console-inline-note">保存 workflow 后即可根据 schema 渲染参数表单。</p> : null}
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
                  </details>

                  <details className="workflow-drawer-panel">
                    <summary className="workflow-drawer-summary">
                      <div>
                        <strong>Profile compatibility</strong>
                        <span>{compatibilitySummary.selection_reason}</span>
                      </div>
                      <span>{compatibilitySummary.workflow_profiles.length} profiles</span>
                    </summary>
                    <div className="workflow-drawer-content workflow-param-panel">
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
                  </details>
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

        <WorkflowTaskWorkbenchViews
          currentTask={currentTask}
          projectWorkspaceTab={projectWorkspaceTab}
          latestRun={latestRun}
          runtimeSummary={runtimeSummary}
          runHeadline={runHeadline}
          runs={runs}
          selectedRunId={selectedRunId}
          selectedRun={selectedRun}
          detailBusy={detailBusy}
          artifactsBusy={artifactsBusy}
          artifactsExpanded={artifactsExpanded}
          detailTab={detailTab}
          artifacts={artifacts}
          results={results}
          resolvedConfig={resolvedConfig}
          compilePreview={compilePreview}
          artifactSummary={artifactSummary}
          traceArtifacts={traceArtifacts}
          availableArtifacts={availableArtifacts}
          missingArtifacts={missingArtifacts}
          chartMax={chartMax}
          onChangeTab={setProjectWorkspaceTab}
          onSelectRun={(runId) => {
            setSelectedRunId(runId);
            router.replace(`/workspace?run_id=${encodeURIComponent(runId)}`);
          }}
          onRefreshRun={() => void (selectedRun ? refreshRunDetail(selectedRun.run_id) : Promise.resolve())}
          onRefreshArtifacts={() => void (selectedRun ? fetchArtifacts(selectedRun.run_id) : Promise.resolve())}
          onRefreshConfig={fetchResolvedConfig}
          onToggleArtifactsExpanded={setArtifactsExpanded}
          onChangeDetailTab={setDetailTab}
        />
      </section>
    </div>
  );
}
