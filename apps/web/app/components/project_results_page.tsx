"use client";

import { useEffect, useState } from "react";

import { apiBase, readJsonOrThrow, safeText } from "./detection_workspace_utils";
import { WorkspaceEmptyState, WorkspaceSectionHeader } from "./workspace_section_primitives";
import { useWorkspaceShell } from "./workspace_shell_context";

function formatTs(value: number): string {
  if (!value) {
    return "未记录";
  }
  return new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });
}

export function ProjectResultsPage() {
  const { currentProjectId, setShellError } = useWorkspaceShell();
  const [resultRows, setResultRows] = useState<Array<Record<string, unknown>>>([]);

  const refreshResults = async (projectId: string) => {
    if (!projectId) {
      setResultRows([]);
      return;
    }
    const resp = await fetch(`${apiBase()}/api/v1/projects/${encodeURIComponent(projectId)}/results`);
    const data = await readJsonOrThrow(resp);
    setResultRows(Array.isArray(data.items) ? data.items : []);
  };

  useEffect(() => {
    void (async () => {
      try {
        await refreshResults(currentProjectId);
      } catch (err) {
        setShellError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [currentProjectId, setShellError]);

  return (
    <section className="grid gap-[18px]">
      {resultRows.length === 0 ? (
        <WorkspaceEmptyState mark="Res" label="当前项目暂无可展示结果" hint="先创建任务并执行工具，再回到这里查看聚合结果。" />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {resultRows.map((row) => (
            <article key={safeText(row.task_id, safeText(row.title))} className="panel p-4">
              <WorkspaceSectionHeader
                title={safeText(row.title, safeText(row.task_id))}
                description={safeText(row.summary, "暂无摘要")}
                aside={<span className="badge">{safeText(row.task_status, "pending")}</span>}
                titleAs="h4"
              />
              <div className="grid gap-3">
                <div className="row border-t border-[var(--workspace-line-soft)] pt-0 first:border-t-0">
                  <span>最新执行</span>
                  <strong>{safeText(row.latest_execution_id, "暂无")}</strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>最近工具</span>
                  <strong>{safeText(row.latest_tool_id, "未记录")}</strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>执行统计</span>
                  <strong>
                    {safeText(row.completed_count, "0")} completed / {safeText(row.failed_count, "0")} failed
                  </strong>
                </div>
                <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                  <span>最近活动</span>
                  <strong>{formatTs(Number(row.last_activity_at || 0))}</strong>
                </div>
                {safeText(row.latest_error) ? (
                  <div className="row border-t border-[var(--workspace-line-soft)] pt-3">
                    <span>最近错误</span>
                    <strong>{safeText(row.latest_error)}</strong>
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
