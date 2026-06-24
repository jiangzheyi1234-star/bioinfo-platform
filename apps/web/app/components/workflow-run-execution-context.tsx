"use client";

import type { ReactNode } from "react";
import { Activity, Clock, Loader2, RotateCcw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import type {
  WorkflowRunExecutionAttempt,
  WorkflowRunExecutionContext,
  WorkflowRunRuleRetryExecutionPlan,
  WorkflowRunRuleRetryPlanRuleRef,
} from "./workflows-page-model";

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

function ruleRefKey(rule: WorkflowRunRuleRetryPlanRuleRef) {
  return rule.runtimeStatusKey || rule.stepId || rule.ruleName || "";
}

function uniqueRuleRefs(rules: WorkflowRunRuleRetryPlanRuleRef[]) {
  const seen = new Set<string>();
  return rules.filter((rule) => {
    const key = ruleRefKey(rule);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function ruleNameList(rules: WorkflowRunRuleRetryPlanRuleRef[]) {
  return uniqueRuleRefs(rules)
    .map((rule) => rule.ruleName || rule.stepId || rule.runtimeStatusKey)
    .filter(Boolean)
    .slice(0, 4)
    .join(", ");
}

function compactList(values: string[] | undefined, fallback = "—") {
  const items = (values || []).filter(Boolean);
  if (items.length === 0) return fallback;
  const shown = items.slice(0, 4).join(", ");
  return items.length > 4 ? `${shown}, +${items.length - 4}` : shown;
}

function RuleRetryPlanSummary({ context }: { context: WorkflowRunExecutionContext }) {
  const plan = context.ruleRetryPlan;
  if (!plan || !plan.failedRuleCount) return null;
  const plannedRules = plan.rules || [];
  const downstreamRules = uniqueRuleRefs(plannedRules.flatMap((rule) => rule.downstreamInvalidation?.rules || []));
  const rerunRules = uniqueRuleRefs(plannedRules.flatMap((rule) => rule.rerunScope?.rules || [rule]));
  const reason = plan.reasonCode || plannedRules[0]?.reasonCode || "—";
  const downstreamLabel = downstreamRules.length > 0 ? ruleNameList(downstreamRules) : "—";
  const scopeLabel = rerunRules.length > 0 ? ruleNameList(rerunRules) : "—";
  const selectedAttemptCount = plan.selectedAttemptCount ?? plannedRules.filter((rule) => rule.selectedAttempt?.attemptId).length;
  const adoptionEnabled = Boolean(plan.cacheAdoptionBoundary?.enabled || plan.artifactAdoptionBoundary?.enabled);
  const selectedAttemptLabel =
    plannedRules
      .map((rule) => rule.selectedAttempt)
      .filter((attempt) => attempt?.attemptId)
      .slice(0, 3)
      .map((attempt) => `#${attempt?.attemptNumber ?? "—"} gen ${attempt?.leaseGeneration ?? "—"}`)
      .join(", ") || "—";

  return (
    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <RotateCcw strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">rule retry plan</span>
          <span className="truncate font-mono text-[11px] text-amber-700">{plan.schemaVersion || "rule-retry-plan"}</span>
        </div>
        <span className="rounded border border-amber-300 bg-white/60 px-1.5 py-0.5 font-mono text-[11px] text-amber-800">
          {plan.invalidationPlanAvailable ? "invalidation planned" : "blocked"}
        </span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <ExecutionMetric label="failed" value={String(plan.failedRuleCount || 0)} />
        <ExecutionMetric label="selected" value={String(selectedAttemptCount)} />
        <ExecutionMetric label="scope" value={String(rerunRules.length)} />
        <ExecutionMetric label="downstream" value={String(downstreamRules.length)} />
        <ExecutionMetric label="reason" value={reason} />
      </div>
      <p className="mt-2 text-[11px] leading-5 text-amber-800">
        规则级重试计划仅供诊断；当前重试按钮会重新调度整个 run。
      </p>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[96px_minmax(0,1fr)]">
        <span className="text-amber-700">selection</span>
        <span className="truncate font-mono">planned only · {selectedAttemptLabel}</span>
        <span className="text-amber-700">adoption</span>
        <span className="truncate font-mono">{adoptionEnabled ? "enabled" : "not enabled"}</span>
        <span className="text-amber-700">downstream</span>
        <span className="truncate font-mono">{downstreamLabel}</span>
        <span className="text-amber-700">rerun scope</span>
        <span className="truncate font-mono">{scopeLabel}</span>
      </div>
    </div>
  );
}

function RuleRetryExecutionPlanPreview({ plan }: { plan?: WorkflowRunRuleRetryExecutionPlan }) {
  if (!plan) return null;
  const options = plan.snakemakeOptions;
  const argsPreview = options?.argsPreview || [];
  const forcerunRules = options?.forcerunRules || [];
  const unsafeFlags = options?.unsafeFlagsProhibited || [];
  const selectedRules = plan.selectedRules || [];
  const rerunRules = uniqueRuleRefs(plan.rerunScope?.rules || []);
  const blockers = plan.blockedReasonCodes || [];
  const commandLabel = argsPreview.length > 0 ? argsPreview.join(" ") : "—";
  const selectedLabel = ruleNameList(selectedRules) || "—";
  const scopeLabel = ruleNameList(rerunRules) || "—";

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span className="font-medium text-slate-900">rule retry execution plan</span>
          <span className="truncate font-mono text-[11px] text-slate-500">{plan.schemaVersion || "rule-retry-execution-plan"}</span>
        </div>
        <span className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
          {plan.commandPreviewAvailable ? "preview only" : "blocked"}
        </span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <ExecutionMetric label="selected" value={String(selectedRules.length)} />
        <ExecutionMetric label="scope" value={String(rerunRules.length)} />
        <ExecutionMetric label="forcerun" value={String(forcerunRules.length)} />
        <ExecutionMetric label="reason" value={plan.reasonCode || "—"} />
      </div>
      <p className="mt-2 text-[11px] leading-5 text-slate-500">
        局部规则重试执行仍关闭；这里仅展示 Snakemake 命令语义和执行前必须解除的阻断项。
      </p>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-slate-500">command preview</span>
        <span className="truncate font-mono text-slate-800">{commandLabel}</span>
        <span className="text-slate-500">selected rules</span>
        <span className="truncate font-mono text-slate-800">{selectedLabel}</span>
        <span className="text-slate-500">rerun scope</span>
        <span className="truncate font-mono text-slate-800">{scopeLabel}</span>
        <span className="text-slate-500">blockers</span>
        <span className="truncate font-mono text-slate-800">{compactList(blockers)}</span>
        <span className="text-slate-500">unsafe flags</span>
        <span className="truncate font-mono text-slate-800">{compactList(unsafeFlags)}</span>
      </div>
    </div>
  );
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
      <RuleRetryPlanSummary context={context} />
      <RuleRetryExecutionPlanPreview plan={context.ruleRetryExecutionPlan} />
    </div>
  );
}
