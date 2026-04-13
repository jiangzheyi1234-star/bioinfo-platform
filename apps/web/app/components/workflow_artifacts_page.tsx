"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useWorkspaceShell } from "./workspace_shell_context";
import type { WorkflowArtifact, WorkflowRun } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toWorkflowArtifact, toWorkflowRun } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { formatDateTime, mapWorkflowRunStatus } from "./workflow_support";

export function WorkflowArtifactsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentProject, currentProjectId, setShellError } = useWorkspaceShell();

  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [artifacts, setArtifacts] = useState<WorkflowArtifact[]>([]);
  const [busy, setBusy] = useState(false);

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

  const fetchArtifacts = async (runId: string) => {
    if (!currentProjectId || !runId) {
      return;
    }
    setBusy(true);
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
      setBusy(false);
    }
  };

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
      return;
    }
    void fetchArtifacts(selectedRunId);
  }, [selectedRunId]);

  if (!currentProjectId || !currentProject) {
    return <WorkspaceEmptyState mark="Art" label="先选择一个项目" hint="Artifacts 会从当前项目的 workflow runs 拉取。" />;
  }

  return (
    <div className="project-workspace-content">
      <WorkspaceSectionHeader
        title="Artifacts"
        description="列出当前 workflow run 的 report、timeline、trace、dag 和 nextflow 日志。"
        aside={
          <button type="button" className="control-btn" disabled={!selectedRunId || busy} onClick={() => void fetchArtifacts(selectedRunId)}>
            {busy ? "拉取中..." : "刷新 Artifacts"}
          </button>
        }
      />

      <section className="workflow-run-layout">
        <div className="workflow-run-list">
          {runs.length === 0 ? <WorkspaceEmptyState mark="Run" label="当前项目还没有 workflow run" compact /> : null}
          {runs.map((run) => {
            const active = run.run_id === selectedRunId;
            return (
              <button
                key={run.run_id}
                type="button"
                className={`workflow-run-list-item${active ? " active" : ""}`}
                onClick={() => {
                  setSelectedRunId(run.run_id);
                  router.replace(`/artifacts?run_id=${encodeURIComponent(run.run_id)}`);
                }}
              >
                <div className="workflow-run-list-head">
                  <strong>{run.workflow_id || run.run_id}</strong>
                  <span>{mapWorkflowRunStatus(run.status)}</span>
                </div>
                <p>{formatDateTime(run.updated_at || run.created_at)}</p>
              </button>
            );
          })}
        </div>

        <div className="workflow-run-detail">
          {selectedRun ? (
            <>
              <WorkspaceSectionHeader
                title={`Artifacts · ${selectedRun.run_id}`}
                description={selectedRun.message || "Workflow artifacts"}
              />
              {artifacts.length === 0 ? (
                <WorkspaceEmptyState mark="NF" label="当前 run 还没有可见 artifacts" hint="先刷新 artifacts；如果仍为空，请确认远端 run 已生成 report/timeline/trace/dag。" compact />
              ) : (
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
              )}
            </>
          ) : (
            <WorkspaceEmptyState mark="Art" label="从左侧选择一个 workflow run" compact />
          )}
        </div>
      </section>
    </div>
  );
}
