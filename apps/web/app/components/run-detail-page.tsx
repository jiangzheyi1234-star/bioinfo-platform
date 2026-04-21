"use client";

import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection, StatusBadge } from "./workspace-primitives";
import { useRunDetailData } from "./workspace-live-data";

export function RunDetailPage({ runId }: { runId: string }) {
  const { run, events, artifacts, logLines, runSpec, error } = useRunDetailData(runId);

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        eyebrow="Run"
        breadcrumbs={[{ label: "Runs", href: "/runs" }, { label: run.runId }]}
        title={`Run ${run.runId}`}
        description={`${run.projectLabel} · ${run.serverLabel}`}
        actions={
          <>
            <WorkspaceActionButton leadingIcon="copy">Copy requestId</WorkspaceActionButton>
            <WorkspaceActionButton>Refresh</WorkspaceActionButton>
            <WorkspaceActionButton href="/results">Open in Results</WorkspaceActionButton>
          </>
        }
      />

      <SummaryStrip
        items={[
          { label: "Pipeline", value: run.pipelineId },
          { label: "Stage", value: run.stage },
          { label: "State Version", value: `v${run.stateVersion}` },
          { label: "Started / Finished", value: `${run.startedAt ?? "—"} → ${run.finishedAt ?? "—"}` },
          { label: "Request ID", value: run.requestId },
        ]}
      />

      <div className="flex flex-wrap gap-2 rounded-2xl bg-slate-50 p-2">
        {["Overview", "Events", "Logs", "Outputs", "Spec"].map((tab, index) => (
          <div
            key={tab}
            className={index === 0 ? "rounded-xl bg-white px-4 py-2 text-sm font-medium text-slate-900 shadow-sm" : "rounded-xl px-4 py-2 text-sm text-slate-500"}
          >
            {tab}
          </div>
        ))}
      </div>

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">
          Failed to load live run data · {error}
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
        <div className="space-y-5">
          <WorkspaceSection title="Overview" description="Run 对象页优先表达状态真相，而不是让日志面板接管页面。">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-2xl bg-slate-50 p-4">
                <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-400">Status</p>
                <div className="mt-3 flex items-center gap-3">
                  <StatusBadge status={run.status} />
                  <span className="text-sm text-slate-700">{run.message}</span>
                </div>
                <p className="mt-3 text-[12px] text-slate-500">lastUpdatedAt · {run.lastUpdatedAt}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 p-4">
                <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-slate-400">Runtime context</p>
                <dl className="mt-3 space-y-2 text-sm text-slate-700">
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">serverId</dt><dd>{run.serverId ?? run.serverLabel}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">pipelineId</dt><dd>{run.pipelineId}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">runSpecVersion</dt><dd>{run.runSpecVersion ?? "2026-04-21"}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-slate-500">resultDir</dt><dd className="truncate">{run.resultDir || "—"}</dd></div>
                </dl>
              </div>
            </div>

            {run.lastError ? (
              <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50/70 p-4">
                <p className="text-[12px] font-semibold uppercase tracking-[0.12em] text-rose-500">Last Error</p>
                <p className="mt-2 text-sm font-medium text-rose-900">{run.lastError.code}</p>
                <p className="mt-2 text-sm leading-6 text-rose-800">{run.lastError.message}</p>
                <p className="mt-2 text-[12px] text-rose-700">scope · {run.lastError.scope} · requestId · {run.lastError.requestId}</p>
              </div>
            ) : null}
          </WorkspaceSection>

          <WorkspaceSection title="Events" description="事件流保留状态迁移、stateVersion 与 requestId，方便后续排障。">
            <div className="space-y-3">
              {events.map((event) => (
                <div key={event.eventId} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm text-slate-900">
                    <span className="font-medium">{event.eventType}</span>
                    <span className="text-slate-300">·</span>
                    <span>{event.stage}</span>
                    <span className="text-slate-300">·</span>
                    <span className="text-slate-500">v{event.stateVersion}</span>
                  </div>
                  <p className="mt-1 text-sm text-slate-600">{event.message}</p>
                  <p className="mt-2 text-[12px] text-slate-500">{event.createdAt} · {event.requestId}</p>
                </div>
              ))}
            </div>
          </WorkspaceSection>
        </div>

        <div className="space-y-5">
          <WorkspaceSection title="Logs" description="日志是对象页子视图，而不是一个抢占注意力的巨大黑框。">
            <div className="rounded-2xl border border-slate-200 bg-white">
              <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
                <div className="flex items-center gap-2">
                  <span className="rounded-lg bg-slate-100 px-3 py-1 text-slate-900">stdout</span>
                  <span className="rounded-lg px-3 py-1">stderr</span>
                </div>
                <div className="flex items-center gap-2">
                  <WorkspaceActionButton>Refresh</WorkspaceActionButton>
                  <WorkspaceActionButton>Copy</WorkspaceActionButton>
                </div>
              </div>
              <div className="space-y-2 px-4 py-4 font-mono text-[12px] leading-6 text-slate-600">
                {logLines.map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            </div>
          </WorkspaceSection>

          <WorkspaceSection title="Outputs" description="Artifacts 列表保持轻量，预览入口优先。">
            <div className="space-y-2">
              {artifacts.map((artifact) => (
                <div key={artifact.artifactId} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-900">{artifact.name ?? artifact.path.split("/").pop()}</p>
                      <p className="truncate text-[12px] text-slate-500">{artifact.path}</p>
                    </div>
                    <div className="text-right text-[12px] text-slate-500">
                      <p>{artifact.kind}</p>
                      <p>{artifact.size ?? `${artifact.sizeBytes ?? 0} bytes`}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </WorkspaceSection>

          <WorkspaceSection title="Spec" description="Structured execution 是 v1 的核心约束，Spec 视图要看起来像对象，而不是脚本。">
            <pre className="overflow-auto rounded-2xl bg-slate-950 px-4 py-4 text-[12px] leading-6 text-slate-100">
              {JSON.stringify(runSpec, null, 2)}
            </pre>
          </WorkspaceSection>
        </div>
      </div>
    </div>
  );
}
