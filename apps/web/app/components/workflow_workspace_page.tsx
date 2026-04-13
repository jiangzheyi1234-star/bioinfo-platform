"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useWorkspaceShell } from "./workspace_shell_context";
import type { ServerDoctorReport, ToolSummary, WorkflowCompilePreview, WorkflowSpecView } from "./detection_workspace_types";
import { apiBase, isRecord, parseServerDoctorReport, parseWorkflowCompilePreview, readJsonOrThrow, safeText, toToolSummary } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { buildProfileFromDoctor, createStarterWorkflow, getSchemaFields, normalizeFieldValue } from "./workflow_support";

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function WorkflowWorkspacePage() {
  const router = useRouter();
  const { currentProject, currentProjectId, setShellError } = useWorkspaceShell();

  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [workflow, setWorkflow] = useState<WorkflowSpecView | null>(null);
  const [schemaDraft, setSchemaDraft] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [doctor, setDoctor] = useState<ServerDoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState("");
  const [compilePreview, setCompilePreview] = useState<WorkflowCompilePreview | null>(null);
  const [compileBusy, setCompileBusy] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [workflowMessage, setWorkflowMessage] = useState("");

  const schemaObject = useMemo(() => {
    try {
      const parsed = JSON.parse(schemaDraft || "{}");
      return isRecord(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }, [schemaDraft]);

  const schemaSummary = useMemo(() => getSchemaFields(schemaObject || {}), [schemaObject]);
  const launchProfile = useMemo(() => buildProfileFromDoctor(doctor), [doctor]);

  useEffect(() => {
    void (async () => {
      try {
        const resp = await fetch(`${apiBase()}/api/v1/tools`);
        const data = await readJsonOrThrow(resp);
        const items = Array.isArray(data.items)
          ? data.items.map(toToolSummary).filter((item: ToolSummary | null): item is ToolSummary => !!item)
          : [];
        setTools(items);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setShellError(message);
      }
    })();
  }, [setShellError]);

  useEffect(() => {
    if (!currentProjectId) {
      setDoctor(null);
      setDoctorError("");
      return;
    }
    void (async () => {
      try {
        const resp = await fetch(`${apiBase()}/api/v1/servers/current/doctor`, { method: "POST" });
        const data = await readJsonOrThrow(resp);
        const item = parseServerDoctorReport(data?.item);
        if (!item) {
          throw new Error("服务器 doctor 返回格式无效。");
        }
        setDoctor(item);
        setDoctorError("");
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setDoctor(null);
        setDoctorError(message);
      }
    })();
  }, [currentProjectId]);

  useEffect(() => {
    if (!currentProjectId || workflow || tools.length === 0) {
      return;
    }
    const starter = createStarterWorkflow(currentProjectId, tools[0]);
    setWorkflow(starter);
    setSchemaDraft(prettyJson(starter.params_schema));
  }, [currentProjectId, tools, workflow]);

  useEffect(() => {
    if (!schemaObject) {
      return;
    }
    const nextParams: Record<string, unknown> = {};
    for (const field of schemaSummary.fields) {
      nextParams[field.key] = Object.prototype.hasOwnProperty.call(params, field.key)
        ? params[field.key]
        : field.defaultValue;
    }
    setParams(nextParams);
  }, [schemaObject, schemaSummary.fields]);

  const updateNode = (index: number, patch: Partial<WorkflowSpecView["nodes"][number]>) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      const nodes = current.nodes.map((node, nodeIndex) => (nodeIndex === index ? { ...node, ...patch } : node));
      return { ...current, nodes };
    });
  };

  const addNode = () => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      const nextIndex = current.nodes.length + 1;
      const fallbackTool = tools[0];
      return {
        ...current,
        nodes: [
          ...current.nodes,
          {
            node_id: `step_${nextIndex}`,
            tool_id: fallbackTool?.id || "tool_placeholder",
            label: fallbackTool?.name || `Step ${nextIndex}`,
            params: {},
          },
        ],
      };
    });
  };

  const removeNode = (index: number) => {
    setWorkflow((current) => {
      if (!current || current.nodes.length <= 1) {
        return current;
      }
      return {
        ...current,
        nodes: current.nodes.filter((_node, nodeIndex) => nodeIndex !== index),
      };
    });
  };

  const buildPayload = (): { workflow: WorkflowSpecView; launch: Record<string, unknown> } => {
    if (!workflow) {
      throw new Error("当前没有可提交的 workflow。");
    }
    if (!schemaObject) {
      throw new Error("参数 schema 不是有效 JSON。");
    }
    if (!currentProjectId) {
      throw new Error("请先选择项目。");
    }
    if (!doctor && doctorError) {
      throw new Error(`服务器 doctor 未通过：${doctorError}`);
    }
    return {
      workflow: {
        ...workflow,
        params_schema: schemaObject,
      },
      launch: {
        profile: launchProfile,
        params,
        data_refs: [],
        resume: true,
      },
    };
  };

  const runCompile = async () => {
    setWorkflowMessage("");
    setCompileBusy(true);
    try {
      const payload = buildPayload();
      const resp = await fetch(`${apiBase()}/api/v1/workflows/compile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          workflow: payload.workflow,
          launch: payload.launch,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const preview = parseWorkflowCompilePreview(data?.item);
      if (!preview) {
        throw new Error("workflow compile 返回格式无效。");
      }
      setCompilePreview(preview);
      setWorkflowMessage(`Bundle 已生成：${preview.bundle_id}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setWorkflowMessage(message);
      setShellError(message);
    } finally {
      setCompileBusy(false);
    }
  };

  const submitRun = async () => {
    setWorkflowMessage("");
    setRunBusy(true);
    try {
      const payload = buildPayload();
      const resp = await fetch(`${apiBase()}/api/v1/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          workflow: payload.workflow,
          launch: payload.launch,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const runId = safeText(data?.item?.run_id);
      if (!runId) {
        throw new Error("run 提交成功但缺少 run_id。");
      }
      router.push(`/runs?run_id=${encodeURIComponent(runId)}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setWorkflowMessage(message);
      setShellError(message);
    } finally {
      setRunBusy(false);
    }
  };

  if (!currentProjectId || !currentProject) {
    return <WorkspaceEmptyState mark="WF" label="先选择一个项目" hint="Workflow bundle 会绑定到当前项目目录。" />;
  }

  return (
    <div className="project-workspace-content">
      <WorkspaceSectionHeader
        title="Workflows"
        description="编辑 workflow 规格、预览 Nextflow bundle，并直接提交新的 workflow run。"
        aside={
          <div className="workflow-summary-inline">
            <span>{currentProject.name}</span>
            <span>{launchProfile.profile_kind}</span>
          </div>
        }
      />

      <section className="workflow-panel">
        <div className="workflow-panel-grid">
          <div className="workflow-panel-stack">
            <label className="control-field">
              <span>Workflow 名称</span>
              <input
                className="control-input"
                value={workflow?.name || ""}
                onChange={(event) => setWorkflow((current) => (current ? { ...current, name: event.target.value } : current))}
              />
            </label>
            <label className="control-field">
              <span>Workflow ID</span>
              <input
                className="control-input"
                value={workflow?.workflow_id || ""}
                onChange={(event) =>
                  setWorkflow((current) => (current ? { ...current, workflow_id: event.target.value.trim() } : current))
                }
              />
            </label>
            <div className="workflow-node-list">
              <div className="workflow-node-list-head">
                <strong>步骤</strong>
                <button type="button" className="control-btn" onClick={addNode}>
                  添加步骤
                </button>
              </div>
              {(workflow?.nodes || []).map((node, index) => (
                <div key={node.node_id} className="workflow-node-row">
                  <label className="control-field">
                    <span>步骤名</span>
                    <input
                      className="control-input"
                      value={node.label}
                      onChange={(event) => updateNode(index, { label: event.target.value })}
                    />
                  </label>
                  <label className="control-field">
                    <span>Tool ID</span>
                    <select
                      className="control-select"
                      value={node.tool_id}
                      onChange={(event) => {
                        const selectedTool = tools.find((tool) => tool.id === event.target.value);
                        updateNode(index, {
                          tool_id: event.target.value,
                          label: selectedTool?.name || node.label,
                        });
                      }}
                    >
                      {tools.map((tool) => (
                        <option key={tool.id} value={tool.id}>
                          {tool.name} · {tool.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="button" className="control-btn" disabled={(workflow?.nodes.length || 0) <= 1} onClick={() => removeNode(index)}>
                    删除
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="workflow-panel-stack">
            <label className="control-field">
              <span>参数 Schema</span>
              <textarea
                className="control-textarea workflow-schema-textarea"
                value={schemaDraft}
                onChange={(event) => setSchemaDraft(event.target.value)}
              />
            </label>
            {schemaObject ? null : <p className="workflow-panel-error">参数 schema 必须是有效 JSON object。</p>}
            {doctorError ? <p className="workflow-panel-error">服务器 doctor 失败：{doctorError}</p> : null}
            <div className="workflow-param-panel">
              <div className="workflow-node-list-head">
                <strong>参数面板</strong>
                <span className="muted">{schemaSummary.fields.length} fields</span>
              </div>
              {schemaSummary.fields.length === 0 ? (
                <WorkspaceEmptyState mark="JSON" label="当前 schema 还没有可渲染字段" compact />
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
                      onChange={(event) =>
                        setParams((current) => ({
                          ...current,
                          [field.key]: normalizeFieldValue(field.kind, event.target.value),
                        }))
                      }
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
                        onChange={(event) =>
                          setParams((current) => ({
                            ...current,
                            [field.key]: event.target.checked,
                          }))
                        }
                      />
                      <span>{field.description || "启用此选项"}</span>
                    </label>
                  ) : (
                    <input
                      className="control-input"
                      type={field.kind === "string" ? "text" : "number"}
                      value={String(params[field.key] ?? field.defaultValue)}
                      onChange={(event) =>
                        setParams((current) => ({
                          ...current,
                          [field.key]: normalizeFieldValue(field.kind, event.target.value),
                        }))
                      }
                    />
                  )}
                  {field.description ? <small className="muted">{field.description}</small> : null}
                </label>
              ))}
              {schemaSummary.unsupported.length > 0 ? (
                <p className="muted">未渲染字段：{schemaSummary.unsupported.join("、")}。当前首期仅支持顶层标量字段。</p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="workflow-action-row">
          <button type="button" className="control-btn" disabled={compileBusy || runBusy} onClick={() => void runCompile()}>
            {compileBusy ? "生成中..." : "预览 Bundle"}
          </button>
          <button type="button" className="control-btn control-btn--primary" disabled={runBusy || compileBusy || !schemaObject} onClick={() => void submitRun()}>
            {runBusy ? "提交中..." : "提交 Run"}
          </button>
          {workflowMessage ? <span className="muted">{workflowMessage}</span> : null}
        </div>
      </section>

      <section className="workflow-panel">
        <WorkspaceSectionHeader title="Compile Preview" description="固定展示这次 launch 将上传的 manifest、resolved config 和参数快照。" />
        {compilePreview ? (
          <div className="workflow-preview-grid">
            <div className="workflow-preview-card">
              <strong>Manifest</strong>
              <pre className="workspace-json-surface">{prettyJson(compilePreview.manifest)}</pre>
            </div>
            <div className="workflow-preview-card">
              <strong>Resolved Config</strong>
              <pre className="workspace-json-surface">{compilePreview.files["resolved.config"] || "resolved.config not generated"}</pre>
            </div>
            <div className="workflow-preview-card">
              <strong>Params</strong>
              <pre className="workspace-json-surface">{compilePreview.files["params/run.yaml"] || "{}"}</pre>
            </div>
          </div>
        ) : (
          <WorkspaceEmptyState mark="NF" label="先生成一次 bundle preview" hint="Compile 成功后，这里会展示 manifest、resolved config 和 params。" compact />
        )}
      </section>
    </div>
  );
}
