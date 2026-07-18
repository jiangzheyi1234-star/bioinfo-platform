"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  Bot,
  CircleDot,
  ExternalLink,
  Loader2,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldCheck,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { AgentApprovalPanel, type AgentApprovalAction } from "./agent-approval-panel";
import { AgentEventTimeline } from "./agent-event-timeline";
import { AgentGoalComposer } from "./agent-goal-composer";
import { AgentPlanCard } from "./agent-plan-card";
import { AgentSessionObservationPanel } from "./agent-session-observation-panel";
import { AgentSessionList } from "./agent-session-list";
import {
  agentStatusLabel,
  shortAgentIdentity,
  type AgentSession,
  type AgentWorkbenchProblem,
} from "./agent-workbench-model";
import { useAgentWorkbenchState } from "./use-agent-workbench-state";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

export function AgentWorkbenchPage() {
  const state = useAgentWorkbenchState();
  const observationFrame = useMemo(
    () => ({ observedAtEpochMs: Date.now(), snapshot: state.snapshot }),
    [state.snapshot]
  );
  const approvalBusy = approvalBusyAction(state.busyAction);
  const commandBusy = Boolean(
    state.busyAction && state.busyAction !== "bootstrap" && state.busyAction !== "refresh"
  );

  return (
    <div className="relative h-full w-full overflow-y-auto bg-slate-50 px-4 py-6 text-slate-800 sm:px-6 sm:py-10 lg:px-8">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-[1480px] space-y-5">
        <WorkflowPageHeader
          title="Agent 工作台"
          leading={
            <div className="hidden items-center gap-2 text-xs text-slate-500 xl:flex">
              <Bot strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
              Goal → Plan → Approval → Revision
            </div>
          }
          actions={
            <Button
              type="button"
              variant="outline"
              className="h-9 bg-white"
              disabled={!state.server || Boolean(state.busyAction)}
              onClick={() => void state.refreshWorkspace(true)}
              data-testid="agent-workbench-refresh"
            >
              {state.refreshing ? (
                <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
              )}
              刷新权威状态
            </Button>
          }
        />

        <section
          className="grid gap-3 rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 via-white to-cyan-50 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center"
          aria-labelledby="agent-first-heading"
          data-testid="agent-first-intro"
        >
          <div className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-blue-200 bg-white text-blue-700">
              <ShieldCheck strokeWidth={1.5} className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <h2 id="agent-first-heading" className="text-sm font-semibold text-slate-950">
                先描述科研目标，再审查可执行方案
              </h2>
              <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-600">
                Agent 只生成类型化 WorkflowDesignDraft。Plan Card、人工审批、不可变 WorkflowRevision
                和 hash-chain 事件是主控制面；DAG 仅作为方案里的只读专家投影。
              </p>
            </div>
          </div>
          <ServerIdentity server={state.server} loading={state.loading} />
        </section>

        {state.problem ? (
          <ProblemNotice
            problem={state.problem}
            refreshing={state.refreshing}
            onRefresh={() => void state.refreshWorkspace(true)}
          />
        ) : null}

        <p className="sr-only" aria-live="polite" aria-atomic="true" data-testid="agent-workbench-status">
          {state.statusMessage}
        </p>

        <div className="grid items-start gap-4 xl:grid-cols-[260px_minmax(540px,1fr)_360px]">
          <AgentSessionList
            activeSessionId={state.selectedSession?.sessionId}
            disabled={Boolean(state.busyAction)}
            loading={state.loading}
            refreshing={state.refreshing}
            sessions={state.sessions}
            onRefresh={() => state.refreshWorkspace(true)}
            onSelect={state.selectSession}
            onStartNew={state.startNew}
          />

          <section
            className="min-w-0 space-y-4"
            aria-label="Agent 工作台主内容"
            data-testid="agent-workbench-main"
          >
            {state.selectedSession ? (
              <>
                <SessionSummary session={state.selectedSession} />

                {state.currentPlan ? (
                  <AgentPlanCard plan={state.currentPlan} parentPlan={state.parentPlan} />
                ) : state.loading ? (
                  <LoadingPanel label="正在读取结构化方案" />
                ) : (
                  <NoPlanPanel
                    session={state.selectedSession}
                    busy={state.busyAction === "plan"}
                    onResume={() => void state.resumePlanning()}
                  />
                )}

                <AgentApprovalPanel
                  busyAction={approvalBusy}
                  error={state.problem?.message || ""}
                  plan={state.currentPlan}
                  session={state.selectedSession}
                  onApprove={state.approve}
                  onCancel={state.cancel}
                  onRefresh={() => state.refreshWorkspace(true)}
                  onRequestChanges={state.requestChanges}
                  onStartNew={state.startNewFromCurrent}
                />
              </>
            ) : state.requestedSessionId ? (
              state.loading ? (
                <LoadingPanel label={`正在恢复会话 ${state.requestedSessionId}`} />
              ) : (
                <SessionUnavailablePanel
                  sessionId={state.requestedSessionId}
                  onRefresh={() => void state.refreshWorkspace(true)}
                  onStartNew={state.startNew}
                />
              )
            ) : state.loading ? (
              <LoadingPanel label="正在恢复 Agent 工作台" />
            ) : (
              <AgentGoalComposer
                key={state.composerPrefill.version}
                busy={state.busyAction === "create" || state.busyAction === "plan"}
                disabled={!state.server?.ready || commandBusy}
                initialBudget={state.composerPrefill.budget}
                initialProjectId={state.composerPrefill.projectId}
                initialSuccessCriterion={state.composerPrefill.successCriterion}
                initialSummary={state.composerPrefill.summary}
                onSubmit={state.submitGoal}
              />
            )}
          </section>

          <div className="min-w-0 space-y-4 xl:sticky xl:top-4">
            {observationFrame.snapshot ? (
              <AgentSessionObservationPanel
                observedAtEpochMs={observationFrame.observedAtEpochMs}
                snapshot={observationFrame.snapshot}
              />
            ) : null}
            <AgentEventTimeline
              events={state.snapshot?.events || []}
              loading={state.loading && Boolean(state.selectedSession)}
              refreshing={state.refreshing}
              statusMessage={state.statusMessage}
              onRefresh={
                state.selectedSession && !state.busyAction
                  ? () => state.refreshWorkspace(true)
                  : undefined
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function ServerIdentity({ loading, server }: { loading: boolean; server: ReturnType<typeof useAgentWorkbenchState>["server"] }) {
  if (loading && !server) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
        正在解析远程 runner
      </div>
    );
  }
  if (!server) {
    return <div className="text-xs font-medium text-red-700">未绑定可用 runner</div>;
  }
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 text-xs" data-testid="agent-server-identity">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-white px-2.5 py-1 font-medium text-emerald-700">
        <CircleDot strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
        connected · ready
      </span>
      <span className="max-w-64 truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 font-mono text-slate-600" title={server.serverId}>
        {server.label || shortAgentIdentity(server.serverId, 22)}
      </span>
    </div>
  );
}

function ProblemNotice({
  onRefresh,
  problem,
  refreshing,
}: {
  onRefresh: () => void;
  problem: AgentWorkbenchProblem;
  refreshing: boolean;
}) {
  return (
    <Alert variant="destructive" className="bg-white" data-testid="agent-workbench-problem">
      <AlertTitle>Agent 控制面需要处理</AlertTitle>
      <AlertDescription>
        <p>{problem.message}</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px]">
          {problem.code ? <span>code={problem.code}</span> : null}
          {problem.reasonCode ? <span>reason={problem.reasonCode}</span> : null}
          {problem.status ? <span>HTTP {problem.status}</span> : null}
        </div>
        {problem.nextAction ? <p className="mt-2 text-xs">下一步：{problem.nextAction}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={refreshing} onClick={onRefresh}>
            <RefreshCw strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
            刷新后重审
          </Button>
          <Button asChild type="button" size="sm" variant="outline">
            <Link href="/workflows/tools">
              检查工具能力
              <ExternalLink strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

function SessionSummary({ session }: { session: AgentSession }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white px-5 py-4" data-testid="agent-session-summary">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">科研目标</div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">{session.goal.summary}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {session.goal.successCriteria.join(" · ") || "未记录成功标准"}
          </p>
        </div>
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          {agentStatusLabel(session.status)}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 border-t border-slate-100 pt-3 text-xs sm:grid-cols-3">
        <SummaryFact label="session" value={session.sessionId} />
        <SummaryFact label="project" value={session.projectId} />
        <SummaryFact label="state" value={`v${session.stateVersion} · plan g${session.planGeneration}`} />
      </dl>
    </section>
  );
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-400">{label}</dt>
      <dd className="mt-0.5 truncate font-mono text-slate-700" title={value}>{value}</dd>
    </div>
  );
}

function NoPlanPanel({
  busy,
  onResume,
  session,
}: {
  busy: boolean;
  onResume: () => void;
  session: AgentSession;
}) {
  const recoverable = session.status === "created" || session.status === "planning";
  return (
    <section className="rounded-xl border border-dashed border-slate-300 bg-white px-5 py-8 text-center" data-testid="agent-plan-empty">
      {busy ? (
        <Loader2 strokeWidth={1.5} className="mx-auto h-6 w-6 animate-spin text-blue-600" aria-hidden="true" />
      ) : (
        <RotateCcw strokeWidth={1.5} className="mx-auto h-6 w-6 text-slate-400" aria-hidden="true" />
      )}
      <h2 className="mt-3 text-sm font-semibold text-slate-900">
        {session.status === "planning" ? "规划已持久化，等待恢复" : "尚无可审查 PlanRevision"}
      </h2>
      <p className="mx-auto mt-1 max-w-xl text-xs leading-5 text-slate-500">
        恢复会复用本地保存的命令；若远程已写入 plan_requested，则从事件的 requestId、idempotencyKey
        和原 expectedStateVersion 重放，不重新猜测 proposal。
      </p>
      {recoverable ? (
        <Button type="button" className="mt-4" disabled={busy} onClick={onResume} data-testid="agent-resume-plan">
          {busy ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RotateCcw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />}
          恢复同一规划命令
        </Button>
      ) : null}
    </section>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500">
      <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

function SessionUnavailablePanel({
  onRefresh,
  onStartNew,
  sessionId,
}: {
  onRefresh: () => void;
  onStartNew: () => void;
  sessionId: string;
}) {
  return (
    <section className="rounded-xl border border-red-200 bg-white px-5 py-8 text-center" data-testid="agent-session-unavailable">
      <Server strokeWidth={1.5} className="mx-auto h-6 w-6 text-red-500" aria-hidden="true" />
      <h2 className="mt-3 text-sm font-semibold text-slate-950">无法恢复 URL 指定的会话</h2>
      <p className="mx-auto mt-1 max-w-xl break-all font-mono text-xs text-slate-500">{sessionId}</p>
      <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-slate-600">
        不会把读取失败退化成空白目标表单。请刷新同一 runner 的权威状态，或明确开始新会话。
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <Button type="button" variant="outline" onClick={onRefresh}>
          <RefreshCw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
          刷新同一 runner
        </Button>
        <Button type="button" onClick={onStartNew}>明确新建会话</Button>
      </div>
    </section>
  );
}

function approvalBusyAction(action: string): AgentApprovalAction {
  if (
    action === "approve" ||
    action === "request_changes" ||
    action === "cancel" ||
    action === "refresh"
  ) {
    return action;
  }
  return action ? "busy" : "";
}
