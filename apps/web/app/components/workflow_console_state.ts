"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useWorkspaceShell } from "./workspace_shell_context";
import type {
  WorkflowCompatibilitySummary,
  ServerDoctorReport,
  WorkflowArtifact,
  WorkflowCompilePreview,
  WorkflowNodePosition,
  WorkflowRun,
  WorkflowSpecView,
  WorkflowToolDescriptor,
} from "./detection_workspace_types";
import {
  apiBase,
  isRecord,
  parseServerDoctorReport,
  parseWorkflowCompilePreview,
  readJsonOrThrow,
  safeText,
  toWorkflowArtifact,
  toWorkflowRun,
} from "./detection_workspace_utils";
import {
  createStarterWorkflow,
  createWorkflowEdgeDraft,
  createWorkflowNodeDraft,
  getSchemaFields,
  normalizeFieldValue,
} from "./workflow_support";
import {
  buildWorkflowCompatibilitySummary,
  parseWorkflowToolDescriptor,
  summarizeWorkflowCompatibility,
} from "./workflow_profile_compatibility";

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function workflowDraftStorageKey(projectId: string) {
  return `h2ometa:workflow-draft:${projectId}`;
}

function readStoredWorkflowDraft(projectId: string): { workflow: WorkflowSpecView; schemaDraft: string } | null {
  if (typeof window === "undefined" || !projectId) {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(workflowDraftStorageKey(projectId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed) || !isRecord(parsed.workflow)) {
      return null;
    }
    const workflow = parsed.workflow as WorkflowSpecView;
    const schemaDraft = typeof parsed.schemaDraft === "string" ? parsed.schemaDraft : prettyJson(workflow.params_schema ?? {});
    return { workflow, schemaDraft };
  } catch {
    return null;
  }
}

function nextDraftId(items: string[], prefix: string) {
  const used = new Set(items);
  let index = items.length + 1;
  while (used.has(`${prefix}_${index}`)) {
    index += 1;
  }
  return index;
}

export function readWorkflowRemoteValue(run: WorkflowRun, key: string): string {
  const value = run.remote_status && typeof run.remote_status[key] !== "undefined" ? run.remote_status[key] : "";
  return safeText(value);
}

export function describeDoctor(summary: WorkflowCompatibilitySummary, doctorError: string): string {
  return summarizeWorkflowCompatibility(summary, doctorError);
}

export function useWorkflowConsoleState() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentProject, currentProjectId, selectedTaskId, setShellError } = useWorkspaceShell();

  const [workflow, setWorkflow] = useState<WorkflowSpecView | null>(null);
  const [schemaDraft, setSchemaDraft] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [doctor, setDoctor] = useState<ServerDoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState("");
  const [toolDescriptors, setToolDescriptors] = useState<Record<string, WorkflowToolDescriptor>>({});
  const [toolDescriptorBusy, setToolDescriptorBusy] = useState(false);
  const [compilePreview, setCompilePreview] = useState<WorkflowCompilePreview | null>(null);
  const [compileBusy, setCompileBusy] = useState(false);
  const [runBusy, setRunBusy] = useState(false);
  const [workflowMessage, setWorkflowMessage] = useState("");
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [artifacts, setArtifacts] = useState<WorkflowArtifact[]>([]);
  const [resolvedConfig, setResolvedConfig] = useState("");
  const [artifactsBusy, setArtifactsBusy] = useState(false);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);
  const [artifactsExpanded, setArtifactsExpanded] = useState(false);
  const [technicalExpanded, setTechnicalExpanded] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [detailTab, setDetailTab] = useState<"logs" | "artifacts" | "config" | "trace">("logs");

  const schemaObject = useMemo(() => {
    try {
      const parsed = JSON.parse(schemaDraft || "{}");
      return isRecord(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }, [schemaDraft]);

  const schemaSummary = useMemo(() => getSchemaFields(schemaObject || {}), [schemaObject]);
  const compatibilitySummary = useMemo(
    () => buildWorkflowCompatibilitySummary(doctor, workflow, toolDescriptors),
    [doctor, workflow, toolDescriptors]
  );
  const launchProfile = compatibilitySummary.selected_profile;
  const selectedRun = useMemo(
    () => runs.find((item) => item.run_id === selectedRunId) ?? null,
    [runs, selectedRunId]
  );
  const selectedNode = useMemo(
    () => workflow?.nodes.find((item) => item.node_id === selectedNodeId) ?? null,
    [workflow, selectedNodeId]
  );
  const toolIds = useMemo(
    () => Array.from(new Set((workflow?.nodes || []).map((node) => node.tool_id).filter(Boolean))),
    [workflow]
  );

  const refreshRuns = async (preferredRunId?: string) => {
    if (!currentProjectId) {
      setRuns([]);
      setSelectedRunId("");
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/runs`);
    const data = await readJsonOrThrow(resp);
    const items = Array.isArray(data.items)
      ? data.items.map(toWorkflowRun).filter((item: WorkflowRun | null): item is WorkflowRun => item !== null)
      : [];
    setRuns(items);
    const requested = safeText(preferredRunId || searchParams.get("run_id"));
    const nextSelectedId = requested && items.some((item: WorkflowRun) => item.run_id === requested) ? requested : items[0]?.run_id || "";
    setSelectedRunId(nextSelectedId);
  };

  const refreshRunDetail = async (runId: string) => {
    if (!currentProjectId || !runId) {
      return;
    }
    setDetailBusy(true);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/runs/${encodeURIComponent(runId)}`);
      const data = await readJsonOrThrow(resp);
      const item = toWorkflowRun(data.item);
      if (!item) {
        throw new Error("workflow run detail 返回格式无效。");
      }
      setRuns((current) => {
        const next = current.map((existing) => (existing.run_id === item.run_id ? item : existing));
        return next.some((existing) => existing.run_id === item.run_id) ? next : [item, ...current];
      });
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailBusy(false);
    }
  };

  const fetchArtifacts = async (runId: string) => {
    if (!currentProjectId || !runId) {
      setArtifacts([]);
      return;
    }
    setArtifactsBusy(true);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/runs/${encodeURIComponent(runId)}/artifacts`);
      const data = await readJsonOrThrow(resp);
      const items = Array.isArray(data.items)
        ? data.items.map(toWorkflowArtifact).filter((item: WorkflowArtifact | null): item is WorkflowArtifact => item !== null)
        : [];
      setArtifacts(items);
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setArtifactsBusy(false);
    }
  };

  const fetchResolvedConfig = async (runId: string) => {
    if (!currentProjectId || !runId) {
      setResolvedConfig("");
      return;
    }
    try {
      const resp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/runs/${encodeURIComponent(runId)}/resolved-config`
      );
      const data = await readJsonOrThrow(resp);
      setResolvedConfig(safeText(data?.item?.content));
    } catch (err) {
      setResolvedConfig("");
      setShellError(err instanceof Error ? err.message : String(err));
    }
  };

  const cancelRun = async (runId: string) => {
    if (!currentProjectId || !runId) {
      return;
    }
    setActionBusy(runId);
    try {
      const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/runs/${encodeURIComponent(runId)}/cancel`, {
        method: "POST",
      });
      const data = await readJsonOrThrow(resp);
      const item = toWorkflowRun(data.item);
      if (!item) {
        throw new Error("cancel run 返回格式无效。");
      }
      setRuns((current) => current.map((existing) => (existing.run_id === item.run_id ? item : existing)));
    } catch (err) {
      setShellError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy("");
    }
  };

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
    setWorkflow(null);
    setSchemaDraft("");
    setParams({});
    setCompilePreview(null);
    setSelectedNodeId("");
  }, [currentProjectId]);

  useEffect(() => {
    if (!currentProjectId || workflow) {
      return;
    }
    const storedDraft = readStoredWorkflowDraft(currentProjectId);
    const starter = storedDraft?.workflow ?? createStarterWorkflow(currentProjectId);
    setWorkflow(starter);
    setSchemaDraft(storedDraft?.schemaDraft ?? prettyJson(starter.params_schema));
    setSelectedNodeId(starter.nodes[0]?.node_id || "");
  }, [currentProjectId, workflow]);

  useEffect(() => {
    if (!currentProjectId || !workflow) {
      return;
    }
    let active = true;
    setToolDescriptorBusy(true);
    void (async () => {
      try {
        const entries = await Promise.all(
          toolIds.map(async (toolId: string) => {
            const resp = await fetch(`${apiBase()}/api/v1/workflows/tools/${encodeURIComponent(toolId)}/descriptor`);
            if (!resp.ok) {
              return [toolId, { tool_id: toolId, name: toolId, workflow_support: null }] as const;
            }
            const data = await readJsonOrThrow(resp);
            const item = parseWorkflowToolDescriptor(data?.item);
            return [toolId, item || { tool_id: toolId, name: toolId, workflow_support: null }] as const;
          })
        );
        if (!active) {
          return;
        }
        setToolDescriptors(Object.fromEntries(entries));
      } catch (err) {
        if (!active) {
          return;
        }
        setToolDescriptors({});
        setShellError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) {
          setToolDescriptorBusy(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [toolIds, workflow, setShellError]);

  useEffect(() => {
    if (!workflow?.nodes.length) {
      setSelectedNodeId("");
      return;
    }
    if (!workflow.nodes.some((node) => node.node_id === selectedNodeId)) {
      setSelectedNodeId(workflow.nodes[0]?.node_id || "");
    }
  }, [workflow, selectedNodeId]);

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

  useEffect(() => {
    void refreshRuns();
  }, [currentProjectId]);

  useEffect(() => {
    const requestedRunId = safeText(searchParams.get("run_id"));
    if (requestedRunId) {
      setSelectedRunId(requestedRunId);
    }
  }, [searchParams]);

  useEffect(() => {
    if (!selectedRunId) {
      setArtifacts([]);
      setResolvedConfig("");
      return;
    }
    void refreshRunDetail(selectedRunId);
    void fetchArtifacts(selectedRunId);
    void fetchResolvedConfig(selectedRunId);
  }, [selectedRunId]);

  useEffect(() => {
    if (selectedRun && ["running", "pending", "draft"].includes(selectedRun.status)) {
      const timer = window.setTimeout(() => {
        void refreshRunDetail(selectedRun.run_id);
      }, 5000);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [selectedRun]);

  const updateNode = (index: number, patch: Partial<WorkflowSpecView["nodes"][number]>) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      const nodes = current.nodes.map((node, nodeIndex) => (nodeIndex === index ? { ...node, ...patch } : node));
      return { ...current, nodes };
    });
  };

  const updateNodePosition = (nodeId: string, position: WorkflowNodePosition) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        nodes: current.nodes.map((node) => (node.node_id === nodeId ? { ...node, position } : node)),
      };
    });
  };

  const addNode = (templateKey?: string) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      const nextIndex = nextDraftId(
        current.nodes.map((node) => node.node_id),
        "step"
      );
      return {
        ...current,
        nodes: [
          ...current.nodes,
          createWorkflowNodeDraft({ index: nextIndex, templateKey }),
        ],
      };
    });
  };

  const removeNode = (index: number) => {
    setWorkflow((current) => {
      if (!current || current.nodes.length <= 1) {
        return current;
      }
      const removedNodeId = current.nodes[index]?.node_id;
      return {
        ...current,
        nodes: current.nodes.filter((_node, nodeIndex) => nodeIndex !== index),
        edges: current.edges.filter(
          (edge) => edge.source_node_id !== removedNodeId && edge.target_node_id !== removedNodeId
        ),
      };
    });
  };

  const updateEdge = (edgeId: string, patch: Partial<WorkflowSpecView["edges"][number]>) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        edges: current.edges.map((edge) => (edge.edge_id === edgeId ? { ...edge, ...patch } : edge)),
      };
    });
  };

  const connectNodes = (sourceNodeId: string, targetNodeId: string) => {
    setWorkflowMessage("");
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      if (
        current.edges.some(
          (edge) => edge.source_node_id === sourceNodeId && edge.target_node_id === targetNodeId
        )
      ) {
        setWorkflowMessage("相同的节点连线已经存在，可直接在 Connections 面板中修改 input/output。");
        return current;
      }
      const nextIndex = nextDraftId(
        current.edges.map((edge) => edge.edge_id),
        "edge"
      );
      return {
        ...current,
        edges: [
          ...current.edges,
          createWorkflowEdgeDraft({
            index: nextIndex,
            sourceNodeId,
            targetNodeId,
          }),
        ],
      };
    });
  };

  const removeEdge = (edgeId: string) => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        edges: current.edges.filter((edge) => edge.edge_id !== edgeId),
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
    if (!doctor) {
      throw new Error("正在检测服务器运行时，请稍后再试。");
    }
    if (toolDescriptorBusy) {
      throw new Error("正在加载 workflow 节点描述符，请稍后再试。");
    }
    if (!launchProfile) {
      const reasons = compatibilitySummary.workflow_profiles.flatMap((item) => item.incompatibility_reasons);
      throw new Error(reasons[0] || "当前 workflow 没有可用 profile。");
    }
    return {
      workflow: {
        ...workflow,
        nodes: workflow.nodes.map((node) => ({
          node_id: node.node_id,
          tool_id: node.tool_id,
          label: node.label,
          params: node.params,
        })),
        edges: workflow.edges.map((edge) => ({
          edge_id: edge.edge_id,
          source_node_id: edge.source_node_id,
          target_node_id: edge.target_node_id,
          output_name: edge.output_name,
          input_name: edge.input_name,
        })),
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
      setWorkflowMessage(`Bundle 已更新：${preview.bundle_id}`);
      setTechnicalExpanded(true);
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
      if (!selectedTaskId) {
        throw new Error("请先选择一个任务，再提交 workflow run。");
      }
      const payload = buildPayload();
      const snapshotResp = await fetch(
        `${apiBase()}/api/v1/projects/${encodeURIComponent(currentProjectId)}/tasks/${encodeURIComponent(selectedTaskId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            workflow: payload.workflow,
          }),
        }
      );
      await readJsonOrThrow(snapshotResp);
      const resp = await fetch(`${apiBase()}/api/v1/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          task_id: selectedTaskId,
          launch: payload.launch,
        }),
      });
      const data = await readJsonOrThrow(resp);
      const item = toWorkflowRun(data?.item);
      if (!item) {
        throw new Error("run 提交返回格式无效。");
      }
      setRuns((current) => [item, ...current.filter((existing) => existing.run_id !== item.run_id)]);
      setSelectedRunId(item.run_id);
      setArtifacts([]);
      setResolvedConfig("");
      setWorkflowExpanded(false);
      setArtifactsExpanded(false);
      router.replace(`/workspace?run_id=${encodeURIComponent(item.run_id)}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setWorkflowMessage(message);
      setShellError(message);
    } finally {
      setRunBusy(false);
    }
  };

  const artifactSummary = (() => {
    const available = artifacts.filter((item) => item.available).length;
    const missing = artifacts.length - available;
    if (!selectedRunId) {
      return "选择一个 Run 后查看产物。";
    }
    if (artifactsBusy) {
      return "正在同步产物清单。";
    }
    if (artifacts.length === 0) {
      return "当前还没有可见产物。";
    }
    return `已同步 ${available} 项，缺失 ${missing} 项。`;
  })();

  const traceArtifacts = artifacts.filter((artifact) => {
    const name = `${artifact.name} ${artifact.remote_path} ${artifact.local_path}`.toLowerCase();
    return (
      name.includes("trace") ||
      name.includes("timeline") ||
      name.includes("report") ||
      name.includes("dag") ||
      name.endsWith(".html")
    );
  });

  return {
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
    toolDescriptorBusy,
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
    submitRun,
  };
}
