"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useWorkspaceShell } from "./workspace_shell_context";
import type { WorkflowRun } from "./detection_workspace_types";
import { apiBase, readJsonOrThrow, safeText, toWorkflowRun } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { formatDateTime, mapWorkflowRunStatus } from "./workflow_support";

function readRemoteValue(run: WorkflowRun, key: string): string {
  const value = run.remote_status && typeof run.remote_status[key] !== "undefined" ? run.remote_status[key] : "";
  return safeText(value);
}

export function WorkflowRunsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { currentProject, currentProjectId, setShellError } = useWorkspaceShell();

  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState("");

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
      return;
    }
    void refreshRunDetail(selectedRunId);
  }, [selectedRunId]);

  if (!currentProjectId || !currentProject) {
    return <WorkspaceEmptyState mark="Run" label="先选择一个项目" hint="Run 记录会绑定到当前项目目录。" />;
  }

  return (
    <div className="project-workspace-content">
      <WorkspaceSectionHeader
        title="Runs"
        description="查看当前项目的 workflow runs、远端状态、日志尾部与取消动作。"
        aside={
          <button type="button" className="control-btn" onClick={() => void refreshRuns(selectedRunId)}>
            刷新列表
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
                  router.replace(`/runs?run_id=${encodeURIComponent(run.run_id)}`);
                }}
              >
                <div className="workflow-run-list-head">
                  <strong>{run.workflow_id || run.run_id}</strong>
                  <span>{mapWorkflowRunStatus(run.status)}</span>
                </div>
                <p>{run.message || "暂无说明"}</p>
                <span className="muted">{formatDateTime(run.updated_at || run.created_at)}</span>
              </button>
            );
          })}
        </div>

        <div className="workflow-run-detail">
          {selectedRun ? (
            <>
              <WorkspaceSectionHeader
                title={selectedRun.run_id}
                description={selectedRun.message || "Workflow run detail"}
                aside={
                  <div className="workflow-run-detail-actions">
                    <button type="button" className="control-btn" disabled={detailBusy} onClick={() => void refreshRunDetail(selectedRun.run_id)}>
                      {detailBusy ? "刷新中..." : "刷新状态"}
                    </button>
                    <button
                      type="button"
                      className="control-btn"
                      disabled={actionBusy === selectedRun.run_id || ["completed", "failed", "cancelled"].includes(selectedRun.status)}
                      onClick={() => void cancelRun(selectedRun.run_id)}
                    >
                      {actionBusy === selectedRun.run_id ? "取消中..." : "取消 Run"}
                    </button>
                  </div>
                }
              />
              <div className="workflow-run-meta-grid">
                <div className="workflow-run-meta-card">
                  <strong>Profile</strong>
                  <span>{selectedRun.profile_id}</span>
                </div>
                <div className="workflow-run-meta-card">
                  <strong>Bundle</strong>
                  <span>{selectedRun.bundle_id || "未记录"}</span>
                </div>
                <div className="workflow-run-meta-card">
                  <strong>Launcher PID</strong>
                  <span>{selectedRun.launcher_pid || "未记录"}</span>
                </div>
                <div className="workflow-run-meta-card">
                  <strong>Nextflow PID</strong>
                  <span>{selectedRun.nextflow_pid || readRemoteValue(selectedRun, "nextflow_pid") || "未记录"}</span>
                </div>
              </div>
              <div className="workflow-preview-grid">
                <div className="workflow-preview-card">
                  <strong>Remote Status</strong>
                  <pre className="workspace-json-surface">
                    {JSON.stringify(selectedRun.remote_status || {}, null, 2)}
                  </pre>
                </div>
                <div className="workflow-preview-card">
                  <strong>Run Paths</strong>
                  <pre className="workspace-json-surface">
                    {JSON.stringify(
                      {
                        local_bundle_dir: selectedRun.local_bundle_dir || "",
                        remote_task_dir: selectedRun.remote_task_dir || "",
                        remote_bundle_dir: selectedRun.remote_bundle_dir || "",
                        remote_work_dir: selectedRun.remote_work_dir || "",
                      },
                      null,
                      2
                    )}
                  </pre>
                </div>
                <div className="workflow-preview-card">
                  <strong>Log Tail</strong>
                  <pre className="workspace-json-surface">{readRemoteValue(selectedRun, "log_tail") || "暂无日志"}</pre>
                </div>
              </div>
            </>
          ) : (
            <WorkspaceEmptyState mark="Run" label="从左侧选择一个 workflow run" hint="提交新的 workflow run 后，会自动出现在这里。" />
          )}
        </div>
      </section>
    </div>
  );
}
