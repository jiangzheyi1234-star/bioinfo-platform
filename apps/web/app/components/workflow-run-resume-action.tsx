"use client";

import { Loader2, Play, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WorkflowRunResumePlan } from "./workflows-page-model";
import type { WorkflowRunResumeRequest, WorkflowRunResumeResult } from "./workflow-run-resume-model";
import { workflowRunResumeCanSubmit } from "./workflow-run-resume-model";

type Props = {
  plan?: WorkflowRunResumePlan;
  resuming?: boolean;
  result?: WorkflowRunResumeResult | null;
  onResume?: (request: WorkflowRunResumeRequest) => void;
};

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "-";
}

function reasonForDisabled(plan?: WorkflowRunResumePlan) {
  if (!plan) return "run resume plan missing";
  if (!plan.planHash) return "plan hash missing";
  if (plan.planHash.length !== 64) return "plan hash invalid";
  if (plan.commandPreviewAvailable !== true) return plan.reasonCode || "resume preflight missing";
  if (plan.eligibleNow !== true) return plan.reasonCode || "run resume not eligible";
  if (plan.executionEnabled !== true) {
    return plan.executionReasonCode || plan.activationReadiness?.reasonCode || plan.reasonCode || "run resume disabled";
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
  const workdir = plan.workdirEvidence;
  if (!workdir || workdir.workDirReusable !== true) {
    return workdir?.reasonCode || "workdir reuse blocked";
  }
  if (workdir.pathExposed) return "workdir projection unsafe";
  const outputAudit = plan.incompleteOutputAudit;
  if (!outputAudit || outputAudit.available !== true) return outputAudit?.reasonCode || "output audit unavailable";
  if ((outputAudit.unsafeOutputCount || 0) > 0) return "unsafe outputs present";
  if ((outputAudit.uncheckedOutputCount || 0) > 0 || (outputAudit.unverifiedOutputCount || 0) > 0) {
    return outputAudit.reasonCode || "output audit unverified";
  }
  if (outputAudit.pathExposed) return "output audit projection unsafe";
  const adoption = plan.artifactAdoptionBoundary;
  if (!adoption || (adoption.enabled !== true && adoption.available !== true)) {
    return adoption?.reasonCode || "artifact adoption blocked";
  }
  if (adoption.pathExposed || adoption.storageUriExposed || adoption.checksumValueExposed) {
    return "artifact adoption projection unsafe";
  }
  const orchestration = plan.executorOrchestration;
  if (!orchestration?.contractReady || !orchestration.executorReady) return orchestration?.reasonCode || "executor not ready";
  if (!orchestration.queueMutationAllowed || !orchestration.runStateMutationAllowed) return "executor mutation blocked";
  if (orchestration.pathExposed || orchestration.storageUriExposed) return "executor projection unsafe";
  return "";
}

export function WorkflowRunResumeAction({ plan, resuming = false, result, onResume }: Props) {
  if (!plan) return null;
  const enabled = Boolean(onResume && workflowRunResumeCanSubmit(plan) && !resuming);
  const disabledReason = reasonForDisabled(plan);
  const readiness = plan.activationReadiness;
  const outputAudit = plan.incompleteOutputAudit;
  const planHash = plan.planHash || "";
  function handleClick() {
    if (!enabled || !planHash) return;
    if (!window.confirm("确认提交 run resume？系统会重算当前计划并校验 plan hash 后才会入队。")) return;
    onResume?.({ planHash });
  }

  return (
    <div className="mt-3 rounded-md border border-cyan-200 bg-cyan-50/70 px-3 py-2 text-xs text-cyan-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Play strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">run resume</span>
          <span className="truncate font-mono text-[11px] text-cyan-700">{plan.schemaVersion || "run-resume-plan"}</span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 border-cyan-300 bg-white/90 px-2 text-[11px] text-cyan-900 hover:bg-cyan-100"
          disabled={!enabled}
          title={enabled ? "提交 run resume" : disabledReason}
          onClick={handleClick}
        >
          {resuming ? (
            <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <ShieldCheck strokeWidth={1.5} className="mr-1 h-3 w-3" />
          )}
          提交恢复
        </Button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded border border-cyan-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-cyan-600">plan</div>
          <div className="font-mono text-cyan-950">{shortHash(plan.planHash)}</div>
        </div>
        <div className="rounded border border-cyan-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-cyan-600">readiness</div>
          <div className="font-mono text-cyan-950">
            {readiness?.readyCheckCount ?? 0}/{readiness?.blockedCheckCount ?? 0}
          </div>
        </div>
        <div className="rounded border border-cyan-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-cyan-600">outputs</div>
          <div className="font-mono text-cyan-950">{outputAudit?.verifiedOutputCount ?? 0}</div>
        </div>
        <div className="rounded border border-cyan-200 bg-white/75 px-2 py-1.5">
          <div className="text-[10px] text-cyan-600">rerun</div>
          <div className="font-mono text-cyan-950">{outputAudit?.rerunRequiredOutputCount ?? 0}</div>
        </div>
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-cyan-700">state</span>
        <span className="truncate font-mono">
          {plan.executionEnabled ? "enabled" : "blocked"} · {disabledReason || plan.executionReasonCode || "RUN_RESUME_EXECUTION_ENABLED"}
        </span>
        <span className="text-cyan-700">strategy</span>
        <span className="truncate font-mono">{plan.strategy || "-"}</span>
        <span className="text-cyan-700">last result</span>
        <span className="truncate font-mono">
          {result?.status || "-"} · {result?.reasonCode || result?.scope || "-"}
        </span>
        <span className="text-cyan-700">command</span>
        <span className="truncate font-mono">{result?.commandId || "-"}</span>
      </div>
    </div>
  );
}
