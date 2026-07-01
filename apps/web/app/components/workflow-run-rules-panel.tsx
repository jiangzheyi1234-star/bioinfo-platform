"use client";

import { useMemo, useState } from "react";
import { Clock, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { RuleAttemptBadge, runAttemptByRule } from "./workflow-run-attempts-panel";
import { WorkflowRuleFailureDiagnostics } from "./workflow-rule-failure-diagnostics";
import { WorkflowRuleLogEvidence } from "./workflow-rule-log-evidence";
import { WorkflowRuleRetryAction } from "./workflow-rule-retry-action";
import type { WorkflowRuleRetryRequest, WorkflowRuleRetryResult } from "./workflow-rule-retry-model";
import { WorkflowRunResumeAction } from "./workflow-run-resume-action";
import type { WorkflowRunResumeRequest, WorkflowRunResumeResult } from "./workflow-run-resume-model";
import type { WorkflowRunRulesSummary } from "./workflow-run-rules-model";
import type { WorkflowRunDetail, WorkflowRunExecutionContext, WorkflowRunRule } from "./workflows-page-model";
import type { WorkflowRunAttemptsReadModel } from "./workflow-run-attempts-model";

type RuleFilterKey = "all" | "failed" | "running" | "completed" | "logs";

const RULE_FILTERS: Array<{ key: RuleFilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "failed", label: "失败" },
  { key: "running", label: "运行中" },
  { key: "completed", label: "完成" },
  { key: "logs", label: "有日志证据" },
];

export function WorkflowRunRulesPanel({
  attempts,
  executionContext,
  onResumeRun,
  onRetryRunRules,
  resumingRun,
  resumeResult,
  retryingRunRules,
  ruleRetryResult,
  rules,
  rulesModel,
}: {
  attempts: WorkflowRunAttemptsReadModel | null;
  executionContext?: WorkflowRunExecutionContext;
  onResumeRun?: (request: WorkflowRunResumeRequest) => void;
  onRetryRunRules?: (request: WorkflowRuleRetryRequest) => void;
  resumingRun?: boolean;
  resumeResult?: WorkflowRunResumeResult | null;
  retryingRunRules?: boolean;
  ruleRetryResult?: WorkflowRuleRetryResult | null;
  rules: WorkflowRunRule[];
  rulesModel?: WorkflowRunDetail["rules"];
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<RuleFilterKey>("all");
  const filteredRules = useMemo(
    () => rules.filter((rule) => ruleMatchesFilter(rule, filter) && ruleMatchesQuery(rule, query)),
    [filter, query, rules]
  );
  if (rules.length === 0) {
    return <div className="py-8 text-center text-sm text-slate-400">暂无 rule 状态</div>;
  }
  const attemptByRule = runAttemptByRule(attempts, rules);
  return (
    <div className="space-y-3">
      <RunRulesRedactionNotice rules={rulesModel} />
      <RunRulesSummary summary={rulesModel?.summary} />
      <RunRulesRecoveryActions
        context={executionContext}
        onResumeRun={onResumeRun}
        onRetryRunRules={onRetryRunRules}
        resumingRun={resumingRun}
        resumeResult={resumeResult}
        retryingRunRules={retryingRunRules}
        ruleRetryResult={ruleRetryResult}
      />
      <RunRulesToolbar
        filter={filter}
        matchCount={filteredRules.length}
        query={query}
        ruleCount={rules.length}
        onFilterChange={setFilter}
        onQueryChange={setQuery}
      />
      {filteredRules.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-400">
          无匹配 rule
        </div>
      ) : null}
      {filteredRules.map((rule) => {
        const events = rule.events || [];
        const wildcards = rule.wildcards && Object.keys(rule.wildcards).length > 0 ? JSON.stringify(rule.wildcards) : "";
        const ruleKey = rule.runRuleId || `${rule.ruleName}-${rule.attemptId || rule.attemptNumber || ""}`;
        const attempt = attemptByRule.get(ruleKey);
        return (
          <div key={ruleKey} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className={cn("rounded border px-2 py-0.5 text-xs font-medium", ruleStatusStyle(rule.status))}>
                    {rule.status || "unknown"}
                  </span>
                  <div className="truncate text-sm font-semibold text-slate-900">{rule.ruleName}</div>
                </div>
                <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-slate-400">
                  {rule.stepId ? <span className="truncate">step {rule.stepId}</span> : null}
                  {rule.runtimeStatusKey ? <span className="truncate">{rule.runtimeStatusKey}</span> : null}
                  {rule.runRuleId ? <span className="truncate">{rule.runRuleId}</span> : null}
                </div>
              </div>
              <RuleAttemptBadge attempt={attempt} rule={rule} />
              <div className="grid shrink-0 grid-cols-2 gap-x-4 gap-y-1 text-right text-[11px] text-slate-500">
                <span>attempt</span>
                <span className="font-mono text-slate-700">{rule.attemptNumber ?? "-"}</span>
                <span>lease</span>
                <span className="font-mono text-slate-700">{rule.leaseGeneration ?? "-"}</span>
                <span>exit</span>
                <span className="font-mono text-slate-700">{rule.exitCode ?? "-"}</span>
                <span>耗时</span>
                <span className="font-mono text-slate-700">{durationText(rule.startedAt, rule.finishedAt)}</span>
              </div>
            </div>

            {rule.message ? <div className="mt-3 text-xs text-slate-600">{rule.message}</div> : null}
            {wildcards ? <div className="mt-2 truncate font-mono text-[11px] text-slate-400">{wildcards}</div> : null}
            <WorkflowRuleFailureDiagnostics rule={rule} ruleLogContext={rule.logContext} />
            <RuleCountList inputCount={rule.inputCount} outputCount={rule.outputCount} logReferenceCount={rule.logReferenceCount} />
            <WorkflowRuleLogEvidence rule={rule} />

            {events.length > 0 ? (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <div className="mb-2 text-[11px] font-medium text-slate-400">events</div>
                <div className="space-y-1.5">
                  {events.slice(-5).map((event) => (
                    <div key={event.ruleEventId || `${event.createdAt}-${event.eventType}`} className="flex min-w-0 items-center gap-2 text-xs text-slate-600">
                      <Clock strokeWidth={1.5} className="h-3 w-3 shrink-0 text-slate-300" />
                      <span className="shrink-0 font-mono text-[11px] text-slate-400">
                        {event.createdAt ? new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--"}
                      </span>
                      <span className={cn("shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium", ruleStatusStyle(event.status))}>
                        {event.eventType || event.status || "event"}
                      </span>
                      <span className="min-w-0 truncate">{event.message || "-"}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function RunRulesRecoveryActions({
  context,
  onResumeRun,
  onRetryRunRules,
  resumingRun,
  resumeResult,
  retryingRunRules,
  ruleRetryResult,
}: {
  context?: WorkflowRunExecutionContext;
  onResumeRun?: (request: WorkflowRunResumeRequest) => void;
  onRetryRunRules?: (request: WorkflowRuleRetryRequest) => void;
  resumingRun?: boolean;
  resumeResult?: WorkflowRunResumeResult | null;
  retryingRunRules?: boolean;
  ruleRetryResult?: WorkflowRuleRetryResult | null;
}) {
  if (!context?.resumePlan && !context?.ruleRetryExecutionPlan) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3" data-rule-recovery-actions="true">
      <div className="text-xs font-semibold text-slate-900">恢复操作</div>
      <WorkflowRunResumeAction
        plan={context.resumePlan}
        resuming={resumingRun}
        result={resumeResult}
        onResume={onResumeRun}
      />
      <WorkflowRuleRetryAction
        plan={context.ruleRetryExecutionPlan}
        retrying={retryingRunRules}
        result={ruleRetryResult}
        onRetry={onRetryRunRules}
      />
    </div>
  );
}

function RunRulesToolbar({
  filter,
  matchCount,
  onFilterChange,
  onQueryChange,
  query,
  ruleCount,
}: {
  filter: RuleFilterKey;
  matchCount: number;
  onFilterChange: (filter: RuleFilterKey) => void;
  onQueryChange: (query: string) => void;
  query: string;
  ruleCount: number;
}) {
  const filtered = filter !== "all" || query.trim();
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search strokeWidth={1.5} className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="搜索 rule / step / message"
            className="h-9 pl-8 text-xs"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {RULE_FILTERS.map((item) => (
            <Button
              key={item.key}
              type="button"
              variant={filter === item.key ? "default" : "outline"}
              className={cn(
                "h-8 px-2.5 text-xs",
                filter === item.key ? "bg-slate-900 text-white" : "bg-white text-slate-600"
              )}
              onClick={() => onFilterChange(item.key)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        {filtered ? (
          <Button
            type="button"
            variant="ghost"
            className="h-8 px-2.5 text-xs text-slate-500"
            onClick={() => {
              onFilterChange("all");
              onQueryChange("");
            }}
          >
            <X strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
            清除
          </Button>
        ) : null}
      </div>
      <div className="mt-2 text-[11px] text-slate-400">
        {matchCount} / {ruleCount} rules
      </div>
    </div>
  );
}

function RunRulesSummary({ summary }: { summary?: WorkflowRunRulesSummary }) {
  if (!summary) return null;
  const ruleCount = numberValue(summary.ruleCount);
  const metrics = [
    ["rules", ruleCount],
    ["failed", summary.failedRuleCount],
    ["running", summary.runningRuleCount],
    ["blocked", summary.blockedRuleCount],
    ["events", summary.ruleEventCount],
    ["attempt meta", `${numberValue(summary.rulesWithAttemptMetadata)} / ${ruleCount}`],
    ["log refs", summary.logReferenceCount],
    ["log preview", `${numberValue(summary.rulesWithAvailableLogEvidence)} / ${numberValue(summary.rulesWithLogReferences)}`],
  ] as const;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="grid gap-3 sm:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <div className="text-[11px] font-medium text-slate-400">{label}</div>
            <div className="mt-1 truncate font-mono text-sm text-slate-800">{value ?? 0}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3 text-[11px]">
        {countPills(summary.statusCounts, "status").map((pill) => pill)}
        {countPills(summary.logEvidenceStatusCounts, "log").map((pill) => pill)}
        {countPills(summary.logEvidenceReasonCodes, "reason").map((pill) => pill)}
      </div>
    </div>
  );
}

function RunRulesRedactionNotice({ rules }: { rules: WorkflowRunDetail["rules"] }) {
  const policy = rules?.redactionPolicy;
  if (!policy) return null;
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        <span>paths {policy.artifactPathsExposed || policy.ruleLogPathsExposed ? "visible" : "redacted"}</span>
        <span>commands {policy.commandSummaryExposed ? "visible" : "redacted"}</span>
        <span>event details {policy.eventDetailsSanitized ? "sanitized" : "raw"}</span>
      </div>
    </div>
  );
}

function RuleCountList({
  inputCount,
  outputCount,
  logReferenceCount,
}: {
  inputCount?: number;
  outputCount?: number;
  logReferenceCount?: number;
}) {
  const rows = [
    ["inputs", inputCount ?? 0],
    ["outputs", outputCount ?? 0],
    ["log refs", logReferenceCount ?? 0],
  ] as const;
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-3">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
          <div className="text-[11px] font-medium text-slate-400">{label}</div>
          <div className="mt-1 font-mono text-sm text-slate-700">{value}</div>
        </div>
      ))}
    </div>
  );
}

function countPills(counts: Record<string, number> | undefined, prefix: string) {
  return Object.entries(counts || {})
    .filter(([, count]) => numberValue(count) > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([label, count]) => (
      <span key={`${prefix}-${label}`} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-slate-600">
        {prefix}:{label}={numberValue(count)}
      </span>
    ));
}

function isFailedStatus(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  return s === "failed" || s === "error";
}

function isRunningStatus(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  return s === "running" || s === "started";
}

function isCompletedStatus(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  return s === "completed" || s === "success" || s === "succeeded";
}

function ruleHasLogEvidence(rule: WorkflowRunRule) {
  const context = rule.logContext;
  return Boolean(
    (rule.logReferenceCount || 0) > 0 ||
      context?.status ||
      context?.reasonCode ||
      context?.selectedArtifact?.artifactId ||
      context?.tail?.length
  );
}

function ruleMatchesFilter(rule: WorkflowRunRule, filter: RuleFilterKey) {
  if (filter === "all") return true;
  if (filter === "failed") return isFailedStatus(rule.status);
  if (filter === "running") return isRunningStatus(rule.status);
  if (filter === "completed") return isCompletedStatus(rule.status);
  if (filter === "logs") return ruleHasLogEvidence(rule);
  return true;
}

function ruleMatchesQuery(rule: WorkflowRunRule, query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  return ruleSearchText(rule).includes(normalized);
}

function ruleSearchText(rule: WorkflowRunRule) {
  const context = rule.logContext;
  return [
    rule.ruleName,
    rule.stepId,
    rule.runtimeStatusKey,
    rule.runRuleId,
    rule.status,
    rule.message,
    rule.sourceLocation?.fileBasename,
    context?.reasonCode,
    context?.status,
    context?.message,
    context?.selectedArtifact?.artifactId,
    ...(rule.events || []).flatMap((event) => [
      event.eventType,
      event.status,
      event.message,
      event.sourceLocation?.fileBasename,
    ]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function ruleStatusStyle(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  if (s === "completed" || s === "success" || s === "succeeded") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (isFailedStatus(s)) return "border-red-200 bg-red-50 text-red-700";
  if (s === "running" || s === "started") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function durationText(startedAt?: string, finishedAt?: string) {
  if (!startedAt || !finishedAt) return "-";
  const seconds = Math.max(0, Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
