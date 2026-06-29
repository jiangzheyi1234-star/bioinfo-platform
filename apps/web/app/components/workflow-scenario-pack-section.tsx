"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, CircleAlert, Database, ExternalLink, FlaskConical, Loader2, ShieldCheck } from "lucide-react";

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
              <ScenarioFact icon="evidence" label="样例" value={sampleDataLabel(pack)} />
              <ScenarioFact icon="evidence" label="证据" value={pack.resultEvidence.join(" / ")} />
            </div>

            <ToolSliceHandoffSummary pack={pack} />
            <SampleDataHandoffSummary pack={pack} />
            <DatabaseHandoffSummary pack={pack} />
            <PilotReadinessPlanSummary pack={pack} />

            <div className="mt-3 space-y-2" data-testid="workflow-scenario-readiness-checks">
              {pack.readinessChecks.map((check) => (
                <div
                  key={check.code}
                  className="grid min-w-0 gap-1 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px]"
                  data-scenario-check-status={check.status}
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                  {check.status === "passed" ? (
                    <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                  ) : (
                    <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                  )}
                    <span className="truncate font-medium text-slate-700">{check.requirement}</span>
                  </div>
                  <div className="truncate pl-5 text-slate-500">{check.detail}</div>
                </div>
              ))}
            </div>

            {pack.externalPracticeAnchors.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5" data-testid="workflow-scenario-practice-anchors">
                {pack.externalPracticeAnchors.slice(0, 2).map((href, index) => (
                  <a
                    key={href}
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex max-w-full items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-500 hover:border-blue-200 hover:text-blue-700"
                  >
                    <ExternalLink strokeWidth={1.5} className="h-3 w-3 shrink-0" />
                    <span className="truncate">实践参考 {index + 1}</span>
                  </a>
                ))}
              </div>
            ) : null}

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
              {toolSliceNeedsOperator(pack) ? (
                <Button asChild variant="outline" className="h-8 bg-white px-2.5 text-xs text-slate-600" data-scenario-action="TOOL_SLICE_PROMOTION">
                  <Link href="/workflows/tools">
                    <FlaskConical strokeWidth={1.5} className="h-3.5 w-3.5" />
                    工具验收
                  </Link>
                </Button>
              ) : null}
              {databaseHandoffNeedsOperator(pack) ? (
                <Button asChild variant="outline" className="h-8 bg-white px-2.5 text-xs text-slate-600" data-scenario-action="DATABASE_HANDOFF_WALKTHROUGH">
                  <Link href={pack.databaseHandoff?.readyScan?.path ? "/workflows/databases" : "/workflows"}>
                    <Database strokeWidth={1.5} className="h-3.5 w-3.5" />
                    数据库陪跑
                  </Link>
                </Button>
              ) : null}
              {pack.nextActions.slice(0, 3).map((action) => (
                <Button key={action.code} asChild variant="outline" className="h-8 bg-white px-2.5 text-xs text-slate-600" data-scenario-action={action.code}>
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

function PilotReadinessPlanSummary({ pack }: { pack: WorkflowScenarioPack }) {
  const plan = pack.pilotReadinessPlan;
  const checklist = plan?.acceptanceChecklist || [];
  if (!plan || checklist.length === 0 || plan.status === "ready") return null;
  const visibleItems = checklist.slice(0, 3);
  const remaining = checklist.length - visibleItems.length;
  return (
    <div className="mt-3 rounded border border-blue-200 bg-blue-50 px-2 py-2" data-testid="workflow-scenario-pilot-readiness-plan">
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-blue-950">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-blue-600" />
          <span className="truncate">试点验收计划</span>
        </div>
        <span className="shrink-0 rounded border border-blue-200 bg-white px-1.5 py-0.5 text-[10px] text-blue-700">
          {plan.mode || "human-reviewed-scenario-pilot"}
        </span>
      </div>
      <div className="grid gap-1 text-[11px]" data-testid="workflow-scenario-pilot-readiness-checklist">
        {visibleItems.map((item) => (
          <div key={item.code || item.label} className="flex min-w-0 items-center gap-1.5 text-slate-600">
            <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span className="truncate">{item.label || item.code}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-blue-700">
        {pilotReadinessPlanText(pack)}
        {remaining > 0 ? ` · +${remaining}` : ""}
      </div>
    </div>
  );
}

function ToolSliceHandoffSummary({ pack }: { pack: WorkflowScenarioPack }) {
  const handoff = pack.toolSliceHandoff;
  const checklist = handoff?.checklist || [];
  if (checklist.length === 0 || handoff?.status === "ready") return null;
  const visibleItems = checklist.slice(0, 2);
  const remaining = checklist.length - visibleItems.length;
  const pendingEvidenceCount = (handoff?.toolOptions || []).filter(
    (item) => item.acceptanceEvidenceContract?.status !== "accepted"
  ).length;
  return (
    <div className="mt-3 rounded border border-slate-200 bg-slate-50 px-2 py-2" data-testid="workflow-scenario-tool-slice-handoff">
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-slate-700">
          <FlaskConical strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">工具切片</span>
        </div>
        <span className="shrink-0 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
          {handoff?.requiredState || "WorkflowReady"}
        </span>
      </div>
      <div className="grid gap-1" data-testid="workflow-scenario-tool-slice-handoff-checklist">
        {visibleItems.map((item) => (
          <div key={item.code || item.label} className="flex min-w-0 items-center gap-1.5 text-[11px] text-slate-600">
            <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span className="truncate">{item.label || item.code}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-slate-400">
        {toolSliceHandoffText(pack)}
        {remaining > 0 ? ` · +${remaining}` : ""}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-slate-500" data-testid="workflow-scenario-tool-slice-promotion-contract">
        Evidence: {(handoff?.promotionContract?.requiredEvidence || []).slice(0, 4).join(" / ")}
        {pendingEvidenceCount > 0 ? ` · ${pendingEvidenceCount} tool contracts pending` : ""}
      </div>
    </div>
  );
}

function SampleDataHandoffSummary({ pack }: { pack: WorkflowScenarioPack }) {
  const handoff = pack.sampleDataHandoff;
  const checklist = handoff?.checklist || [];
  if (checklist.length === 0 || handoff?.status === "ready") return null;
  const visibleItems = checklist.slice(0, 2);
  const remaining = checklist.length - visibleItems.length;
  return (
    <div className="mt-3 rounded border border-slate-200 bg-slate-50 px-2 py-2" data-testid="workflow-scenario-sample-data-handoff">
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-slate-700">
          <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">样例陪跑</span>
        </div>
        <span className="shrink-0 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
          {handoff?.mode || "operator_provided"}
        </span>
      </div>
      <div className="grid gap-1" data-testid="workflow-scenario-sample-data-handoff-checklist">
        {visibleItems.map((item) => (
          <div key={item.code || item.label} className="flex min-w-0 items-center gap-1.5 text-[11px] text-slate-600">
            <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span className="truncate">{item.label || item.code}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-slate-400">
        {sampleDataHandoffInputText(pack)}
        {remaining > 0 ? ` · +${remaining}` : ""}
      </div>
    </div>
  );
}

function DatabaseHandoffSummary({ pack }: { pack: WorkflowScenarioPack }) {
  const handoff = pack.databaseHandoff;
  const checklist = handoff?.checklist || [];
  if (checklist.length === 0 || handoff?.status === "not_required") return null;
  const visibleItems = checklist.slice(0, 3);
  const remaining = checklist.length - visibleItems.length;
  return (
    <div className="mt-3 rounded border border-slate-200 bg-slate-50 px-2 py-2" data-testid="workflow-scenario-database-handoff">
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-slate-700">
          <Database strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">数据库陪跑</span>
        </div>
        <span className="shrink-0 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
          {handoff?.mode || "manual_external"}
        </span>
      </div>
      <div className="grid gap-1" data-testid="workflow-scenario-database-handoff-checklist">
        {visibleItems.map((item) => (
          <div key={item.code || item.label} className="flex min-w-0 items-center gap-1.5 text-[11px] text-slate-600">
            {item.status === "passed" ? (
              <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
            ) : (
              <CircleAlert strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
            )}
            <span className="truncate">{item.label || item.code}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-slate-400">
        {databaseHandoffTemplateText(pack)}
        {remaining > 0 ? ` · +${remaining}` : ""}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-slate-500" data-testid="workflow-scenario-database-ready-scan-contract">
        Ready scan: {handoff?.readyScan?.path || "-"} · Prefill: {handoff?.registration?.prefillSource || "-"}
      </div>
      <DatabasePackOptionSummary pack={pack} />
    </div>
  );
}

function DatabasePackOptionSummary({ pack }: { pack: WorkflowScenarioPack }) {
  const packOptions = pack.databaseHandoff?.packOptions || [];
  const missingTemplates = pack.databaseHandoff?.missingPackTemplates || [];
  if (packOptions.length === 0 && missingTemplates.length === 0) return null;
  return (
    <div className="mt-2 grid gap-1" data-testid="workflow-scenario-database-pack-options">
      {packOptions.slice(0, 2).map((item) => (
        <div key={item.packId || item.templateId || item.name} className="min-w-0 truncate text-[11px] text-slate-500">
          <span className="font-mono text-slate-700">{item.packId || item.templateId}</span>
          {item.checksum ? <span> · {item.checksum}</span> : null}
        </div>
      ))}
      {missingTemplates.length > 0 ? (
        <div className="min-w-0 truncate text-[11px] text-amber-700" data-testid="workflow-scenario-database-missing-packs">
          缺少 pack: {missingTemplates.slice(0, 4).join(" / ")}
        </div>
      ) : null}
    </div>
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
    .map((item) => `${item.name || item.toolId || item.kind || "tool"}:${item.contractState || "unknown"}`)
    .join(", ");
}

function toolSliceHandoffText(pack: WorkflowScenarioPack) {
  return (pack.toolSliceHandoff?.toolOptions || pack.requiredWorkflowReadyTools)
    .map((item) => [item.role, item.contractState].filter(Boolean).join(":"))
    .slice(0, 4)
    .join(" / ");
}

function databaseLabel(pack: WorkflowScenarioPack) {
  if (pack.requiredDatabases.length === 0) return "none";
  return pack.requiredDatabases
    .map((item) => [item.capability || "database", item.templates?.length ? `(${item.templates.join("/")})` : ""].filter(Boolean).join(" "))
    .join(", ");
}

function databaseHandoffTemplateText(pack: WorkflowScenarioPack) {
  const options = pack.databaseHandoff?.templateOptions || pack.requiredDatabases;
  return options
    .flatMap((item) => item.templates || [])
    .slice(0, 4)
    .join(" / ");
}

function sampleDataHandoffInputText(pack: WorkflowScenarioPack) {
  return (pack.sampleDataHandoff?.inputOptions || [])
    .map((item) => [item.role, item.formats?.join("/")].filter(Boolean).join(":"))
    .slice(0, 4)
    .join(" / ");
}

function sampleDataLabel(pack: WorkflowScenarioPack) {
  return [pack.sampleData.mode, pack.sampleData.source].filter(Boolean).join(" / ");
}

function pilotReadinessPlanText(pack: WorkflowScenarioPack) {
  const plan = pack.pilotReadinessPlan;
  const inputs = (plan?.minimumInputs || [])
    .map((item) => item.role)
    .filter(Boolean)
    .slice(0, 3)
    .join("/");
  const evidence = (plan?.acceptanceEvidence || []).slice(0, 4).join("/");
  const blockers = plan?.blockingGateCodes?.length || 0;
  return [inputs ? `inputs:${inputs}` : "", evidence ? `evidence:${evidence}` : "", blockers ? `${blockers} gates` : ""]
    .filter(Boolean)
    .join(" · ");
}

function databaseHandoffNeedsOperator(pack: WorkflowScenarioPack) {
  return pack.databaseHandoff?.mode === "manual_external" && pack.databaseHandoff?.operatorActionRequired === true;
}

function toolSliceNeedsOperator(pack: WorkflowScenarioPack) {
  return pack.toolSliceHandoff?.requiredState === "WorkflowReady" && pack.toolSliceHandoff?.operatorActionRequired === true;
}
