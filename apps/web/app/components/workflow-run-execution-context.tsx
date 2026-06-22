"use client";

import type { ReactNode } from "react";
import { Activity, Clock, Loader2, RotateCcw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WorkflowRunExecutionAttempt, WorkflowRunExecutionContext } from "./workflows-page-model";

type MetricProps = {
  label: string;
  value: string;
  icon?: ReactNode;
};

function ExecutionMetric({ label, value, icon }: MetricProps) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
        {icon}
        {label}
      </div>
      <div className="mt-1 truncate text-sm font-medium text-slate-900">{value}</div>
    </div>
  );
}

function formatDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function durationText(startedAt?: string, finishedAt?: string) {
  if (!startedAt || !finishedAt) return "—";
  const seconds = Math.max(0, Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function policyNumber(policy: Record<string, unknown> | null | undefined, key: string) {
  const value = policy?.[key];
  return typeof value === "number" ? value : Number.isFinite(Number(value)) ? Number(value) : null;
}

function latestAttempts(attempts: WorkflowRunExecutionAttempt[]) {
  return [...attempts].sort((left, right) => (right.attemptNumber || 0) - (left.attemptNumber || 0)).slice(0, 3);
}

function retryLabel(context: WorkflowRunExecutionContext) {
  const retry = context.retryEligibility;
  const reason = retry?.reasonCode || "—";
  if (retry?.eligibleNow) return `可调度 · ${reason}`;
  if (retry?.eligible) return `等待 · ${reason}`;
  return reason;
}

function attemptLabel(context: WorkflowRunExecutionContext) {
  const used = context.job?.attemptCount ?? context.attempts?.length ?? 0;
  const max = context.job?.maxAttempts ?? policyNumber(context.retryPolicy, "maxAttempts") ?? 0;
  return max > 0 ? `${used} / ${max}` : String(used);
}

function leaseLabel(context: WorkflowRunExecutionContext) {
  const lease = context.activeLease || context.currentLease;
  if (!lease) return "—";
  return `${lease.state || "unknown"} · gen ${lease.leaseGeneration ?? "—"}`;
}

function attemptStateClass(state?: string) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "succeeded") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "failed" || normalized === "fenced") return "border-red-200 bg-red-50 text-red-700";
  if (normalized === "running") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

export function WorkflowRunExecutionContextPanel({
  context,
  onRetryRun,
  retrying = false,
}: {
  context?: WorkflowRunExecutionContext;
  onRetryRun?: () => void;
  retrying?: boolean;
}) {
  if (!context) return null;
  const attempts = context.attempts || [];
  const retryBackoff = policyNumber(context.retryPolicy, "backoffSeconds");
  const lease = context.activeLease || context.currentLease;
  const retryReason = context.retryEligibility?.reasonCode || "RUN_RETRY_UNAVAILABLE";
  const retryEnabled = Boolean(context.retryEligibility?.eligibleNow && onRetryRun);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-slate-900">执行上下文</div>
        <div className="flex items-center gap-2">
          {onRetryRun ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={!retryEnabled || retrying}
              title={retryReason}
              onClick={onRetryRun}
            >
              {retrying ? (
                <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw strokeWidth={1.5} className="mr-1 h-3 w-3" />
              )}
              重试
            </Button>
          ) : null}
          <div className="font-mono text-[11px] text-slate-400">{context.schemaVersion || "run-execution-context"}</div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <ExecutionMetric label="attempt" value={attemptLabel(context)} icon={<Activity strokeWidth={1.5} className="h-3 w-3" />} />
        <ExecutionMetric label="retry" value={retryLabel(context)} icon={<RotateCcw strokeWidth={1.5} className="h-3 w-3" />} />
        <ExecutionMetric label="lease" value={leaseLabel(context)} icon={<ShieldCheck strokeWidth={1.5} className="h-3 w-3" />} />
        <ExecutionMetric label="next" value={formatDateTime(context.retryEligibility?.nextAttemptAt)} icon={<Clock strokeWidth={1.5} className="h-3 w-3" />} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <div className="mb-2 text-[11px] font-medium text-slate-400">attempt history</div>
          {attempts.length === 0 ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-400">暂无 attempt</div>
          ) : (
            <div className="space-y-2">
              {latestAttempts(attempts).map((attempt) => (
                <div key={attempt.attemptId} className="grid gap-2 rounded-md border border-slate-200 px-3 py-2 text-xs sm:grid-cols-[96px_minmax(0,1fr)_88px]">
                  <span className={`w-fit rounded border px-1.5 py-0.5 font-medium ${attemptStateClass(attempt.state)}`}>
                    {attempt.state || "unknown"}
                  </span>
                  <div className="min-w-0">
                    <div className="truncate font-mono text-slate-600">{attempt.attemptId || "—"}</div>
                    <div className="mt-0.5 truncate text-[11px] text-slate-400">
                      worker {attempt.workerId || "—"} · slot {attempt.slotId || "—"}
                    </div>
                  </div>
                  <div className="text-right font-mono text-[11px] text-slate-500">
                    <div>#{attempt.attemptNumber ?? "—"} / gen {attempt.leaseGeneration ?? "—"}</div>
                    <div>{durationText(attempt.startedAt, attempt.finishedAt)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <div className="mb-2 text-[11px] font-medium text-slate-400">policy</div>
          <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-y-1">
            <span>queue</span>
            <span className="truncate font-mono text-slate-800">{context.job?.queueName || "—"}</span>
            <span>backoff</span>
            <span className="font-mono text-slate-800">{retryBackoff === null ? "—" : `${retryBackoff}s`}</span>
            <span>remaining</span>
            <span className="font-mono text-slate-800">{context.retryEligibility?.remainingAttempts ?? "—"}</span>
            <span>resume</span>
            <span className="truncate font-mono text-slate-800">{context.resumeEligibility?.reasonCode || "—"}</span>
            <span>heartbeat</span>
            <span className="truncate font-mono text-slate-800">{formatDateTime(lease?.heartbeatAt)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
