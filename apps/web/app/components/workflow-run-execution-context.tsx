"use client";

import type { ReactNode } from "react";
import { Activity, Clock, Loader2, RotateCcw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import { WorkflowRuleCacheRestoreActions } from "./workflow-rule-cache-restore-actions";
import type {
  WorkflowRuleCacheRestoreRequest,
  WorkflowRuleCacheRestoreResult,
} from "./workflow-rule-cache-restore-model";
import { WorkflowRuleRetryAction } from "./workflow-rule-retry-action";
import type { WorkflowRuleRetryRequest, WorkflowRuleRetryResult } from "./workflow-rule-retry-model";
import { WorkflowRunResumeAction } from "./workflow-run-resume-action";
import type { WorkflowRunResumeRequest, WorkflowRunResumeResult } from "./workflow-run-resume-model";
import type {
  WorkflowRunActivationReadiness,
  WorkflowRunExecutionAttempt,
  WorkflowRunExecutionContext,
  WorkflowRunResumePlan,
  WorkflowRunRuleOutputInvalidationPlan,
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

function runRetryLabel(context: WorkflowRunExecutionContext) {
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

function readinessLabel(readiness?: WorkflowRunActivationReadiness) {
  if (!readiness) return "—";
  return `${readiness.readyCheckCount ?? 0} ready / ${readiness.blockedCheckCount ?? 0} blocked · ${
    readiness.reasonCode || "—"
  }`;
}

function readinessCheckLabel(readiness?: WorkflowRunActivationReadiness) {
  const blocked = (readiness?.checks || [])
    .filter((check) => !check.ready)
    .map((check) => check.name || check.reasonCode || "")
    .filter(Boolean);
  return compactList(blocked);
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
        规则级重试计划仅供诊断摘要；整跑重试和 rule-level retry 使用各自独立按钮，并在提交时重新校验当前计划。
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

function RuleOutputInvalidationPlanPreview({
  plan,
  onApply,
  applying = false,
}: {
  plan?: WorkflowRunRuleOutputInvalidationPlan;
  onApply?: (planHash: string) => void;
  applying?: boolean;
}) {
  if (!plan?.previewAvailable) return null;
  const summary = plan.outputEdgeSummary || {};
  const invalidationState = plan.outputInvalidationState;
  const invalidatedOutputCount = summary.invalidatedOutputEdgeCount || 0;
  const appliedOutputCount =
    invalidationState?.state === "applied"
      ? invalidationState.appliedOutputEdgeCount || summary.alreadyInvalidatedOutputEdgeCount || 0
      : summary.alreadyInvalidatedOutputEdgeCount || 0;
  const planHash = plan.planHash;
  const applyEnabled = Boolean(
    onApply && planHash && plan.invalidationEnabled && plan.eligibleNow && invalidatedOutputCount > 0
  );
  const disabledReason = !plan.invalidationEnabled
    ? plan.reasonCode || "invalidation disabled"
    : !planHash
      ? "plan hash missing"
      : invalidatedOutputCount <= 0
        ? "empty invalidation scope"
        : "not eligible now";
  const applyTitle = applyEnabled ? "应用 output invalidation tombstone" : `无法应用：${disabledReason}`;
  const impactedOutputs = (plan.rules || [])
    .flatMap((rule) => rule.outputs || [])
    .map((output) => output.portName || output.stepId || "")
    .filter(Boolean);
  const selectedRules = (plan.rules || []).filter((rule) => rule.invalidationRole === "selected_failed_rule");
  const downstreamRules = (plan.rules || []).filter((rule) => rule.invalidationRole === "downstream_rule");
  function handleApply() {
    if (!applyEnabled || !planHash) return;
    if (window.confirm("确认应用 output invalidation tombstone？这会标记当前计划中的输出和 lineage 边为失效。")) {
      onApply?.(planHash);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-sky-200 bg-sky-50/70 px-3 py-2 text-xs text-sky-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">output invalidation plan</span>
          <span className="truncate font-mono text-[11px] text-sky-700">{plan.schemaVersion || "rule-output-invalidation-plan"}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded border border-sky-300 bg-white/60 px-1.5 py-0.5 font-mono text-[11px] text-sky-800">
            preview only
          </span>
          {onApply ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 border-sky-300 bg-white/80 px-2 text-[11px] text-sky-900 hover:bg-sky-100"
              disabled={!applyEnabled || applying}
              title={applyTitle}
              onClick={handleApply}
            >
              {applying ? (
                <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <ShieldCheck strokeWidth={1.5} className="mr-1 h-3 w-3" />
              )}
              应用失效
            </Button>
          ) : null}
        </div>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <ExecutionMetric label="invalidated" value={String(invalidatedOutputCount)} />
        <ExecutionMetric label="selected" value={String(summary.selectedOutputEdgeCount || selectedRules.length)} />
        <ExecutionMetric label="downstream" value={String(summary.downstreamOutputEdgeCount || downstreamRules.length)} />
        <ExecutionMetric label="lineage" value={String(summary.invalidatedLineageEdgeCount || 0)} />
        <ExecutionMetric label="applied" value={String(appliedOutputCount)} />
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-sky-700">outputs</span>
        <span className="truncate font-mono">{compactList(impactedOutputs)}</span>
        <span className="text-sky-700">state</span>
        <span className="truncate font-mono">
          {invalidationState?.state || "pending"} · {plan.reasonCode || "—"}
        </span>
        <span className="text-sky-700">preserved</span>
        <span className="truncate font-mono">{String(summary.preservedOutputEdgeCount || 0)}</span>
        <span className="text-sky-700">unmatched</span>
        <span className="truncate font-mono">{String(summary.unmatchedOutputEdgeCount || 0)}</span>
        <span className="text-sky-700">payload delete</span>
        <span className="truncate font-mono">{summary.payloadDeletionAllowed ? "enabled" : "disabled"}</span>
        <span className="text-sky-700">blockers</span>
        <span className="truncate font-mono">{compactList(plan.blockedReasonCodes)}</span>
      </div>
    </div>
  );
}

function RuleRetryExecutionPlanPreview({ plan }: { plan?: WorkflowRunRuleRetryExecutionPlan }) {
  if (!plan) return null;
  const cacheRestore = plan.cacheRestorePlan;
  const outputAudit = plan.incompleteOutputAudit;
  const lifecycle = plan.partialRerunLifecycle;
  const partialOutputClosure = plan.partialRerunOutputClosure;
  const stagedFilePolicy = cacheRestore?.stagedFilePolicy;
  const restorePinPolicy = cacheRestore?.restorePinPolicy;
  const options = plan.snakemakeOptions;
  const argsPreview = options?.argsPreview || [];
  const forcerunRules = options?.forcerunRules || [];
  const targetOutputKeys = options?.targetOutputKeys || [];
  const unsafeFlags = options?.unsafeFlagsProhibited || [];
  const selectedRules = plan.selectedRules || [];
  const rerunRules = uniqueRuleRefs(plan.rerunScope?.rules || []);
  const blockers = plan.blockedReasonCodes || [];
  const commandLabel = argsPreview.length > 0 ? argsPreview.join(" ") : "—";
  const selectedLabel = ruleNameList(selectedRules) || "—";
  const scopeLabel = ruleNameList(rerunRules) || "—";
  const cacheLabel = cacheRestore
    ? `${cacheRestore.cacheHitCount || 0} / ${cacheRestore.outputCount || 0}`
    : "—";
  const stagedFileLabel = stagedFilePolicy
    ? `${stagedFilePolicy.reasonCode || "—"} · targets ${stagedFilePolicy.targetCount || 0} · hit ${
        stagedFilePolicy.cacheHitTargetCount || 0
      } · miss ${stagedFilePolicy.cacheMissTargetCount || 0} · unmapped ${stagedFilePolicy.unmappedTargetCount || 0}`
    : "—";
  const restorePinLabel = restorePinPolicy
    ? `${restorePinPolicy.reasonCode || "—"} · candidate ${restorePinPolicy.candidatePinCount || 0} · required ${
        restorePinPolicy.requiredPinCount || 0
      } · created ${restorePinPolicy.createdPinCount || 0}`
    : "—";
  const cacheFingerprints = (cacheRestore?.rules || [])
    .flatMap((rule) => rule.outputs || [])
    .map((output) => output.cacheKeyFingerprint || "")
    .filter(Boolean);
  const cacheFingerprintLabel = compactList(cacheFingerprints);
  const cachePolicyLabel = cacheRestore?.redactionPolicy?.cacheKeysExposed
    ? "raw keys exposed"
    : cacheRestore?.redactionPolicy?.cacheKeyFingerprintsExposed
      ? "digest-only"
      : "redacted";
  const activationReadiness = plan.activationReadiness;
  const orchestration = plan.executorOrchestration;
  const launchPreflight = orchestration?.launchPreflight;
  const executionBoundary = orchestration?.executionBoundary;
  const orchestrationLabel = orchestration
    ? `${orchestration.reasonCode || "—"} · contract ${orchestration.contractReady ? "ready" : "blocked"} · executor ${
        orchestration.executorReady ? "ready" : "off"
      }`
    : "—";
  const launchPreflightLabel = launchPreflight
    ? `${launchPreflight.reasonCode || "—"} · preflight ${launchPreflight.preflightReady ? "ready" : "blocked"} · scope ${
        launchPreflight.outputAdoptionScopeOutputCount ?? launchPreflight.outputAdoptionScope?.outputCount ?? 0
      } · recheck ${launchPreflight.executionPlanHashRevalidationRequired ? "yes" : "no"}`
    : "—";
  const executionBoundaryLabel = executionBoundary
    ? `${executionBoundary.reasonCode || "—"} · targets ${executionBoundary.explicitTargetCount ?? 0} · scoped ${
        executionBoundary.scopedOutputCount ?? 0
      } · finalize ${executionBoundary.finalizeRunAllowed ? "allowed" : "blocked"}`
    : "—";
  const outputAuditLabel = outputAudit
    ? `${outputAudit.reasonCode || "—"} · verified ${outputAudit.verifiedOutputCount ?? 0} · rerun ${
        outputAudit.rerunRequiredOutputCount ?? 0
      } · adopted ${outputAudit.adoptedOutputCount ?? 0} · unverified ${outputAudit.unverifiedOutputCount ?? 0}`
    : "—";
  const lifecycleLabel = lifecycle
    ? `${lifecycle.mode || "—"} · ${lifecycle.reasonCode || "—"} · source ${
        lifecycle.sourceAttempt?.leaseReleased ? "released" : "blocked"
      } · target ${lifecycle.targetAttempt?.creationMode || "—"}`
    : "—";
  const outputClosureLabel = partialOutputClosure
    ? `${partialOutputClosure.reasonCode || "—"} · scoped ${partialOutputClosure.adoptedScopedOutputCount ?? 0}/${
        partialOutputClosure.scopedOutputCount ?? 0
      } · declared ${partialOutputClosure.adoptedDeclaredOutputCount ?? 0}/${
        partialOutputClosure.declaredOutputCount ?? 0
      } · preserved ${partialOutputClosure.preservedOutputEdgeCount ?? 0} · unknown ${
        partialOutputClosure.unknownActiveOutputEdgeCount ?? 0
      }`
    : "—";

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
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        <ExecutionMetric label="selected" value={String(selectedRules.length)} />
        <ExecutionMetric label="scope" value={String(rerunRules.length)} />
        <ExecutionMetric label="forcerun" value={String(forcerunRules.length)} />
        <ExecutionMetric label="targets" value={String(targetOutputKeys.length)} />
        <ExecutionMetric label="cache" value={cacheLabel} />
        <ExecutionMetric label="reason" value={plan.reasonCode || "—"} />
      </div>
      <p className="mt-2 text-[11px] leading-5 text-slate-500">
        rule-level retry 执行预览展示 Snakemake 命令语义、输出边界和启动前检查；提交由独立确认按钮按当前 plan hash 入队。
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
        <span className="text-slate-500">activation</span>
        <span className="truncate font-mono text-slate-800">{readinessLabel(activationReadiness)}</span>
        <span className="text-slate-500">readiness checks</span>
        <span className="truncate font-mono text-slate-800">{readinessCheckLabel(activationReadiness)}</span>
        <span className="text-slate-500">executor contract</span>
        <span className="truncate font-mono text-slate-800">{orchestrationLabel}</span>
        <span className="text-slate-500">launch preflight</span>
        <span className="truncate font-mono text-slate-800">{launchPreflightLabel}</span>
        <span className="text-slate-500">execution boundary</span>
        <span className="truncate font-mono text-slate-800">{executionBoundaryLabel}</span>
        <span className="text-slate-500">output audit</span>
        <span className="truncate font-mono text-slate-800">{outputAuditLabel}</span>
        <span className="text-slate-500">rerun lifecycle</span>
        <span className="truncate font-mono text-slate-800">{lifecycleLabel}</span>
        <span className="text-slate-500">output closure</span>
        <span className="truncate font-mono text-slate-800">{outputClosureLabel}</span>
        {cacheRestore ? (
          <>
            <span className="text-slate-500">cache restore</span>
            <span className="truncate font-mono text-slate-800">
              {cacheRestore.reasonCode || "—"} · miss {cacheRestore.cacheMissCount || 0}
            </span>
            <span className="text-slate-500">cache policy</span>
            <span className="truncate font-mono text-slate-800">
              {cachePolicyLabel} · plan {cacheRestore.planHash ? cacheRestore.planHash.slice(0, 12) : "—"}
            </span>
            <span className="text-slate-500">cache fingerprints</span>
            <span className="truncate font-mono text-slate-800">{cacheFingerprintLabel}</span>
            <span className="text-slate-500">staged files</span>
            <span className="truncate font-mono text-slate-800">{stagedFileLabel}</span>
            <span className="text-slate-500">staged policy</span>
            <span className="truncate font-mono text-slate-800">
              preview {stagedFilePolicy?.previewAvailable ? "yes" : "no"} · overwrite{" "}
              {stagedFilePolicy?.overwriteAllowed ? "yes" : "no"} · paths{" "}
              {stagedFilePolicy?.pathExposed ? "exposed" : "redacted"}
            </span>
            <span className="text-slate-500">restore pins</span>
            <span className="truncate font-mono text-slate-800">{restorePinLabel}</span>
            <span className="text-slate-500">pin policy</span>
            <span className="truncate font-mono text-slate-800">
              create {restorePinPolicy?.pinCreationAllowed ? "yes" : "no"} · owner{" "}
              {restorePinPolicy?.ownerIdExposed ? "exposed" : "redacted"} · storage{" "}
              {restorePinPolicy?.storageUriExposed ? "exposed" : "redacted"}
            </span>
          </>
        ) : null}
        <span className="text-slate-500">unsafe flags</span>
        <span className="truncate font-mono text-slate-800">{compactList(unsafeFlags)}</span>
      </div>
    </div>
  );
}

function RunResumePlanPreview({ plan }: { plan?: WorkflowRunResumePlan }) {
  if (!plan) return null;
  const argsPreview = plan.snakemakeOptions?.argsPreview || [];
  const unsafeFlags = plan.snakemakeOptions?.unsafeFlagsProhibited || [];
  const blockers = plan.blockedReasonCodes || [];
  const commandLabel = argsPreview.length > 0 ? argsPreview.join(" ") : "—";
  const latest = plan.latestAttempt;
  const workdir = plan.workdirEvidence;
  const outputAudit = plan.incompleteOutputAudit;
  const adoption = plan.artifactAdoptionBoundary;
  const orchestration = plan.executorOrchestration;
  const latestLabel = latest?.attemptId
    ? `#${latest.attemptNumber ?? "—"} gen ${latest.leaseGeneration ?? "—"} · ${latest.state || latest.status || "unknown"}`
    : "—";
  const outputAuditLabel = outputAudit
    ? `${outputAudit.reasonCode || "—"} · expected ${outputAudit.expectedOutputCount ?? 0} · verified ${
        outputAudit.verifiedOutputCount ?? 0
      } · rerun ${outputAudit.rerunRequiredOutputCount ?? 0} · unsafe ${outputAudit.unsafeOutputCount ?? 0}`
    : "—";
  const orchestrationLabel = orchestration
    ? `${orchestration.reasonCode || "—"} · contract ${orchestration.contractReady ? "ready" : "blocked"} · executor ${
        orchestration.executorReady ? "ready" : "off"
      }`
    : "—";
  const activationReadiness = plan.activationReadiness;

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <RotateCcw strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span className="font-medium text-slate-900">run resume plan</span>
          <span className="truncate font-mono text-[11px] text-slate-500">{plan.schemaVersion || "run-resume-plan"}</span>
        </div>
        <span className="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
          {plan.commandPreviewAvailable ? "preview only" : "blocked"}
        </span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <ExecutionMetric label="strategy" value={plan.strategy || "—"} />
        <ExecutionMetric label="attempts" value={String(plan.attemptCount ?? 0)} />
        <ExecutionMetric label="rerun incomplete" value={plan.snakemakeOptions?.rerunIncomplete ? "yes" : "no"} />
        <ExecutionMetric label="workdir" value={workdir?.available ? "present" : "missing"} />
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-slate-500">command preview</span>
        <span className="truncate font-mono text-slate-800">{commandLabel}</span>
        <span className="text-slate-500">latest attempt</span>
        <span className="truncate font-mono text-slate-800">{latestLabel}</span>
        <span className="text-slate-500">workdir evidence</span>
        <span className="truncate font-mono text-slate-800">{workdir?.reasonCode || "—"}</span>
        <span className="text-slate-500">output audit</span>
        <span className="truncate font-mono text-slate-800">{outputAuditLabel}</span>
        <span className="text-slate-500">artifact adoption</span>
        <span className="truncate font-mono text-slate-800">{adoption?.reasonCode || "—"}</span>
        <span className="text-slate-500">executor contract</span>
        <span className="truncate font-mono text-slate-800">{orchestrationLabel}</span>
        <span className="text-slate-500">blockers</span>
        <span className="truncate font-mono text-slate-800">{compactList(blockers)}</span>
        <span className="text-slate-500">activation</span>
        <span className="truncate font-mono text-slate-800">{readinessLabel(activationReadiness)}</span>
        <span className="text-slate-500">readiness checks</span>
        <span className="truncate font-mono text-slate-800">{readinessCheckLabel(activationReadiness)}</span>
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
  onResumeRun,
  resumingRun = false,
  resumeResult,
  onApplyRuleOutputInvalidation,
  applyingOutputInvalidation = false,
  onRetryRunRules,
  retryingRunRules = false,
  ruleRetryResult,
  onRunRuleCacheRestoreAction,
  runningRuleCacheRestoreKey = "",
  ruleCacheRestoreResult,
}: {
  context?: WorkflowRunExecutionContext;
  onRetryRun?: () => void;
  retrying?: boolean;
  onResumeRun?: (request: WorkflowRunResumeRequest) => void;
  resumingRun?: boolean;
  resumeResult?: WorkflowRunResumeResult | null;
  onApplyRuleOutputInvalidation?: (planHash: string) => void;
  applyingOutputInvalidation?: boolean;
  onRetryRunRules?: (request: WorkflowRuleRetryRequest) => void;
  retryingRunRules?: boolean;
  ruleRetryResult?: WorkflowRuleRetryResult | null;
  onRunRuleCacheRestoreAction?: (request: WorkflowRuleCacheRestoreRequest) => void;
  runningRuleCacheRestoreKey?: string;
  ruleCacheRestoreResult?: WorkflowRuleCacheRestoreResult | null;
}) {
  if (!context) return null;
  const attempts = context.attempts || [];
  const retryBackoff = policyNumber(context.retryPolicy, "backoffSeconds");
  const lease = context.activeLease || context.currentLease;
  const retryReason = context.retryEligibility?.reasonCode || "RUN_RETRY_UNAVAILABLE";
  const retryEnabled = Boolean(context.retryEligibility?.eligibleNow && onRetryRun);
  const outputInvalidationPlan = context.ruleOutputInvalidationPlan;

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
              title={retryEnabled ? "提交整跑重试" : `整跑重试不可用：${retryReason}`}
              onClick={onRetryRun}
            >
              {retrying ? (
                <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw strokeWidth={1.5} className="mr-1 h-3 w-3" />
              )}
              整跑重试
            </Button>
          ) : null}
          <div className="font-mono text-[11px] text-slate-400">{context.schemaVersion || "run-execution-context"}</div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <ExecutionMetric label="attempt" value={attemptLabel(context)} icon={<Activity strokeWidth={1.5} className="h-3 w-3" />} />
        <ExecutionMetric label="run retry" value={runRetryLabel(context)} icon={<RotateCcw strokeWidth={1.5} className="h-3 w-3" />} />
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
      <RunResumePlanPreview plan={context.resumePlan} />
      <WorkflowRunResumeAction
        plan={context.resumePlan}
        resuming={resumingRun}
        result={resumeResult}
        onResume={onResumeRun}
      />
      <RuleRetryPlanSummary context={context} />
      <RuleOutputInvalidationPlanPreview
        plan={outputInvalidationPlan}
        onApply={onApplyRuleOutputInvalidation}
        applying={applyingOutputInvalidation}
      />
      <RuleRetryExecutionPlanPreview plan={context.ruleRetryExecutionPlan} />
      <WorkflowRuleRetryAction
        plan={context.ruleRetryExecutionPlan}
        retrying={retryingRunRules}
        result={ruleRetryResult}
        onRetry={onRetryRunRules}
      />
      <WorkflowRuleCacheRestoreActions
        plan={context.ruleCacheRestorePlan || context.ruleRetryExecutionPlan?.cacheRestorePlan}
        attemptId={lease?.attemptId}
        leaseGeneration={lease?.leaseGeneration}
        busyKey={runningRuleCacheRestoreKey}
        lastResult={ruleCacheRestoreResult}
        onAction={onRunRuleCacheRestoreAction}
      />
    </div>
  );
}
