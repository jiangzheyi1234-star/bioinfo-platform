"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertCircle, Loader2, RefreshCw, ShieldCheck } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { fetchWorkflowRunAttempts } from "./workflow-run-attempts-api";
import type { WorkflowRunAttemptsReadModel } from "./workflow-run-attempts-model";
import type { WorkflowRunExecutionAttempt, WorkflowRunRule } from "./workflows-page-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowRunAttemptsPanel({
  runId,
  rules,
  onAttemptsLoaded,
}: {
  runId: string;
  rules: WorkflowRunRule[];
  onAttemptsLoaded?: (attempts: WorkflowRunAttemptsReadModel | null) => void;
}) {
  const [attempts, setAttempts] = useState<WorkflowRunAttemptsReadModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (forceRefresh = false) => {
    if (!forceRefresh) {
      setAttempts(null);
      onAttemptsLoaded?.(null);
    }
    setLoading(true);
    setError("");
    try {
      const data = await fetchWorkflowRunAttempts(runId, { forceRefresh });
      setAttempts(data);
      onAttemptsLoaded?.(data);
    } catch (err) {
      const message = runAttemptsErrorMessage(err, "读取 run attempts 失败");
      setError(message);
      setAttempts(null);
      onAttemptsLoaded?.(null);
    } finally {
      setLoading(false);
    }
  }, [onAttemptsLoaded, runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const ruleAttemptCount = useMemo(
    () => rules.filter((rule) => rule.attemptId || rule.attemptNumber).length,
    [rules]
  );

  if (loading && !attempts) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-slate-200 bg-white py-8 text-sm text-slate-400">
        <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
        正在读取 attempts
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Activity strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <div>
            <div className="text-sm font-semibold text-slate-900">Run attempts</div>
            <div className="text-xs text-slate-500">{ruleAttemptCount} 个 rule 带 attempt 引用</div>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={loading}
          onClick={() => void load(true)}
        >
          <RefreshCw strokeWidth={1.5} className={loading ? "mr-1.5 h-3.5 w-3.5 animate-spin" : "mr-1.5 h-3.5 w-3.5"} />
          刷新
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive" className="py-2 text-xs">
          <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {attempts ? <AttemptReadModelSummary attempts={attempts} /> : null}
    </div>
  );
}

export function RuleAttemptBadge({
  attempt,
  rule,
}: {
  attempt?: WorkflowRunExecutionAttempt;
  rule: WorkflowRunRule;
}) {
  const state = attempt?.state || rule.status;
  const attemptNumber = attempt?.attemptNumber ?? rule.attemptNumber;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className={cn("rounded border px-1.5 py-0.5 font-medium", attemptStateClass(state))}>
        attempt {attemptNumber ?? "—"} · {state || "unknown"}
      </span>
      {attempt?.leaseGeneration ?? rule.leaseGeneration ? (
        <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-slate-500">
          lease {attempt?.leaseGeneration ?? rule.leaseGeneration}
        </span>
      ) : null}
      {attempt?.exitCode !== undefined && attempt.exitCode !== null ? (
        <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-slate-500">
          exit {attempt.exitCode}
        </span>
      ) : null}
      {attempt?.workerId ? (
        <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-slate-500">
          {attempt.workerId}
        </span>
      ) : null}
    </div>
  );
}

export function runAttemptByRule(attempts: WorkflowRunAttemptsReadModel | null, rules: WorkflowRunRule[]) {
  const byAttemptId = new Map(
    (attempts?.attempts || [])
      .filter((attempt) => attempt.attemptId)
      .map((attempt) => [attempt.attemptId, attempt])
  );
  const byAttemptNumber = new Map(
    (attempts?.attempts || [])
      .filter((attempt) => typeof attempt.attemptNumber === "number")
      .map((attempt) => [attempt.attemptNumber, attempt])
  );
  return new Map(
    rules.map((rule) => [
      rule.runRuleId || `${rule.ruleName}-${rule.attemptId || rule.attemptNumber || ""}`,
      (rule.attemptId ? byAttemptId.get(rule.attemptId) : undefined)
        || (typeof rule.attemptNumber === "number" ? byAttemptNumber.get(rule.attemptNumber) : undefined),
    ])
  );
}

function AttemptReadModelSummary({ attempts }: { attempts: WorkflowRunAttemptsReadModel }) {
  const summary = attempts.summary || {};
  const latest = summary.latestAttempt;
  const job = attempts.job;
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <AttemptMetric label="attempts" value={String(summary.attemptCount ?? attempts.attempts?.length ?? 0)} />
        <AttemptMetric label="slots" value={String(summary.slotCount ?? attempts.slots?.length ?? 0)} />
        <AttemptMetric label="active lease" value={summary.activeLeasePresent ? "yes" : "no"} />
        <AttemptMetric label="job attempts" value={job?.maxAttempts ? `${job.attemptCount ?? 0}/${job.maxAttempts}` : String(job?.attemptCount ?? "—")} />
        <AttemptMetric label="latest" value={latest?.state || "—"} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <StateBreakdown title="attempt states" values={summary.attemptsByState} />
        <StateBreakdown title="slot states" values={summary.slotsByState} />
      </div>
      <AttemptTimeline attempts={attempts.attempts || []} />
      <AttemptRedactionNotice attempts={attempts} />
    </div>
  );
}

function AttemptTimeline({ attempts }: { attempts: WorkflowRunExecutionAttempt[] }) {
  if (attempts.length === 0) {
    return <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-400">暂无 attempt 记录</div>;
  }
  return (
    <div className="space-y-1.5">
      {attempts.slice(-5).map((attempt) => (
        <div key={attempt.attemptId || attempt.attemptNumber} className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 text-xs md:grid-cols-[150px_minmax(0,1fr)_120px]">
          <div className="font-mono text-slate-700">#{attempt.attemptNumber ?? "—"} {attempt.state || "unknown"}</div>
          <div className="min-w-0 truncate text-slate-500">
            {formatDateTime(attempt.startedAt)} {"->"} {formatDateTime(attempt.finishedAt)}
          </div>
          <div className="text-right font-mono text-slate-500">exit {attempt.exitCode ?? "—"}</div>
        </div>
      ))}
    </div>
  );
}

function AttemptRedactionNotice({ attempts }: { attempts: WorkflowRunAttemptsReadModel }) {
  const redaction = attempts.redactionPolicy;
  if (!redaction) return null;
  const hidden = Object.entries(redaction).filter(([, exposed]) => exposed === false).map(([key]) => key);
  if (hidden.length === 0) return null;
  return (
    <div className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
      <ShieldCheck strokeWidth={1.5} className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
      <span className="min-w-0">已隐藏敏感执行字段：{hidden.join(", ")}</span>
    </div>
  );
}

function AttemptMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-medium text-slate-400">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function StateBreakdown({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values || {});
  if (entries.length === 0) return <div className="text-xs text-slate-400">{title}: —</div>;
  return (
    <div className="flex flex-wrap gap-1.5 text-[11px]">
      <span className="text-slate-400">{title}</span>
      {entries.map(([state, count]) => (
        <span key={state} className={cn("rounded border px-1.5 py-0.5", attemptStateClass(state))}>
          {state} {count}
        </span>
      ))}
    </div>
  );
}

function attemptStateClass(state?: string) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "succeeded" || normalized === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "failed" || normalized === "fenced" || normalized === "error") return "border-red-200 bg-red-50 text-red-700";
  if (normalized === "running" || normalized === "active") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function formatDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function runAttemptsErrorMessage(err: unknown, fallback: string) {
  const message = workflowErrorMessage(err, fallback);
  const status = typeof err === "object" && err && "status" in err ? Number((err as { status?: unknown }).status) : 0;
  if (status === 404 || /^not found$/i.test(message)) {
    return "当前远程 runner 未暴露 run attempts API，请部署包含 run-attempts.v1 的 runner 后重试。";
  }
  return message;
}
