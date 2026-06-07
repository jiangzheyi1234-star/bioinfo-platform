"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import { GENERATED_TOOL_RUN_PIPELINE_ID, workflowToolRevisionId } from "./generated-workflow-model";
import { useGeneratedWorkflowBuilder } from "./use-generated-workflow-builder";
import {
  fetchRunsList,
  fetchWorkflowCatalog,
  fetchWorkflowDatabases,
  fetchWorkflowDesignDrafts,
  fetchWorkflowRunDetail,
  fetchWorkflowServer,
  fetchWorkflowTools,
  compileWorkflowDesignDraft,
  getCachedWorkflowCatalog,
  getCachedWorkflowServer,
  planWorkflowDesignDraft,
  saveWorkflowDesignDraft,
  submitWorkflowDesignRun,
  submitPipelineWorkflowRun,
  uploadWorkflowSampleData,
} from "./workflows-page-api";
import {
  buildWorkflowDesignDraft,
  workflowDesignDraftToGraphDraft,
  type WorkflowDesignCompileResult,
  type WorkflowDesignDraftRecord,
  type WorkflowDesignPlan,
} from "./workflow-design-draft-model";
import {
  buildWorkflowResourceBindings,
  databaseMatchesWorkflowResource,
  runnableCatalogItems,
  selectableDatabases,
  selectableTools,
  workflowErrorMessage,
  workflowResourceEntries,
  type WorkflowCatalogItem,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowServer,
  type WorkflowUpload,
} from "./workflows-page-model";

export function useWorkflowsPageState(initialWorkflowId = "") {
  const [catalog, setCatalog] = useState<WorkflowCatalogItem[]>(() => getCachedWorkflowCatalog() || []);
  const [tools, setTools] = useState<AddedTool[]>([]);
  const [databases, setDatabases] = useState<DatabaseItem[]>([]);
  const [server, setServer] = useState<WorkflowServer | null>(() => getCachedWorkflowServer() || null);
  const [loading, setLoading] = useState(() => !getCachedWorkflowCatalog());
  const [error, setError] = useState("");
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(initialWorkflowId);
  const [selectedResourceDatabaseIds, setSelectedResourceDatabaseIds] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [sampleUploads, setSampleUploads] = useState<WorkflowUpload[]>([]);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submittedRun, setSubmittedRun] = useState<WorkflowRun | null>(null);
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [runHistory, setRunHistory] = useState<WorkflowRun[]>([]);
  const [workflowDesignDrafts, setWorkflowDesignDrafts] = useState<WorkflowDesignDraftRecord[]>([]);
  const [activeWorkflowDesignDraft, setActiveWorkflowDesignDraft] = useState<WorkflowDesignDraftRecord | null>(null);
  const [workflowDesignPlan, setWorkflowDesignPlan] = useState<WorkflowDesignPlan | null>(null);
  const [workflowDesignPlanSignature, setWorkflowDesignPlanSignature] = useState("");
  const [workflowDesignCompileResult, setWorkflowDesignCompileResult] = useState<WorkflowDesignCompileResult | null>(null);
  const [workflowDesignBusy, setWorkflowDesignBusy] = useState(false);
  const [workflowDesignError, setWorkflowDesignError] = useState("");
  const [pendingRecommendedToolRevisionId, setPendingRecommendedToolRevisionId] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [activeRunId, setActiveRunId] = useState<string>("");

  const loadWorkspace = useCallback(async (options: { forceRefresh?: boolean } = {}) => {
    setLoading(true);
    setError("");
    try {
      const nextCatalog = await fetchWorkflowCatalog(options);
      const runnableWorkflows = runnableCatalogItems(nextCatalog);
      setCatalog(nextCatalog);
      setSelectedWorkflowId((current) =>
        initialWorkflowId || current || runnableWorkflows[0]?.id || nextCatalog[0]?.id || ""
      );
    } catch (err) {
      setError(workflowErrorMessage(err, "读取流程工作区失败"));
    } finally {
      setLoading(false);
    }
    const [toolsResult, databasesResult, serverResult] = await Promise.allSettled([
      fetchWorkflowTools(options),
      fetchWorkflowDatabases(options),
      fetchWorkflowServer(options),
    ]);
    if (toolsResult.status === "fulfilled") {
      const nextTools = toolsResult.value;
      setTools(nextTools);
    }
    if (databasesResult.status === "fulfilled") {
      setDatabases(databasesResult.value);
    }
    if (serverResult.status === "fulfilled") {
      setServer(serverResult.value);
    }
    if (serverResult.status === "rejected") {
      const message = workflowErrorMessage(serverResult.reason, "读取工作流运行服务失败");
      setWorkflowDesignError(message);
      setError(message);
      return;
    }
    const serverId = serverResult.value.serverId;
    if (!serverId) {
      const message = "serverId is required";
      setWorkflowDesignError(message);
      setError(message);
      return;
    }
    try {
      setWorkflowDesignDrafts(await fetchWorkflowDesignDrafts({ ...options, serverId }));
      setWorkflowDesignError("");
    } catch (err) {
      const message = workflowErrorMessage(err, "读取 WorkflowDesignDraft 列表失败");
      setWorkflowDesignError(message);
      setError(message);
    }
  }, [initialWorkflowId]);

  const loadRunHistory = useCallback(async () => {
    try {
      const runs = await fetchRunsList();
      setRunHistory(runs);
    } catch {
      // Non-critical: history is best-effort
    }
  }, []);

  useEffect(() => {
    void loadWorkspace();
    void loadRunHistory();
  }, [loadRunHistory, loadWorkspace]);

  const selectedWorkflow = catalog.find((item) => item.id === selectedWorkflowId) || catalog[0] || null;
  const selectedPipelineId = selectedWorkflow?.kind === "pipeline" && selectedWorkflow.runnable ? selectedWorkflow.id : "";
  const isGeneratedToolRun = selectedPipelineId === GENERATED_TOOL_RUN_PIPELINE_ID;

  useEffect(() => {
    setSampleUploads([]);
    setFiles([]);
    if (selectedWorkflow?.paramsSchema && typeof selectedWorkflow.paramsSchema === "object") {
      const schema = selectedWorkflow.paramsSchema as Record<string, unknown>;
      const properties = (schema.properties || {}) as Record<string, { default?: unknown }>;
      const defaults: Record<string, unknown> = {};
      for (const key of Object.keys(properties)) {
        if (properties[key].default !== undefined) {
          defaults[key] = properties[key].default;
        }
      }
      setParams(defaults);
    } else {
      setParams({});
    }
  }, [selectedWorkflowId, selectedWorkflow?.paramsSchema]);

  const runnableTools = useMemo(() => selectableTools(tools), [tools]);
  const availableDatabases = useMemo(() => selectableDatabases(databases), [databases]);
  const generatedInputCount = activeWorkflowDesignDraft
    ? Math.max(files.length, activeWorkflowDesignDraft.draft.inputs.length)
    : files.length;
  const generatedBuilder = useGeneratedWorkflowBuilder(runnableTools, availableDatabases, generatedInputCount);
  const addRecommendedWorkflowTool = useCallback(async (toolRevisionId: string) => {
    const normalizedRevisionId = String(toolRevisionId || "").trim();
    if (!normalizedRevisionId) return;
    if (runnableTools.some((tool) => workflowToolRevisionId(tool) === normalizedRevisionId)) {
      generatedBuilder.addStep(toolRevisionId);
      return;
    }
    setPendingRecommendedToolRevisionId(normalizedRevisionId);
    setWorkflowDesignError("");
    try {
      const nextTools = await fetchWorkflowTools({ forceRefresh: true });
      setTools(nextTools);
      if (!selectableTools(nextTools).some((tool) => workflowToolRevisionId(tool) === normalizedRevisionId)) {
        setPendingRecommendedToolRevisionId((current) => current === normalizedRevisionId ? "" : current);
        setWorkflowDesignError("推荐工具还未进入可添加工具列表，请稍后刷新工具库。");
      }
    } catch (err) {
      setPendingRecommendedToolRevisionId((current) => current === normalizedRevisionId ? "" : current);
      setWorkflowDesignError(workflowErrorMessage(err, "刷新推荐工具失败"));
    }
  }, [generatedBuilder, runnableTools]);
  useEffect(() => {
    const toolRevisionId = pendingRecommendedToolRevisionId;
    if (!toolRevisionId) return;
    if (!runnableTools.some((tool) => workflowToolRevisionId(tool) === toolRevisionId)) return;
    generatedBuilder.addStep(toolRevisionId);
    setPendingRecommendedToolRevisionId("");
  }, [generatedBuilder, pendingRecommendedToolRevisionId, runnableTools]);
  const currentWorkflowDesignDraftResult = useMemo(() => {
    if (!isGeneratedToolRun) return { draft: null, error: "" };
    try {
      return {
        draft: buildWorkflowDesignDraft({
          graphDraft: generatedBuilder.graphDraft,
          files,
          projectId: selectedWorkflow?.id || "proj_workflow_ui",
          resourceBindings: generatedBuilder.resourceBindings,
          name: activeWorkflowDesignDraft?.name || selectedWorkflow?.name || "Generated workflow design",
          existingDraft: activeWorkflowDesignDraft?.draft,
        }),
        error: "",
      };
    } catch (err) {
      return { draft: null, error: workflowErrorMessage(err, "WORKFLOW_DESIGN_DRAFT_INVALID") };
    }
  }, [
    activeWorkflowDesignDraft,
    files,
    generatedBuilder.graphDraft,
    generatedBuilder.resourceBindings,
    isGeneratedToolRun,
    selectedWorkflow?.id,
    selectedWorkflow?.name,
  ]);
  const currentWorkflowDesignDraft = currentWorkflowDesignDraftResult.draft;
  const currentWorkflowDesignDraftError = currentWorkflowDesignDraftResult.error;
  const currentWorkflowDesignSignature = useMemo(
    () => currentWorkflowDesignDraft ? workflowDesignDraftSignature(currentWorkflowDesignDraft) : "",
    [currentWorkflowDesignDraft]
  );
  const currentWorkflowDesignPlan =
    workflowDesignPlan && workflowDesignPlanSignature === currentWorkflowDesignSignature ? workflowDesignPlan : null;
  const currentWorkflowDesignCompileResult = currentWorkflowDesignPlan ? workflowDesignCompileResult : null;
  const workflowResources = useMemo(() => workflowResourceEntries(selectedWorkflow), [selectedWorkflow]);
  const missingRequiredResourceKeys = workflowResources
    .filter(([key, spec]) => {
      if (!spec.required) return false;
      const selectedDatabase = availableDatabases.find((database) => database.id === selectedResourceDatabaseIds[key]);
      return !selectedDatabase || !databaseMatchesWorkflowResource(selectedDatabase, spec);
    })
    .map(([key]) => key);
  const workflowResourceBindings = useMemo(
    () => buildWorkflowResourceBindings(selectedResourceDatabaseIds, selectedWorkflow, availableDatabases),
    [availableDatabases, selectedResourceDatabaseIds, selectedWorkflow]
  );
  const pipelineInputCount = isGeneratedToolRun ? files.length : files.length + sampleUploads.length;
  const canSubmit = Boolean(
    server?.serverId &&
      server.ready === true &&
      pipelineInputCount > 0 &&
      selectedWorkflow?.runnable &&
      (isGeneratedToolRun || Boolean(selectedPipelineId)) &&
      (!isGeneratedToolRun || (generatedBuilder.selectedTools.length > 0 && generatedBuilder.validation.errors.length === 0)) &&
      (!isGeneratedToolRun || currentWorkflowDesignPlan?.valid === true) &&
      (!isGeneratedToolRun || Boolean(currentWorkflowDesignCompileResult?.workflowRevisionId)) &&
      (isGeneratedToolRun || missingRequiredResourceKeys.length === 0) &&
      (!isGeneratedToolRun || !workflowDesignBusy) &&
      !submitting &&
      !sampleLoading
  );

  useEffect(() => {
    setSelectedResourceDatabaseIds((current) => {
      const next: Record<string, string> = {};
      for (const [key, spec] of workflowResources) {
        const currentDatabase = availableDatabases.find((database) => database.id === current[key]);
        if (currentDatabase && databaseMatchesWorkflowResource(currentDatabase, spec)) {
          next[key] = currentDatabase.id;
          continue;
        }
        if (spec.required) {
          const firstMatch = availableDatabases.find((database) => databaseMatchesWorkflowResource(database, spec));
          if (firstMatch) next[key] = firstMatch.id;
        }
      }
      return next;
    });
  }, [availableDatabases, workflowResources]);

  useEffect(() => {
    if (workflowDesignPlanSignature && workflowDesignPlanSignature !== currentWorkflowDesignSignature) {
      setWorkflowDesignPlan(null);
      setWorkflowDesignPlanSignature("");
      setWorkflowDesignCompileResult(null);
    }
  }, [currentWorkflowDesignSignature, workflowDesignPlanSignature]);

  useEffect(() => {
    const runId = activeRunId || submittedRun?.runId;
    if (!runId) {
      setRunDetail(null);
      return;
    }
    const pollingRunId = runId;
    let cancelled = false;
    async function loadRunDetail() {
      try {
        const detail = await fetchWorkflowRunDetail(pollingRunId);
        if (!cancelled) {
          setRunDetail(detail);
        }
      } catch (err) {
        if (!cancelled) {
          setSubmitError(workflowErrorMessage(err, "读取运行详情失败"));
        }
      }
    }
    void loadRunDetail();
    const timer = window.setInterval(() => void loadRunDetail(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [submittedRun, activeRunId]);

  function setWorkflowResourceBinding(resourceKey: string, databaseId: string) {
    setSelectedResourceDatabaseIds((current) => {
      const next = { ...current };
      if (databaseId) {
        next[resourceKey] = databaseId;
      } else {
        delete next[resourceKey];
      }
      return next;
    });
  }

  async function saveGeneratedWorkflowDesign() {
    if (!server?.serverId) {
      throw new Error("serverId is required");
    }
    if (currentWorkflowDesignDraftError) {
      throw new Error(currentWorkflowDesignDraftError);
    }
    if (!currentWorkflowDesignDraft) {
      throw new Error("WORKFLOW_DESIGN_DRAFT_INVALID");
    }
    const saved = await saveWorkflowDesignDraft({
      draft: currentWorkflowDesignDraft,
      record: activeWorkflowDesignDraft,
      serverId: server.serverId,
    });
    setActiveWorkflowDesignDraft(saved);
    setWorkflowDesignCompileResult(null);
    setWorkflowDesignDrafts((current) => [saved, ...current.filter((item) => item.draftId !== saved.draftId)]);
    return saved;
  }

  async function validateGeneratedWorkflowDesign(savedDraft?: WorkflowDesignDraftRecord) {
    const target = savedDraft || activeWorkflowDesignDraft;
    if (!target?.draftId || !server?.serverId) {
      throw new Error("WORKFLOW_DESIGN_DRAFT_REQUIRED");
    }
    const plan = await planWorkflowDesignDraft({ draftId: target.draftId, serverId: server.serverId });
    setWorkflowDesignPlan(plan);
    setWorkflowDesignPlanSignature(workflowDesignDraftSignature(target.draft));
    return plan;
  }

  async function saveAndValidateGeneratedWorkflowDesign() {
    if (workflowDesignBusy) return null;
    setWorkflowDesignBusy(true);
    setWorkflowDesignError("");
    try {
      setWorkflowDesignPlan(null);
      setWorkflowDesignPlanSignature("");
      setWorkflowDesignCompileResult(null);
      const saved = await saveGeneratedWorkflowDesign();
      return await validateGeneratedWorkflowDesign(saved);
    } catch (err) {
      const message = workflowErrorMessage(err, "保存或验证 WorkflowDesignDraft 失败");
      setWorkflowDesignError(message);
      throw err;
    } finally {
      setWorkflowDesignBusy(false);
    }
  }

  async function compileGeneratedWorkflowDesign() {
    if (workflowDesignBusy) return null;
    if (!server?.serverId) {
      throw new Error("serverId is required");
    }
    setWorkflowDesignBusy(true);
    setWorkflowDesignError("");
    setWorkflowDesignPlan(null);
    setWorkflowDesignPlanSignature("");
    setWorkflowDesignCompileResult(null);
    try {
      const saved = await saveGeneratedWorkflowDesign();
      const plan = await validateGeneratedWorkflowDesign(saved);
      if (!plan.valid) {
        const issue = plan.validationIssues[0];
        throw new Error(issue ? `${issue.code}: ${issue.message}` : "WORKFLOW_DESIGN_PLAN_INVALID");
      }
      const compiled = await compileWorkflowDesignDraft({ draftId: saved.draftId, serverId: server.serverId });
      setWorkflowDesignCompileResult(compiled);
      return compiled;
    } catch (err) {
      const message = workflowErrorMessage(err, "编译 WorkflowDesignDraft 失败");
      setWorkflowDesignError(message);
      throw err;
    } finally {
      setWorkflowDesignBusy(false);
    }
  }

  function openWorkflowDesignDraft(draftId: string) {
    const record = workflowDesignDrafts.find((item) => item.draftId === draftId);
    if (!record) {
      const message = `WORKFLOW_DESIGN_DRAFT_NOT_FOUND: ${draftId}`;
      setWorkflowDesignError(message);
      throw new Error(message);
    }
    setActiveWorkflowDesignDraft(record);
    setWorkflowDesignPlan(null);
    setWorkflowDesignPlanSignature("");
    setWorkflowDesignCompileResult(null);
    generatedBuilder.loadGraphDraft(workflowDesignDraftToGraphDraft(record.draft));
    generatedBuilder.loadResourceBindings(resourceIdsFromWorkflowDesignDraft(record));
  }

  async function submitRun() {
    if (!server || !canSubmit) return;
    if (!isGeneratedToolRun && !selectedPipelineId) {
      setSubmitError("当前流程不是可运行 pipeline，不能提交。");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    setSubmittedRun(null);
    setRunDetail(null);
    setActiveRunId("");
    try {
      let run: WorkflowRun;
      if (selectedPipelineId && !isGeneratedToolRun) {
        run = await submitPipelineWorkflowRun({
            server,
            projectId: selectedWorkflow?.id || "proj_workflow_ui",
            pipelineId: selectedPipelineId,
            files,
            sampleUploads,
            params,
            resourceBindings: workflowResourceBindings,
        });
      } else {
        const plan = currentWorkflowDesignPlan;
        if (!plan?.valid) {
          throw new Error("WORKFLOW_DESIGN_PLAN_REQUIRED");
        }
        const workflowRevisionId = currentWorkflowDesignCompileResult?.workflowRevisionId;
        if (!workflowRevisionId) {
          throw new Error("WORKFLOW_REVISION_ID_REQUIRED");
        }
        run = await submitWorkflowDesignRun({ server, files, plan, workflowRevisionId });
      }
      setSubmittedRun(run);
      setActiveRunId(run.runId);
      void loadRunHistory();
    } catch (err) {
      setSubmitError(workflowErrorMessage(err, "提交流程失败"));
    } finally {
      setSubmitting(false);
    }
  }

  async function loadSampleData() {
    if (!selectedPipelineId || isGeneratedToolRun || sampleLoading) return;
    setSampleLoading(true);
    setSubmitError("");
    try {
      const uploads = await uploadWorkflowSampleData(selectedPipelineId);
      setSampleUploads(uploads);
      setFiles([]);
    } catch (err) {
      setSubmitError(workflowErrorMessage(err, "准备示例数据失败"));
    } finally {
      setSampleLoading(false);
    }
  }

  function updateFiles(nextFiles: File[]) {
    setFiles(nextFiles);
    if (nextFiles.length > 0) {
      setSampleUploads([]);
    }
  }

  function selectRun(runId: string) {
    setActiveRunId(runId);
    const fromHistory = runHistory.find((r) => r.runId === runId);
    if (fromHistory) {
      setSubmittedRun(fromHistory);
    }
  }

  return {
    activeRunId,
    availableDatabases,
    canSubmit,
    catalog,
    error,
    files,
    loadSampleData,
    loadWorkspace,
    loading,
    params,
    runnableTools,
    generatedBuilder,
    addRecommendedWorkflowTool,
    generatedInputCount,
    workflowDesignBusy,
    workflowDesignCompileResult: currentWorkflowDesignCompileResult,
    workflowDesignDrafts,
    workflowDesignError: currentWorkflowDesignDraftError || workflowDesignError,
    workflowDesignPlan: currentWorkflowDesignPlan,
    isGeneratedToolRun,
    runDetail,
    runHistory,
    sampleLoading,
    sampleUploads,
    selectedResourceDatabaseIds,
    selectedWorkflow,
    selectedWorkflowId,
    selectedToolIds: generatedBuilder.selectedToolIds,
    selectedTools: generatedBuilder.selectedTools,
    activeWorkflowDesignDraft,
    server,
    selectRun,
    setFiles: updateFiles,
    setParams,
    setSelectedWorkflowId,
    setWorkflowResourceBinding,
    openWorkflowDesignDraft,
    compileGeneratedWorkflowDesign,
    saveAndValidateGeneratedWorkflowDesign,
    submitError,
    submitRun,
    submittedRun,
    submitting,
    workflowResources,
    missingRequiredResourceKeys,
  };
}

function resourceIdsFromWorkflowDesignDraft(record: WorkflowDesignDraftRecord): Record<string, string> {
  return Object.fromEntries(
    Object.entries(record.draft.resources.bindings || {})
      .map(([resourceKey, binding]) => [resourceKey, String(binding?.databaseId || "")])
      .filter(([, databaseId]) => databaseId)
  );
}

function workflowDesignDraftSignature(draft: unknown): string {
  return stableWorkflowDesignStringify(draft);
}

function stableWorkflowDesignStringify(draft: unknown): string {
  return JSON.stringify(sortWorkflowDesignValue(draft));
}

function sortWorkflowDesignValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortWorkflowDesignValue);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const record = value as Record<string, unknown>;
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, sortWorkflowDesignValue(record[key])])
  );
}
