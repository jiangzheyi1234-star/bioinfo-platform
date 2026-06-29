"use client";

import { CheckCircle2, ClipboardCheck, Cpu, Database, FileArchive, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

import type { FirstRunValidationCard } from "../_domain/first-run-types";
import type { WorkflowResultPackageExport } from "@/app/components/workflows-page-model";

type TrustTone = "success" | "waiting";

export function FirstRunTrustSummary({
  card,
  packageExport,
}: {
  card: FirstRunValidationCard | null;
  packageExport?: WorkflowResultPackageExport;
}) {
  const resultPackage = card?.resultPackage || packageExport;
  const checks = card?.checks || [];
  const passedChecks = checks.filter((item) => item.status === "passed").length;
  const allChecksPassed = checks.length > 0 && passedChecks === checks.length;
  const summaryReady = Boolean(card) && allChecksPassed;
  const sampleItems = card?.sampleData?.items || [];
  const keyResults = card?.keyResults || [];
  const packageHash = resultPackage?.sha256 || "";
  const manifestHash = resultPackage?.manifestSha256 || "";
  const fullPackage = resultPackage?.artifactPayloadMode === "full" || resultPackage?.includeArtifacts === true;
  const software = card?.softwareEnvironment;
  const runtime = [software?.runtime?.engine, software?.runtime?.platform, software?.runtime?.pipelineVersion]
    .filter(Boolean)
    .join(" / ");
  const items = [
    {
      label: "官方样例输入",
      detail:
        card?.sampleData?.status === "verified"
          ? `${sampleItems.length} 个 Moving Pictures 输入 checksum 通过`
          : "等待样例输入完整性证据",
      tone: card?.sampleData?.status === "verified" ? "success" : "waiting",
      icon: ClipboardCheck,
    },
    {
      label: "软件环境",
      detail: software?.status === "verified" ? runtime || "运行环境和流程内容已锁定" : "等待运行环境证据",
      tone: software?.status === "verified" ? "success" : "waiting",
      icon: Cpu,
    },
    {
      label: "数据库",
      detail: "Moving Pictures 首跑不需要外部参考数据库",
      tone: "success",
      icon: Database,
    },
    {
      label: "关键结果",
      detail:
        card?.reportInterpretation?.status === "ready"
          ? `${keyResults.length} 个关键输出和 ${card.reportInterpretation.metrics?.length || 0} 个指标可读`
          : "等待报告解读证据",
      tone: card?.reportInterpretation?.status === "ready" ? "success" : "waiting",
      icon: CheckCircle2,
    },
    {
      label: "结果包",
      detail:
        fullPackage && packageHash && manifestHash
          ? `完整包 ${shortHash(packageHash)} / manifest ${shortHash(manifestHash)}`
          : "等待完整结果包和 hash",
      tone: fullPackage && packageHash && manifestHash ? "success" : "waiting",
      icon: FileArchive,
    },
  ] satisfies Array<{ label: string; detail: string; tone: TrustTone; icon: typeof CheckCircle2 }>;
  return (
    <div
      className={cn(
        "rounded-md border p-3",
        summaryReady ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"
      )}
      data-testid="first-run-trust-summary"
      data-summary-ready={summaryReady ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className={cn("flex min-w-0 items-center gap-2 text-xs font-semibold", summaryReady ? "text-emerald-950" : "text-amber-950")}>
          {summaryReady ? (
            <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
          ) : (
            <XCircle strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-600" />
          )}
          <span className="truncate">这次结果为什么可信</span>
        </div>
        <span
          className={cn(
            "rounded-full border bg-white px-2 py-0.5 text-[11px]",
            summaryReady ? "border-emerald-200 text-emerald-700" : "border-amber-200 text-amber-700"
          )}
        >
          {checks.length ? `${passedChecks}/${checks.length} checks` : "waiting"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5" data-testid="first-run-trust-summary-items">
        {items.map((item) => (
          <TrustItem key={item.label} item={item} />
        ))}
      </div>
    </div>
  );
}

function TrustItem({
  item,
}: {
  item: { label: string; detail: string; tone: TrustTone; icon: typeof CheckCircle2 };
}) {
  const Icon = item.icon;
  return (
    <div className="min-w-0 rounded border border-emerald-200 bg-white px-3 py-2">
      <div className="flex min-w-0 items-center gap-2 text-[11px] font-semibold text-slate-800">
        <Icon
          strokeWidth={1.5}
          className={cn("h-3.5 w-3.5 shrink-0", item.tone === "success" ? "text-emerald-500" : "text-amber-500")}
        />
        <span className="truncate">{item.label}</span>
      </div>
      <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{item.detail}</div>
    </div>
  );
}

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "";
}
