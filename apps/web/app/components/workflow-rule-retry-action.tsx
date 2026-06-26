"use client";

import { Loader2, RotateCcw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WorkflowRunRuleRetryExecutionPlan } from "./workflows-page-model";
import type { WorkflowRuleRetryRequest, WorkflowRuleRetryResult } from "./workflow-rule-retry-model";
import { workflowRuleRetryCanSubmit } from "./workflow-rule-retry-model";

type Props = {
  plan?: WorkflowRunRuleRetryExecutionPlan;
  retrying?: boolean;
  result?: WorkflowRuleRetryResult | null;
  onRetry?: (request: WorkflowRuleRetryRequest) => void;
};

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "—";
}

function reasonForDisabled(plan?: WorkflowRunRuleRetryExecutionPlan) {
  if (!plan) return "rule retry plan missing";
  if (!plan.planHash) return "plan hash missing";
  if (plan.planHash.length !== 64) return "plan hash invalid";
  if (plan.eligibleNow !== true) return plan.reasonCode || "rule retry not eligible";
  if (!plan.selectedRules?.length) return "selected rule missing";
  if (plan.executionEnabled !== true) {
    return plan.executionReasonCode || plan.activationReadiness?.reasonCode || plan.reasonCode || "rule retry disabled";
  }
  if (plan.activationReadiness?.executionReady !== true || plan.activationReadiness.executionEnabled !== true) {
    return plan.activationReadiness?.reasonCode || "activation not ready";
  }
  if ((plan.activationReadiness?.blockedCheckCount || 0) > 0) return "activation checks blocked";
  if (
    plan.activationReadiness?.redactionPolicy?.pathsExposed === true ||
    plan.activationReadiness?.redactionPolicy?.storageUrisExposed === true
  ) {
    return "activation projection unsafe";
  }
  const orchestration = plan.executorOrchestration;
  if (!orchestration?.contractReady || !orchestration.executorReady) return orchestration?.reasonCode || "executor not ready";
  if (!orchestration.queueMutationAllowed || !orchestration.runStateMutationAllowed) return "executor mutation blocked";
  if (!orchestration.launchReady || !orchestration.executionBoundaryReady) return "executor launch boundary blocked";
  if (orchestration.pathExposed || orchestration.storageUriExposed) return "executor projection unsafe";
  const launch = orchestration.launchPreflight;
  if (!launch?.preflightReady || !launch.launchReady) return launch?.reasonCode || "launch preflight blocked";
  if (!launch.executorStartAllowed || !launch.queueMutationAllowed || !launch.runStateMutationAllowed) {
    return "launch mutation blocked";
  }
  if (launch.pathExposed || launch.storageUriExposed) return "launch projection unsafe";
  const boundary = orchestration.executionBoundary;
  if (!boundary?.boundaryReady) return boundary?.reasonCode || "execution boundary blocked";
  if (!boundary.executorStartAllowed || !boundary.queueMutationAllowed || !boundary.runStateMutationAllowed) {
    return "execution boundary mutation blocked";
  }
  if (boundary.pathExposed || boundary.storageUriExposed) return "execution boundary projection unsafe";
  return "";
}

export function WorkflowRuleRetryAction({ plan, retrying = false, result, onRetry }: Props) {
  if (!plan) return null;
  const enabled = Boolean(onRetry && workflowRuleRetryCanSubmit(plan) && !retrying);
  const disabledReason = reasonForDisabled(plan);
  const selectedCount = plan.selectedRules?.length || 0;
  const rerunCount = plan.rerunScope?.ruleCount || plan.rerunScope?.rules?.length || 0;
  const readiness = plan.activationReadiness;
  const planHash = plan.planHash || "";
  function handleClick() {
    if (!enabled || !planHash) return;
    if (!window.confirm("确认提交 rule-level retry？系统会重算当前计划并校验 plan hash 后才会入队。")) return;
    onRetry?.({ planHash });
  }

  return (
    <div className="mt-3 rounded-md border border-violet-200 bg-violet-50/70 px-3 py-2 text-xs text-violet-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <RotateCcw strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">rule-level retry</span>
          <span className="truncate font-mono text-[11px] text-violet-700">{plan.schemaVersion || "rule-retry-execution-plan"}</span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 border-violet-300 bg-white/90 px-2 text-[11px] text-violet-900 hover:bg-violet-100"
          disabled={!enabled}
          title={enabled ? "提交 rule-level retry" : disabledReason}
          onClick={handleClick}
        >
          {retrying ? (
            <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <ShieldCheck strokeWidth={1.5} className="mr-1 h-3 w-3" />
          )}
          提交规则重试
        </Button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded border border-violet-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-violet-600">selected</div>
          <div className="font-mono text-violet-950">{selectedCount}</div>
        </div>
        <div className="rounded border border-violet-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-violet-600">rerun scope</div>
          <div className="font-mono text-violet-950">{rerunCount}</div>
        </div>
        <div className="rounded border border-violet-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-violet-600">plan</div>
          <div className="font-mono text-violet-950">{shortHash(plan.planHash)}</div>
        </div>
        <div className="rounded border border-violet-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-violet-600">readiness</div>
          <div className="font-mono text-violet-950">
            {readiness?.readyCheckCount ?? 0}/{readiness?.blockedCheckCount ?? 0}
          </div>
        </div>
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-violet-700">state</span>
        <span className="truncate font-mono">
          {plan.executionEnabled ? "enabled" : "blocked"} · {disabledReason || plan.executionReasonCode || "RULE_RETRY_EXECUTION_ENABLED"}
        </span>
        <span className="text-violet-700">last result</span>
        <span className="truncate font-mono">
          {result?.status || "—"} · {result?.scope || "—"} · rules {result?.rerunRuleCount ?? "—"}
        </span>
        <span className="text-violet-700">command</span>
        <span className="truncate font-mono">{result?.commandId || "—"}</span>
      </div>
    </div>
  );
}
