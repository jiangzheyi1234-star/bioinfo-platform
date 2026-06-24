"use client";

import type { WorkflowRunRule, WorkflowRunRuleEvent, WorkflowRunRuleLogContext } from "./workflows-page-model";

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

export function WorkflowRuleFailureDiagnostics({
  rule,
  ruleLogContext,
}: {
  rule?: WorkflowRunRule;
  ruleLogContext?: WorkflowRunRuleLogContext;
}) {
  if (!rule || !isFailedStatus(rule.status)) return null;
  const failedEvent = [...(rule.events || [])].reverse().find(isFailureEvent);
  const logs = rule.logs || [];
  const detailItems = scalarDetails(failedEvent?.details);
  const logTail = ruleLogContext?.tail || [];
  const selectedLogArtifact = ruleLogContext?.selectedArtifact;

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
        {ruleLogContext ? (
          <>
            <span className="text-red-500">log evidence</span>
            <span className="truncate font-mono">{ruleLogContext.reasonCode || ruleLogContext.status || "—"}</span>
            <span className="text-red-500">artifact</span>
            <span className="truncate font-mono">
              {selectedLogArtifact?.artifactId || selectedLogArtifact?.path || ruleLogContext.message || "—"}
            </span>
          </>
        ) : null}
        {detailItems.length > 0 ? (
          <>
            <span className="text-red-500">details</span>
            <span className="truncate font-mono">{detailItems.join(", ")}</span>
          </>
        ) : null}
      </div>
      {logTail.length > 0 ? (
        <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap rounded-md bg-slate-950 p-2 text-[11px] text-red-100">
          {logTail.join("\n")}
        </pre>
      ) : null}
    </div>
  );
}
