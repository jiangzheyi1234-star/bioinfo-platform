"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, FileCheck2, Package, RefreshCw, RotateCcw, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { artifactName } from "../_domain/first-run-display";
import { RuleAttemptBadge } from "@/app/components/workflow-run-attempts-panel";
import { WorkflowRuleFailureDiagnostics } from "@/app/components/workflow-rule-failure-diagnostics";
import { WorkflowRuleLogEvidence } from "@/app/components/workflow-rule-log-evidence";
import type {
  WorkflowArtifact,
  WorkflowArtifactPreview,
  WorkflowRun,
  WorkflowRunDetail,
  WorkflowRunRule,
} from "@/app/components/workflows-page-model";

type RulesSummary = NonNullable<NonNullable<WorkflowRunDetail["rules"]>["summary"]>;

const MOVING_PICTURES_EXPECTED_OUTPUTS = [
  {
    name: "summary.tsv",
    label: "样本摘要",
    detail: "sample、body site、matched/passed reads 和 unique_features",
  },
  {
    name: "qc-summary.tsv",
    label: "QC 摘要",
    detail: "reads、通过数、样本数和 feature 数",
  },
  {
    name: "feature-table.tsv",
    label: "Feature table",
    detail: "feature abundance matrix",
  },
  {
    name: "run-report.html",
    label: "HTML report",
    detail: "Top samples 与 QC 卡片",
  },
] as const;

export function RunReportPanel({
  artifacts,
  detail,
  onRefreshRun,
  packageLoading,
  previews,
  run,
}: {
  artifacts: WorkflowArtifact[];
  detail: WorkflowRunDetail | null;
  onRefreshRun: () => void;
  packageLoading: boolean;
  previews: WorkflowArtifactPreview[];
  run: WorkflowRun | null;
}) {
  const rulesSummary = detail?.rules?.summary;
  const stdoutCount = detail?.logs.stdout?.lines?.length || 0;
  const stderrCount = detail?.logs.stderr?.lines?.length || 0;
  const tablePreview = preferredTablePreview(previews);
  const reportPreview = preferredReportPreview(previews);
  const summaryPreview = previewByArtifactName(previews, "summary.tsv");
  const qcPreview = previewByArtifactName(previews, "qc-summary.tsv");
  const insight = movingPicturesInsight(artifacts, summaryPreview, qcPreview, run);
  const rules = detail?.rules?.items || [];
  return (
    <section id="run-report" className="scroll-mt-24 rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <FileCheck2 strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            看懂报告
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{run?.runId || "run not submitted"}</div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {run?.runId ? (
            <Button asChild variant="outline" size="sm" className="h-8 px-2.5 text-xs">
              <Link href={`/workflows/results/detail?run=${encodeURIComponent(run.runId)}`}>
                <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                完整结果
              </Link>
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" className="h-8 px-2 text-xs text-slate-500" disabled={!run?.runId || packageLoading} onClick={onRefreshRun}>
            <RefreshCw strokeWidth={1.5} className="h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>

      {run ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="状态" value={runStatusLabel(run.status)} tone={run.status === "completed" ? "success" : run.status === "failed" || run.status === "error" ? "danger" : "info"} />
          <Metric label="阶段" value={run.stage || "-"} />
          <Metric label="规则" value={formatRuleSummary(rulesSummary)} />
          <Metric label="日志" value={`${stdoutCount} stdout / ${stderrCount} stderr`} />
        </div>
      ) : (
        <div className="mt-4 rounded-md border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-400">
          尚未提交运行
        </div>
      )}

      <FirstRunRuleLevelView detail={detail} run={run} rules={rules} />
      <FirstRunReportInsight insight={insight} />
      {tablePreview?.preview?.columns?.length ? <TablePreview preview={tablePreview} /> : null}
      {reportPreview?.artifact ? (
        <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          HTML 报告已生成：<span className="font-mono text-slate-800">{artifactName(reportPreview.artifact)}</span>
        </div>
      ) : null}
      {artifacts.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {artifacts.map((artifact) => (
            <span key={artifact.artifactId} className="inline-flex max-w-full items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
              <Package strokeWidth={1.5} className="h-3 w-3 shrink-0 text-slate-400" />
              <span className="truncate">{artifactName(artifact)}</span>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function FirstRunRuleLevelView({
  detail,
  rules,
  run,
}: {
  detail: WorkflowRunDetail | null;
  rules: WorkflowRunRule[];
  run: WorkflowRun | null;
}) {
  if (!run?.runId) return null;
  const summary = detail?.rules?.summary;
  const failedRule = firstFailedRule(detail, rules);
  const visibleRules = prioritizedRules(rules).slice(0, 4);
  const rulesReady = rules.length > 0;
  const resultHref = `/workflows/results/detail?run=${encodeURIComponent(run.runId)}`;
  return (
    <div
      className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3"
      data-testid="first-run-rule-level-run-view"
      data-rule-count={rules.length}
      data-rule-projection={rulesReady ? "available" : "pending"}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-900">
            <RotateCcw strokeWidth={1.5} className="h-3.5 w-3.5 text-slate-500" />
            Rule-level run view
          </div>
          <div className="mt-1 text-[11px] leading-4 text-slate-500">
            {rulesReady ? "每个 Snakemake rule 的状态、日志证据和失败定位已接入首跑报告。" : "等待 runner 返回 run-rules projection。"}
          </div>
        </div>
        <Button asChild variant="outline" size="sm" className="h-8 shrink-0 bg-white px-2.5 text-xs">
          <Link href={resultHref}>
            <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
            完整规则 / retry / resume
          </Link>
        </Button>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <RuleMetric label="rules" value={String(summary?.ruleCount ?? rules.length)} />
        <RuleMetric label="failed" value={String(summary?.failedRuleCount ?? rules.filter((rule) => isFailedRule(rule)).length)} tone={failedRule ? "danger" : "neutral"} />
        <RuleMetric label="running" value={String(summary?.runningRuleCount ?? rules.filter((rule) => isRunningRule(rule)).length)} />
        <RuleMetric label="log evidence" value={`${summary?.rulesWithAvailableLogEvidence ?? rules.filter(ruleHasLogEvidence).length}/${summary?.rulesWithLogReferences ?? rules.filter((rule) => (rule.logReferenceCount || 0) > 0).length}`} />
      </div>

      {failedRule ? (
        <WorkflowRuleFailureDiagnostics
          rule={failedRule}
          ruleLogContext={detail?.failureLocator?.ruleLogContext || failedRule.logContext}
        />
      ) : null}

      {visibleRules.length > 0 ? (
        <div className="mt-3 grid gap-2" data-testid="first-run-rule-level-rules">
          {visibleRules.map((rule) => (
            <div
              key={rule.runRuleId || `${rule.ruleName}-${rule.attemptId || rule.attemptNumber || ""}`}
              className="min-w-0 rounded border border-slate-200 bg-white px-3 py-2 text-xs"
              data-first-run-rule-status={rule.status || "unknown"}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={cn("shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium", ruleStatusStyle(rule.status))}>
                      {rule.status || "unknown"}
                    </span>
                    <span className="truncate font-semibold text-slate-900">{rule.ruleName}</span>
                  </div>
                  <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-slate-400">
                    {rule.stepId ? <span className="truncate">step {rule.stepId}</span> : null}
                    {rule.runtimeStatusKey ? <span className="truncate">{rule.runtimeStatusKey}</span> : null}
                    {rule.sourceLocation?.fileBasename ? (
                      <span className="truncate">
                        {rule.sourceLocation.fileBasename}
                        {rule.sourceLocation.line ? `:${rule.sourceLocation.line}` : ""}
                      </span>
                    ) : null}
                  </div>
                </div>
                <RuleAttemptBadge rule={rule} />
              </div>
              <WorkflowRuleLogEvidence rule={rule} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FirstRunReportInsight({ insight }: { insight: ReturnType<typeof movingPicturesInsight> }) {
  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="first-run-report-insight">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold text-slate-900">Moving Pictures 结果解读</div>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px]", insight.ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700")}>
          {insight.ready ? "关键结果完整" : "等待关键结果"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {insight.outputs.map((item) => (
          <div key={item.name} className="min-w-0 rounded border border-slate-200 bg-white px-3 py-2">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-800">
              {item.present ? (
                <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
              ) : (
                <XCircle strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              )}
              <span className="truncate">{item.label}</span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] text-slate-500">{item.name}</div>
            <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{item.detail}</div>
          </div>
        ))}
      </div>
      {insight.metrics.length > 0 ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {insight.metrics.map((metric) => (
            <div key={metric.label} className="rounded border border-slate-200 bg-white px-3 py-2">
              <div className="text-[11px] text-slate-400">{metric.label}</div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-900">{metric.value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TablePreview({ preview }: { preview: WorkflowArtifactPreview }) {
  const columns = preview.preview?.columns || [];
  const rows = preview.preview?.rows || [];
  if (columns.length === 0 || rows.length === 0) return null;
  return (
    <div className="mt-4 overflow-hidden rounded-md border border-slate-200">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-2">
        <span className="truncate text-xs font-medium text-slate-800">{preview.artifact ? artifactName(preview.artifact) : "summary.tsv"}</span>
        <span className="shrink-0 text-[11px] text-slate-400">{rows.length} 行预览</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-white text-slate-500">
            <tr>
              {columns.slice(0, 6).map((column) => (
                <th key={column} className="whitespace-nowrap px-3 py-2 font-medium">{column}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.slice(0, 5).map((row, index) => (
              <tr key={index}>
                {columns.slice(0, 6).map((column, columnIndex) => (
                  <td key={`${column}-${columnIndex}`} className="max-w-[180px] truncate px-3 py-2 text-slate-700">
                    {row[columnIndex] || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ label, tone = "neutral", value }: { label: string; tone?: "neutral" | "success" | "danger" | "info"; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-medium text-slate-400">{label}</div>
      <div
        className={cn(
          "mt-1 truncate text-sm font-semibold",
          tone === "success" ? "text-emerald-700" : tone === "danger" ? "text-red-700" : tone === "info" ? "text-blue-700" : "text-slate-900"
        )}
      >
        {value}
      </div>
    </div>
  );
}

function RuleMetric({
  label,
  tone = "neutral",
  value,
}: {
  label: string;
  tone?: "neutral" | "danger";
  value: string;
}) {
  return (
    <div className="min-w-0 rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className={cn("mt-1 truncate font-mono text-sm font-semibold", tone === "danger" ? "text-red-700" : "text-slate-900")}>
        {value}
      </div>
    </div>
  );
}

export function preferredTablePreview(previews: WorkflowArtifactPreview[]) {
  const tables = previews.filter((preview) => preview.preview?.kind === "table");
  return previewByArtifactName(tables, "summary.tsv") || previewByArtifactName(tables, "qc-summary.tsv") || tables[0];
}

export function preferredReportPreview(previews: WorkflowArtifactPreview[]) {
  return previews.find((preview) => preview.artifact && artifactName(preview.artifact) === "run-report.html");
}

function previewByArtifactName(previews: WorkflowArtifactPreview[], name: string) {
  return previews.find((preview) => preview.artifact && artifactName(preview.artifact) === name);
}

function movingPicturesInsight(
  artifacts: WorkflowArtifact[],
  summaryPreview: WorkflowArtifactPreview | undefined,
  qcPreview: WorkflowArtifactPreview | undefined,
  run: WorkflowRun | null
) {
  const artifactNames = new Set(artifacts.map(artifactName));
  const outputs = MOVING_PICTURES_EXPECTED_OUTPUTS.map((item) => ({
    ...item,
    present: artifactNames.has(item.name),
  }));
  return {
    ready: run?.status === "completed" && outputs.every((item) => item.present),
    outputs,
    metrics: [...summaryMetrics(summaryPreview), ...qcMetrics(qcPreview)].slice(0, 6),
  };
}

function firstFailedRule(detail: WorkflowRunDetail | null, rules: WorkflowRunRule[]) {
  const locatorRuleId = detail?.failureLocator?.failedRule?.runRuleId;
  return (locatorRuleId ? rules.find((rule) => rule.runRuleId === locatorRuleId) : undefined) || rules.find(isFailedRule);
}

function prioritizedRules(rules: WorkflowRunRule[]) {
  return [...rules].sort((left, right) => rulePriority(right) - rulePriority(left));
}

function rulePriority(rule: WorkflowRunRule) {
  if (isFailedRule(rule)) return 4;
  if (isRunningRule(rule)) return 3;
  if (ruleHasLogEvidence(rule)) return 2;
  if (rule.status === "completed" || rule.status === "success" || rule.status === "succeeded") return 1;
  return 0;
}

function isFailedRule(rule: WorkflowRunRule) {
  const status = String(rule.status || "").toLowerCase();
  return status === "failed" || status === "error";
}

function isRunningRule(rule: WorkflowRunRule) {
  const status = String(rule.status || "").toLowerCase();
  return status === "running" || status === "started";
}

function ruleHasLogEvidence(rule: WorkflowRunRule) {
  const context = rule.logContext;
  return Boolean(
    (rule.logReferenceCount || 0) > 0 ||
      context?.status ||
      context?.reasonCode ||
      context?.selectedArtifact?.artifactId ||
      context?.tail?.length
  );
}

function ruleStatusStyle(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "completed" || normalized === "success" || normalized === "succeeded") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (normalized === "failed" || normalized === "error") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  if (normalized === "running" || normalized === "started") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function summaryMetrics(preview: WorkflowArtifactPreview | undefined) {
  const rows = preview?.preview?.rows || [];
  const columns = preview?.preview?.columns || [];
  if (rows.length === 0 || columns.length === 0) return [];
  const passedIndex = columns.indexOf("passed_reads");
  const featuresIndex = columns.indexOf("unique_features");
  return [
    { label: "samples", value: String(rows.length) },
    ...(passedIndex >= 0 ? [{ label: "passed reads", value: formatNumber(sumColumn(rows, passedIndex)) }] : []),
    ...(featuresIndex >= 0 ? [{ label: "unique features", value: formatNumber(sumColumn(rows, featuresIndex)) }] : []),
  ];
}

function qcMetrics(preview: WorkflowArtifactPreview | undefined) {
  const rows = preview?.preview?.rows || [];
  const columns = preview?.preview?.columns || [];
  const metricIndex = columns.indexOf("metric");
  const valueIndex = columns.indexOf("value");
  if (metricIndex < 0 || valueIndex < 0) return [];
  return rows.slice(0, 3).map((row) => ({ label: row[metricIndex] || "metric", value: row[valueIndex] || "" }));
}

function sumColumn(rows: string[][], columnIndex: number) {
  return rows.reduce((total, row) => total + Number(row[columnIndex] || 0), 0);
}

function formatNumber(value: number) {
  return Number.isFinite(value) ? value.toLocaleString("en-US") : "";
}

function formatRuleSummary(summary: RulesSummary | undefined) {
  if (!summary) return "-";
  const count = summary.ruleCount ?? 0;
  const failed = summary.failedRuleCount ?? 0;
  return failed ? `${count} rules / ${failed} failed` : `${count} rules`;
}

function runStatusLabel(status?: string) {
  if (status === "completed") return "完成";
  if (status === "failed" || status === "error") return "失败";
  if (status === "running") return "运行中";
  return status || "-";
}
