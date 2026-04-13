"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useWorkspaceShell } from "./workspace_shell_context";
import type {
  ServerDoctorReport,
  WorkflowArtifact,
  WorkflowCompilePreview,
  WorkflowRun,
  WorkflowSpecView,
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
import { buildProfileFromDoctor, getSchemaFields, normalizeFieldValue, createStarterWorkflow } from "./workflow_support";

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function readWorkflowRemoteValue(run: WorkflowRun, key: string): string {
  const value = run.remote_status && typeof run.remote_status[key] !== "undefined" ? run.remote_status[key] : "";
  return safeText(value);
}

export function describeDoctor(doctor: ServerDoctorReport | null, doctorError: string): string {
  if (doctorError) {
    return `连接可用，但运行时探测失败：${doctorError}`;
  }
  if (!doctor) {
    return "正在检测服务器运行时。";
  }
  const profile = buildProfileFromDoctor(doctor);
  const nextflow = doctor.runtime_capabilities?.nextflow;
  const java = doctor.runtime_capabilities?.java;
  const runtimeBits = [
    nextflow?.available ? `Nextflow ${nextflow.version || "ok"}` : "Nextflow 缺失",
    java?.available ? `Java ${java.version || "ok"}` : "Java 缺失",
  ];
  return `建议 profile：${profile.profile_id} · executor=${profile.executor} · ${runtimeBits.join(" / ")}`;
}

export function useWorkflowConsoleState() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentProject, currentProjectId, setShellError } = useWorkspaceShell();

  const [workflow, setWorkflow] = useState<WorkflowSpecView | null>(null);
  const [schemaDraft, setSchemaDraft] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [doctor, setDoctor] = useState<ServerDoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState("");
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
  const launchProfile = useMemo(() => buildProfileFromDoctor(doctor), [doctor]);
  const selectedRun = useMemo(
    () => runs.find((item) => item.run_id === selectedRunId) ?? null,
    [runs, selectedRunId]
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
    if (!currentProjectId || workflow) {
      return;
    }
    const starter = createStarterWorkflow(currentProjectId);
    setWorkflow(starter);
    setSchemaDraft(prettyJson(starter.params_schema));
    setSelectedNodeId(starter.nodes[0]?.node_id || "");
  }, [currentProjectId, workflow]);

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

  const addNode = () => {
    setWorkflow((current) => {
      if (!current) {
        return current;
      }
      const nextIndex = current.nodes.length + 1;
      return {
        ...current,
        nodes: [
          ...current.nodes,
          {
            node_id: `step_${nextIndex}`,
            tool_id: `tool_${nextIndex}`,
            label: `Step ${nextIndex}`,
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
    detailTab,
    schemaSummary,
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
    addNode,
    removeNode,
    runCompile,
    submitRun,
  };
}
