"use client";

import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { formatDateTime, mapWorkflowRunStatus, normalizeFieldValue } from "./workflow_support";
import { describeDoctor, readWorkflowRemoteValue, useWorkflowConsoleState } from "./workflow_console_state";

export function WorkflowConsolePage() {
  const {
    currentProject,
    currentProjectId,
    workflow,
    schemaDraft,
    params,
    doctor,
    doctorError,
    compilePreview,
    compileBusy,
    runBusy,
    workflowMessage,
    runs,
    selectedRunId,
    selectedRun,
    detailBusy,
    actionBusy,
    artifacts,
    resolvedConfig,
    artifactsBusy,
    workflowExpanded,
    artifactsExpanded,
    technicalExpanded,
    schemaSummary,
    launchProfile,
    artifactSummary,
    router,
    setWorkflow,
    setSchemaDraft,
    setParams,
    setSelectedRunId,
    setWorkflowExpanded,
    setArtifactsExpanded,
    setTechnicalExpanded,
    refreshRuns,
    refreshRunDetail,
    fetchArtifacts,
    fetchResolvedConfig,
    cancelRun,
    updateNode,
    addNode,
    removeNode,
    runCompile,
    submitRun,
  } = useWorkflowConsoleState();

  if (!currentProjectId || !currentProject) {
    return <WorkspaceEmptyState mark="WF" label="先选择一个项目" hint="工作台会围绕当前项目的 workflow run 展开。" />;
  }

  const doctorSummary = describeDoctor(doctor, doctorError);
  const runHeadline = selectedRun
    ? `${mapWorkflowRunStatus(selectedRun.status)} · ${formatDateTime(selectedRun.updated_at || selectedRun.created_at)}`
    : "当前项目还没有 workflow run。";

  return (
    <div className="project-workspace-content">
      <WorkspaceSectionHeader
        title="工作台"
        description={selectedRun ? `当前焦点：${selectedRun.workflow_id || selectedRun.run_id}` : "围绕当前项目的 workflow run 进行编译、提交、监控和收集产物。"}
        aside={
          <div className="workflow-console-topbar">
            <span className="workflow-console-inline-note">{doctorSummary}</span>
            <button type="button" className="control-btn" onClick={() => void refreshRuns(selectedRunId)}>
              刷新状态
            </button>
            <button type="button" className="control-btn control-btn--primary" onClick={() => setWorkflowExpanded(true)}>
              新建 Run
            </button>
            {selectedRun ? (
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

      <section className="workflow-console-shell">
        <section className="workflow-console-primary">
          <WorkspaceSectionHeader
            title={selectedRun ? "当前 Run" : "运行状态"}
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
                  <button type="button" className="control-btn" onClick={() => void fetchResolvedConfig(selectedRun.run_id)}>
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
                <div className="workflow-console-stat">
                  <span>状态</span>
                  <strong>{mapWorkflowRunStatus(selectedRun.status)}</strong>
                </div>
                <div className="workflow-console-stat">
                  <span>Profile</span>
                  <strong>{selectedRun.profile_id}</strong>
                </div>
                <div className="workflow-console-stat">
                  <span>Backend</span>
                  <strong>{selectedRun.backend_kind || selectedRun.executor || "未记录"}</strong>
                </div>
                <div className="workflow-console-stat">
                  <span>Bundle</span>
                  <strong>{selectedRun.bundle_id || "未记录"}</strong>
                </div>
                <div className="workflow-console-stat">
                  <span>更新时间</span>
                  <strong>{formatDateTime(selectedRun.updated_at || selectedRun.created_at)}</strong>
                </div>
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
            <WorkspaceEmptyState
              mark="Run"
              label="当前还没有 Run"
              hint="先展开下方 Workflow 规格，检查参数后提交一个新的 workflow run。"
              compact
            />
          )}
        </section>

        <details className="workflow-console-section" open={workflowExpanded} onToggle={(event) => setWorkflowExpanded(event.currentTarget.open)}>
          <summary className="workflow-console-section-summary">
            <div>
              <strong>Workflow 规格</strong>
              <span>编辑 starter workflow、参数 schema，并提交新的 run。</span>
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

              <div className="workflow-node-list">
                <div className="workflow-node-list-head">
                  <strong>Steps</strong>
                  <button type="button" className="control-btn" onClick={addNode}>
                    添加 Step
                  </button>
                </div>
                {workflow?.nodes.map((node, index) => (
                  <div key={node.node_id} className="workflow-node-row">
                    <label className="control-field">
                      <span>Label</span>
                      <input className="control-input" value={node.label} onChange={(event) => updateNode(index, { label: event.target.value })} />
                    </label>
                    <label className="control-field">
                      <span>Tool ID</span>
                      <input
                        className="control-input"
                        value={node.tool_id}
                        onChange={(event) => updateNode(index, { tool_id: event.target.value })}
                        placeholder="tool_placeholder"
                      />
                    </label>
                    <button type="button" className="control-btn" onClick={() => removeNode(index)} disabled={(workflow?.nodes.length || 0) <= 1}>
                      删除
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div className="workflow-panel-stack">
              <label className="control-field">
                <span>Params Schema</span>
                <textarea className="control-textarea workflow-schema-textarea" value={schemaDraft} onChange={(event) => setSchemaDraft(event.target.value)} spellCheck={false} />
              </label>

              <div className="workflow-param-panel">
                <div className="workflow-node-list-head">
                  <strong>参数面板</strong>
                  <span className="muted">{launchProfile.profile_id}</span>
                </div>
                {schemaSummary.unsupported.length > 0 ? (
                  <p className="workflow-panel-error">以下字段类型暂不支持表单渲染：{schemaSummary.unsupported.join(", ")}</p>
                ) : null}
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

              <div className="workflow-action-row">
                <button type="button" className="control-btn" disabled={compileBusy} onClick={() => void runCompile()}>
                  {compileBusy ? "编译中..." : "更新 Bundle"}
                </button>
                <button type="button" className="control-btn control-btn--primary" disabled={runBusy} onClick={() => void submitRun()}>
                  {runBusy ? "提交中..." : "提交 Run"}
                </button>
              </div>
              {workflowMessage ? <p className="workflow-console-inline-note">{workflowMessage}</p> : null}
            </div>
          </div>
        </details>

        <details className="workflow-console-section" open={artifactsExpanded} onToggle={(event) => setArtifactsExpanded(event.currentTarget.open)}>
          <summary className="workflow-console-section-summary">
            <div>
              <strong>Artifacts</strong>
              <span>{artifactSummary}</span>
            </div>
            <span>{artifacts.length} 项</span>
          </summary>
          {selectedRun ? (
            artifacts.length > 0 ? (
              <div className="workflow-artifact-list">
                {artifacts.map((artifact) => (
                  <div key={artifact.name} className="workflow-artifact-item">
                    <div className="workflow-artifact-copy">
                      <strong>{artifact.name}</strong>
                      <p>{artifact.available ? artifact.local_path || artifact.remote_path : artifact.error || "未找到远端文件"}</p>
                    </div>
                    <span className={`workflow-artifact-state${artifact.available ? " available" : ""}`}>
                      {artifact.available ? "已同步" : "缺失"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <WorkspaceEmptyState
                mark="Art"
                label="当前 run 还没有可见产物"
                hint="先刷新状态；如果仍为空，请确认远端 run 已生成 report、timeline、trace 或 dag。"
                compact
              />
            )
          ) : (
            <WorkspaceEmptyState mark="Art" label="选择一个 Run 后查看产物" compact />
          )}
        </details>

        <details className="workflow-console-section" open={technicalExpanded} onToggle={(event) => setTechnicalExpanded(event.currentTarget.open)}>
          <summary className="workflow-console-section-summary">
            <div>
              <strong>技术详情</strong>
              <span>Compile preview、remote status、路径和 manifest。</span>
            </div>
          </summary>
          <div className="workflow-preview-grid">
            <div className="workflow-preview-card">
              <strong>Compile Preview</strong>
              <pre className="workspace-json-surface">
                {JSON.stringify(
                  compilePreview
                    ? {
                        bundle_id: compilePreview.bundle_id,
                        files: Object.keys(compilePreview.files),
                        main_nf_preview: compilePreview.files["main.nf"]?.split("\n").slice(0, 24).join("\n") || "",
                      }
                    : {},
                  null,
                  2
                )}
              </pre>
            </div>
            <div className="workflow-preview-card">
              <strong>Manifest</strong>
              <pre className="workspace-json-surface">{JSON.stringify(compilePreview?.manifest || {}, null, 2)}</pre>
            </div>
            <div className="workflow-preview-card">
              <strong>Resolved Config</strong>
              <pre className="workspace-json-surface">{resolvedConfig || compilePreview?.files["resolved.config"] || "{}"}</pre>
            </div>
            <div className="workflow-preview-card">
              <strong>Run Detail</strong>
              <pre className="workspace-json-surface">
                {JSON.stringify(
                  selectedRun
                    ? {
                        backend_kind: selectedRun.backend_kind || "",
                        executor: selectedRun.executor || "",
                        packaging_mode: selectedRun.packaging_mode || "",
                        container_runtime: selectedRun.container_runtime || "",
                        remote_status: selectedRun.remote_status || {},
                        local_bundle_dir: selectedRun.local_bundle_dir || "",
                        local_run_dir: selectedRun.local_run_dir || "",
                        resolved_config_path: selectedRun.resolved_config_path || "",
                        remote_bundle_dir: selectedRun.remote_bundle_dir || "",
                        remote_task_dir: selectedRun.remote_task_dir || "",
                        remote_work_dir: selectedRun.remote_work_dir || "",
                        remote_output_dir: selectedRun.remote_output_dir || "",
                        launcher_pid: selectedRun.launcher_pid || "",
                        nextflow_pid: selectedRun.nextflow_pid || readWorkflowRemoteValue(selectedRun, "nextflow_pid") || "",
                      }
                    : {},
                  null,
                  2
                )}
              </pre>
            </div>
          </div>
        </details>
      </section>
    </div>
  );
}
