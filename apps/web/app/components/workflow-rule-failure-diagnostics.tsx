"use client";

import type { WorkflowRunRule, WorkflowRunRuleEvent } from "./workflows-page-model";

function isFailedStatus(status?: string) {
  const normalized = String(status || "").toLowerCase();
  return normalized === "failed" || normalized === "error";
}

function isFailureEvent(event: WorkflowRunRuleEvent) {
  return isFailedStatus(event.status) || /fail|error/i.test(event.eventType || "");
}

function scalarDetails(details?: Record<string, unknown>) {
  if (!details) return [];
  return Object.entries(details)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`);
}

function ruleLocator(rule: WorkflowRunRule) {
  return [
    rule.stepId ? `step ${rule.stepId}` : "",
    rule.runtimeStatusKey || "",
    rule.runRuleId || "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function WorkflowRuleFailureDiagnostics({ rule }: { rule?: WorkflowRunRule }) {
  if (!rule || !isFailedStatus(rule.status)) return null;
  const failedEvent = [...(rule.events || [])].reverse().find(isFailureEvent);
  const logs = rule.logs || [];
  const detailItems = scalarDetails(failedEvent?.details);

  return (
    <div className="mt-3 border-l-2 border-red-300 bg-red-50/70 py-2 pl-3 pr-2 text-xs text-red-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium">失败定位</div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-red-700">{ruleLocator(rule) || rule.ruleName}</div>
        </div>
        <div className="shrink-0 font-mono text-[11px] text-red-700">
          #{rule.attemptNumber ?? "—"} · lease {rule.leaseGeneration ?? "—"}
        </div>
      </div>
      <div className="mt-2 grid gap-1 text-[11px] sm:grid-cols-[88px_minmax(0,1fr)]">
        <span className="text-red-500">event</span>
        <span className="truncate font-mono">{failedEvent?.eventType || failedEvent?.status || "—"}</span>
        <span className="text-red-500">message</span>
        <span className="truncate">{failedEvent?.message || rule.message || "—"}</span>
        <span className="text-red-500">log paths</span>
        <span className="truncate font-mono">{logs.length > 0 ? logs.slice(0, 4).join(", ") : "—"}</span>
        {detailItems.length > 0 ? (
          <>
            <span className="text-red-500">details</span>
            <span className="truncate font-mono">{detailItems.join(", ")}</span>
          </>
        ) : null}
      </div>
    </div>
  );
}
