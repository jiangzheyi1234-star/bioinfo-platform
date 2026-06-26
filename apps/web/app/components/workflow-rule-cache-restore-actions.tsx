"use client";

import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { WorkflowRunRuleCacheRestorePlan } from "./workflows-page-model";
import type {
  WorkflowRuleCacheRestoreAction,
  WorkflowRuleCacheRestoreRequest,
  WorkflowRuleCacheRestoreResult,
  WorkflowRuleCacheRestoreStage,
} from "./workflow-rule-cache-restore-model";
import { workflowRuleCacheRestorePlanReady } from "./workflow-rule-cache-restore-model";

type Props = {
  plan?: WorkflowRunRuleCacheRestorePlan;
  attemptId?: string;
  leaseGeneration?: number;
  busyKey?: string;
  lastResult?: WorkflowRuleCacheRestoreResult | null;
  onAction?: (request: WorkflowRuleCacheRestoreRequest) => void;
};

type StageConfig = {
  stage: WorkflowRuleCacheRestoreStage;
  label: string;
  reasonCode: string;
  countLabel: string;
  countValue: number;
  enabled: boolean;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function boolValue(value: unknown) {
  return value === true;
}

function numberValue(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function compactHash(value?: string) {
  return value ? value.slice(0, 12) : "—";
}

function resultCount(result?: WorkflowRuleCacheRestoreResult | null) {
  if (!result) return "—";
  const count =
    result.appliedPinCount ??
    result.stagedFileCount ??
    result.finalOutputCount ??
    result.adoptedArtifactCount ??
    result.verifiedCandidateOutputCount ??
    result.targetCount ??
    0;
  return String(count);
}

function actionKey(stage: WorkflowRuleCacheRestoreStage, action: WorkflowRuleCacheRestoreAction) {
  return `${stage}:${action}`;
}

function stageConfigs(plan: WorkflowRunRuleCacheRestorePlan): StageConfig[] {
  const pins = asRecord(plan.restorePinPolicy);
  const staged = asRecord(plan.stagedFilePolicy);
  const promotion = asRecord((plan as { finalOutputPromotionState?: unknown }).finalOutputPromotionState);
  const hitCount = plan.cacheHitCount || 0;
  const targetCount = numberValue(staged.targetCount);
  const promotedCount = numberValue(promotion.promotedFinalOutputCount);
  return [
    {
      stage: "pins",
      label: "restore pins",
      reasonCode: String(pins.reasonCode || plan.reasonCode || "—"),
      countLabel: "required",
      countValue: numberValue(pins.requiredPinCount),
      enabled: boolValue(pins.pinCreationAllowed) && numberValue(pins.requiredPinCount) > 0,
    },
    {
      stage: "staged-files",
      label: "staged files",
      reasonCode: String(staged.reasonCode || plan.reasonCode || "—"),
      countLabel: "targets",
      countValue: targetCount,
      enabled:
        boolValue(staged.previewAvailable) &&
        (boolValue(staged.materializationEnabled) || boolValue(staged.attemptStagingAllowed)) &&
        hitCount > 0,
    },
    {
      stage: "final-outputs",
      label: "final outputs",
      reasonCode: String(staged.reasonCode || plan.reasonCode || "—"),
      countLabel: "targets",
      countValue: targetCount,
      enabled:
        boolValue(staged.attemptFinalOutputPromotionAllowed) ||
        boolValue(staged.finalOutputMutationAllowed) ||
        numberValue(promotion.candidateOutputCount) > 0,
    },
    {
      stage: "adoption",
      label: "adoption",
      reasonCode: String(promotion.state || staged.reasonCode || plan.reasonCode || "—"),
      countLabel: "promoted",
      countValue: promotedCount,
      enabled: promotedCount > 0 || numberValue(promotion.pendingFinalOutputCount) > 0,
    },
  ];
}

function disabledReason(config: StageConfig, planHash?: string, attemptId?: string, leaseGeneration?: number) {
  if (!planHash) return "plan hash missing";
  if (!attemptId) return "attempt missing";
  if (!leaseGeneration) return "lease missing";
  if (!config.enabled) return config.reasonCode || "stage blocked";
  return "";
}

export function WorkflowRuleCacheRestoreActions({
  plan,
  attemptId,
  leaseGeneration,
  busyKey,
  lastResult,
  onAction,
}: Props) {
  if (!plan || !workflowRuleCacheRestorePlanReady(plan)) return null;
  const planHash = plan.planHash || "";
  const redaction = plan.redactionPolicy || {};
  const unsafeProjection = Boolean(redaction.cacheKeysExposed || redaction.keyPayloadsExposed || redaction.storageUrisExposed || redaction.pathsExposed);
  const actionsEnabled = Boolean(onAction && !unsafeProjection);
  const blockedReason = unsafeProjection ? "unsafe projection" : "";

  function runAction(stage: WorkflowRuleCacheRestoreStage, action: WorkflowRuleCacheRestoreAction, enabled: boolean) {
    if (!onAction || !enabled || !planHash || !attemptId || !leaseGeneration) return;
    if (
      action === "apply" &&
      !window.confirm("确认执行当前 rule cache restore apply 步骤？系统会重新校验 plan hash、attempt 和 lease。")
    ) {
      return;
    }
    onAction({ stage, action, planHash, attemptId, leaseGeneration });
  }

  return (
    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium">rule cache restore actions</span>
          <span className="truncate font-mono text-[11px] text-emerald-700">{plan.schemaVersion || "rule-cache-restore"}</span>
        </div>
        <span className="rounded border border-emerald-300 bg-white/70 px-1.5 py-0.5 font-mono text-[11px] text-emerald-800">
          plan {compactHash(planHash)}
        </span>
      </div>
      <div className="mt-2 grid gap-2 lg:grid-cols-4">
        {stageConfigs(plan).map((config) => {
          const reason = blockedReason || disabledReason(config, planHash, attemptId, leaseGeneration);
          const baseEnabled = actionsEnabled && !reason;
          return (
            <div key={config.stage} className="min-w-0 rounded-md border border-emerald-200 bg-white/75 px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[11px] font-medium text-emerald-900">{config.label}</span>
                <span className="shrink-0 rounded border border-emerald-200 px-1.5 py-0.5 font-mono text-[10px] text-emerald-700">
                  {config.countLabel} {config.countValue}
                </span>
              </div>
              <div className="mt-1 truncate font-mono text-[10px] text-emerald-700">{config.reasonCode}</div>
              <div className="mt-2 grid grid-cols-2 gap-1.5">
                {(["prepare", "apply"] as const).map((action) => {
                  const key = actionKey(config.stage, action);
                  const busy = busyKey === key;
                  const enabled = baseEnabled && !busyKey;
                  return (
                    <Button
                      key={action}
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 border-emerald-300 bg-white/90 px-2 text-[11px] text-emerald-900 hover:bg-emerald-100"
                      disabled={!enabled}
                      title={enabled ? `${config.label} ${action}` : reason || "busy"}
                      onClick={() => runAction(config.stage, action, enabled)}
                    >
                      {busy ? (
                        <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <CheckCircle2 strokeWidth={1.5} className="mr-1 h-3 w-3" />
                      )}
                      {action}
                    </Button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[116px_minmax(0,1fr)]">
        <span className="text-emerald-700">lease fence</span>
        <span className="truncate font-mono">
          {attemptId || "—"} · gen {leaseGeneration ?? "—"}
        </span>
        <span className="text-emerald-700">last result</span>
        <span className="truncate font-mono">
          {lastResult?.status || "—"} · {lastResult?.schemaVersion || "—"} · count {resultCount(lastResult)}
        </span>
        <span className="text-emerald-700">evidence</span>
        <span className="truncate font-mono">{lastResult?.evidenceId || "—"}</span>
        <span className="text-emerald-700">projection</span>
        <span className="truncate font-mono">{unsafeProjection ? "blocked: unsafe fields" : "safe counts only"}</span>
      </div>
    </div>
  );
}
