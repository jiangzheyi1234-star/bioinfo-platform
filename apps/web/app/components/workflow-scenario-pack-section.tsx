"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, CircleAlert, Database, FlaskConical, Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { WorkflowScenarioPack } from "./workflows-page-model";

export function WorkflowScenarioPackSection({
  error,
  loading,
  packs,
}: {
  error: string;
  loading: boolean;
  packs: WorkflowScenarioPack[];
}) {
  if (!loading && !error && packs.length === 0) return null;
  return (
    <section className="rounded-lg border border-slate-200 bg-white" data-testid="workflow-scenario-pack-section">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-950">
          <FlaskConical strokeWidth={1.5} className="h-4 w-4 shrink-0 text-blue-600" />
          <span className="truncate">场景包</span>
        </div>
        {loading ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin text-slate-400" /> : null}
      </div>

      {error ? <div className="px-4 py-3 text-sm text-red-600">{error}</div> : null}

      <div className="grid divide-y divide-slate-100 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        {packs.map((pack) => (
          <article key={pack.packId} className="min-w-0 p-4" data-scenario-pack={pack.scenarioId} data-scenario-status={pack.status}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-950">{pack.name}</div>
                <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{pack.pipelineId}</div>
              </div>
              <ScenarioStatus status={pack.status} />
            </div>

            <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-600">{pack.summary}</p>

            <div className="mt-3 grid gap-2 text-[11px] text-slate-600">
              <ScenarioFact icon="tools" label="工具" value={toolSliceLabel(pack)} />
              <ScenarioFact icon="database" label="数据库" value={databaseLabel(pack)} />
              <ScenarioFact icon="evidence" label="证据" value={pack.resultEvidence.join(" / ")} />
            </div>

            <div className="mt-3 space-y-1.5">
              {pack.readinessChecks.slice(0, 4).map((check) => (
                <div key={check.code} className="flex min-w-0 items-center gap-1.5 text-[11px]">
                  {check.status === "passed" ? (
                    <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                  ) : (
                    <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                  )}
                  <span className="truncate text-slate-500">{check.detail}</span>
                </div>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {pack.status === "ready" && pack.firstRunPath ? (
                <Button asChild className="h-8 px-2.5 text-xs">
                  <Link href={pack.firstRunPath}>
                    <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                    首跑
                  </Link>
                </Button>
              ) : null}
              {pack.workflowPath ? (
                <Button asChild variant="outline" className="h-8 bg-white px-2.5 text-xs">
                  <Link href={pack.workflowPath}>
                    <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                    流程
                  </Link>
                </Button>
              ) : null}
              {pack.nextActions.slice(0, 2).map((action) => (
                <Button key={action.code} asChild variant="outline" className="h-8 bg-white px-2.5 text-xs text-slate-600">
                  <Link href={action.target}>
                    <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                    {action.label}
                  </Link>
                </Button>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ScenarioStatus({ status }: { status: string }) {
  const ready = status === "ready";
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded border px-2 text-[11px]",
        ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
      )}
    >
      {ready ? <CheckCircle2 strokeWidth={1.5} className="h-3 w-3" /> : <CircleAlert strokeWidth={1.5} className="h-3 w-3" />}
      {ready ? "ready" : "blocked"}
    </span>
  );
}

function ScenarioFact({
  icon,
  label,
  value,
}: {
  icon: "database" | "evidence" | "tools";
  label: string;
  value: string;
}) {
  const Icon = icon === "database" ? Database : icon === "evidence" ? ShieldCheck : FlaskConical;
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Icon strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-400" />
      <span className="shrink-0 text-slate-400">{label}</span>
      <span className="truncate text-slate-700">{value || "-"}</span>
    </div>
  );
}

function toolSliceLabel(pack: WorkflowScenarioPack) {
  return pack.requiredWorkflowReadyTools
    .map((item) => `${item.kind || "tool"}:${item.count || 1}`)
    .join(", ");
}

function databaseLabel(pack: WorkflowScenarioPack) {
  if (pack.requiredDatabases.length === 0) return "none";
  return pack.requiredDatabases.map((item) => item.capability || "database").join(", ");
}
