"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  fetchRunsList,
  fetchWorkflowCatalog,
  fetchWorkflowDatabases,
  fetchWorkflowRunDetail,
  fetchWorkflowServer,
  fetchWorkflowTools,
  getCachedWorkflowCatalog,
  getCachedWorkflowServer,
  submitGeneratedWorkflowRun,
  submitPipelineWorkflowRun,
  uploadWorkflowSampleData,
} from "./workflows-page-api";
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
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([]);
  const [selectedDatabaseIds, setSelectedDatabaseIds] = useState<string[]>([]);
  const [selectedResourceDatabaseIds, setSelectedResourceDatabaseIds] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [sampleUploads, setSampleUploads] = useState<WorkflowUpload[]>([]);
  const [sampleLoading, setSampleLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submittedRun, setSubmittedRun] = useState<WorkflowRun | null>(null);
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [runDetailError, setRunDetailError] = useState("");
  const [runHistory, setRunHistory] = useState<WorkflowRun[]>([]);
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
      const runnableTools = selectableTools(nextTools);
      setTools(nextTools);
      setSelectedToolIds((current) => current.length > 0 ? current : runnableTools[0]?.id ? [runnableTools[0].id] : []);
    }
    if (databasesResult.status === "fulfilled") {
      setDatabases(databasesResult.value);
    }
    if (serverResult.status === "fulfilled") {
      setServer(serverResult.value);
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
  const isGeneratedToolRun = selectedPipelineId === "generated-tool-run-v1" || !selectedPipelineId;

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
  const workflowResources = useMemo(() => workflowResourceEntries(selectedWorkflow), [selectedWorkflow]);
  const selectedTools = runnableTools.filter((tool) => selectedToolIds.includes(tool.id));
  const selectedDatabases = availableDatabases.filter((database) => selectedDatabaseIds.includes(database.id));
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
      (!isGeneratedToolRun || selectedTools.length > 0) &&
      (isGeneratedToolRun || missingRequiredResourceKeys.length === 0) &&
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
          setRunDetailError("");
        }
      } catch (err) {
        if (!cancelled) {
          setRunDetailError(workflowErrorMessage(err, "读取运行详情失败"));
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

  function toggleTool(id: string) {
    setSelectedToolIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleDatabase(id: string) {
    setSelectedDatabaseIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

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

  async function submitRun() {
    if (!server || !canSubmit) return;
    setSubmitting(true);
    setSubmitError("");
    setSubmittedRun(null);
    setRunDetail(null);
    setActiveRunId("");
    try {
      const run = selectedPipelineId && !isGeneratedToolRun
        ? await submitPipelineWorkflowRun({
            server,
            projectId: selectedWorkflow?.id || "proj_workflow_ui",
            pipelineId: selectedPipelineId,
            files,
            sampleUploads,
            params,
            resourceBindings: workflowResourceBindings,
          })
        : await submitGeneratedWorkflowRun({
            server,
            projectId: selectedWorkflow?.id || "proj_workflow_ui",
            files,
            tools: selectedTools,
            databases: selectedDatabases,
          });
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
    isGeneratedToolRun,
    runDetail,
    runDetailError,
    runHistory,
    sampleLoading,
    sampleUploads,
    selectedDatabaseIds,
    selectedDatabases,
    selectedResourceDatabaseIds,
    selectedWorkflow,
    selectedWorkflowId,
    selectedToolIds,
    selectedTools,
    server,
    selectRun,
    setFiles: updateFiles,
    setParams,
    setSelectedWorkflowId,
    setWorkflowResourceBinding,
    submitError,
    submitRun,
    submittedRun,
    submitting,
    toggleDatabase,
    toggleTool,
    workflowResources,
    missingRequiredResourceKeys,
  };
}
