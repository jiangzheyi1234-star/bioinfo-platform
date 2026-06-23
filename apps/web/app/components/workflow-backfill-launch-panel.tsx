"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type {
  WorkflowBackfillLaunch,
  WorkflowBackfillLaunchDetail,
  WorkflowBackfillPartition,
  WorkflowBackfillPartitionSummary,
} from "./workflow-backfill-model";

export function WorkflowBackfillLaunchPanel({
  detail,
  detailLoading,
  error,
  launches,
  loading,
  onRefresh,
  onSelectLaunch,
  selectedLaunchId,
}: {
  detail: WorkflowBackfillLaunchDetail | null;
  detailLoading: boolean;
  error: string;
  launches: WorkflowBackfillLaunch[];
  loading: boolean;
  onRefresh: () => void;
  onSelectLaunch: (launchId: string) => void;
  selectedLaunchId: string;
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <CalendarClock strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            回填批次
          </div>
          <div className="mt-1 text-xs text-slate-500">Backfill launches / partitions / triggered runs</div>
        </div>
        <Button type="button" variant="outline" className="h-8 bg-white px-2.5 text-xs" disabled={loading} onClick={onRefresh}>
          <RefreshCw strokeWidth={1.5} className={loading ? "mr-1.5 h-3.5 w-3.5 animate-spin" : "mr-1.5 h-3.5 w-3.5"} />
          刷新回填
        </Button>
      </div>

      {error ? (
        <div className="px-4 pt-4">
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      {loading && launches.length === 0 ? (
        <div className="flex h-28 items-center justify-center text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取回填批次
        </div>
      ) : launches.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-slate-400">暂无回填批次</div>
      ) : (
        <div className="grid gap-0 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
          <div className="border-b border-slate-100 lg:border-b-0 lg:border-r">
            <div className="divide-y divide-slate-100">
              {launches.map((launch) => (
                <button
                  key={launch.launchId}
                  type="button"
                  className={cn(
                    "flex w-full min-w-0 items-start gap-3 px-4 py-3 text-left transition",
                    selectedLaunchId === launch.launchId ? "bg-slate-50" : "hover:bg-slate-50"
                  )}
                  onClick={() => onSelectLaunch(launch.launchId)}
                >
                  <StatusIcon status={launch.state} />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-xs font-medium text-slate-900">{launch.launchId}</span>
                      <span className={cn("shrink-0 rounded border px-1.5 py-0.5 text-[10px]", statusStyle(launch.state))}>
                        {launch.state || "unknown"}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-xs text-slate-500">{launch.triggerId}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <SummaryPill value={`${launch.partitionSummary?.partitionCount ?? launch.partitionCount ?? 0} 分区`} />
                      {launch.partitionSummary?.failedPartitionCount ? (
                        <SummaryPill tone="red" value={`${launch.partitionSummary.failedPartitionCount} 失败`} />
                      ) : null}
                      {launch.partitionSummary?.replayedPartitionCount ? (
                        <SummaryPill tone="amber" value={`${launch.partitionSummary.replayedPartitionCount} 幂等命中`} />
                      ) : null}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="min-w-0 p-4">
            {detailLoading ? (
              <div className="flex h-40 items-center justify-center text-sm text-slate-400">
                <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
                正在读取分区状态
              </div>
            ) : detail ? (
              <BackfillDetail detail={detail} />
            ) : (
              <div className="py-12 text-center text-sm text-slate-400">选择一个回填批次</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function BackfillDetail({ detail }: { detail: WorkflowBackfillLaunchDetail }) {
  const summary = detail.partitionSummary || {};
  const partitions = detail.partitions || [];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <DetailMetric label="分区" value={String(summary.partitionCount ?? detail.partitionCount ?? 0)} />
        <DetailMetric label="运行" value={String(summary.submittedRunCount ?? 0)} />
        <DetailMetric label="失败" value={String(summary.failedPartitionCount ?? 0)} tone={summary.failedPartitionCount ? "red" : "slate"} />
        <DetailMetric label="并发" value={concurrencyLabel(detail)} tone={detail.concurrency?.enforced ? "emerald" : "amber"} />
      </div>

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600 md:grid-cols-2">
        <LabelValue label="范围" value={`${formatDate(detail.range?.start || detail.rangeStart)} → ${formatDate(detail.range?.end || detail.rangeEnd)}`} />
        <LabelValue label="时区" value={detail.range?.timezone || detail.timezone || "—"} />
        <LabelValue label="分区单位" value={detail.range?.partitionUnit || detail.partitionUnit || "—"} />
        <LabelValue label="重算策略" value={detail.reprocessBehavior || "—"} />
        <LabelValue label="顺序" value={detail.range?.runOrder || detail.runOrder || "—"} />
        <LabelValue label="创建者" value={detail.actor || "—"} />
      </div>

      <StateSummary summary={summary} />

      {partitions.length === 0 ? (
        <div className="py-8 text-center text-sm text-slate-400">暂无分区记录</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="w-[18%] px-3 py-2 font-medium">分区</th>
                <th className="w-[15%] px-3 py-2 font-medium">状态</th>
                <th className="w-[22%] px-3 py-2 font-medium">窗口</th>
                <th className="w-[20%] px-3 py-2 font-medium">运行</th>
                <th className="w-[25%] px-3 py-2 font-medium">证据</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {partitions.map((partition) => (
                <PartitionRow key={partition.partitionId} partition={partition} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PartitionRow({ partition }: { partition: WorkflowBackfillPartition }) {
  return (
    <tr>
      <td className="px-3 py-2">
        <div className="truncate font-medium text-slate-800">{partition.partitionKey || partition.partitionId}</div>
        <div className="truncate font-mono text-[10px] text-slate-400">#{partition.index ?? "—"}</div>
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]", statusStyle(partition.state))}>
          {statusLabel(partition.state)}
        </span>
        {partition.dispatch?.state ? <div className="mt-1 truncate text-[10px] text-slate-400">dispatch {partition.dispatch.state}</div> : null}
      </td>
      <td className="px-3 py-2 text-slate-600">
        <div className="truncate">{formatDate(partition.window?.start)}</div>
        <div className="truncate text-slate-400">{formatDate(partition.window?.end)}</div>
      </td>
      <td className="px-3 py-2">
        {partition.runId ? (
          <Link
            href={`/workflows/results/detail?run=${encodeURIComponent(partition.runId)}`}
            className="inline-flex min-w-0 max-w-full items-center gap-1 text-blue-600 hover:text-blue-700"
          >
            <span className="truncate font-mono">{partition.runId}</span>
            <ArrowRight strokeWidth={1.5} className="h-3 w-3 shrink-0" />
          </Link>
        ) : (
          <span className="text-slate-400">—</span>
        )}
        {partition.run?.status ? (
          <div className="mt-1 truncate text-[10px] text-slate-500">{partition.run.status} / {partition.run.stage || "—"}</div>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <div className="truncate font-mono text-[10px] text-slate-500">{partition.triggerEventId || "no trigger event"}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{shortHash(partition.runSpecHash)}</div>
      </td>
    </tr>
  );
}

function StateSummary({ summary }: { summary: WorkflowBackfillPartitionSummary }) {
  const states = Object.entries(summary.states || {});
  if (states.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {states.map(([state, count]) => (
        <span key={state} className={cn("inline-flex items-center rounded border px-2 py-1 text-[11px]", statusStyle(state))}>
          {statusLabel(state)} {count}
        </span>
      ))}
    </div>
  );
}

function DetailMetric({ label, tone = "slate", value }: { label: string; value: string; tone?: "slate" | "emerald" | "amber" | "red" }) {
  const toneClass = {
    slate: "border-slate-200 bg-white text-slate-900",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    red: "border-red-200 bg-red-50 text-red-800",
  }[tone];
  return (
    <div className={cn("rounded-lg border px-3 py-2", toneClass)}>
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  );
}

function LabelValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="text-slate-400">{label}</span>
      <span className="ml-2 break-words font-medium text-slate-700">{value}</span>
    </div>
  );
}

function SummaryPill({ tone = "slate", value }: { tone?: "slate" | "amber" | "red"; value: string }) {
  const toneClass = {
    slate: "border-slate-200 bg-white text-slate-500",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-700",
  }[tone];
  return <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", toneClass)}>{value}</span>;
}

function StatusIcon({ status }: { status?: string }) {
  const s = String(status || "").toLowerCase();
  if (s === "submitted" || s === "completed" || s === "success") {
    return <CheckCircle2 strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />;
  }
  if (s === "failed" || s === "error") {
    return <XCircle strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />;
  }
  if (s === "replayed") {
    return <RotateCcw strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />;
  }
  if (s === "launching" || s === "pending") {
    return <Loader2 strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-blue-500" />;
  }
  return <Clock strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />;
}

function statusStyle(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  if (s === "submitted" || s === "completed" || s === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (s === "failed" || s === "error") return "border-red-200 bg-red-50 text-red-700";
  if (s === "launching" || s === "pending" || s === "running") return "border-blue-200 bg-blue-50 text-blue-700";
  if (s === "replayed") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function statusLabel(status: string | undefined) {
  const s = String(status || "").toLowerCase();
  if (s === "replayed") return "幂等命中";
  if (s === "submitted") return "已提交";
  if (s === "pending") return "待提交";
  if (s === "launching") return "提交中";
  return status || "unknown";
}

function concurrencyLabel(detail: WorkflowBackfillLaunchDetail) {
  const limit = detail.concurrency?.limit || "—";
  const enforced = detail.concurrency?.enforced ? "强制" : "未强制";
  return `${limit} / ${enforced}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function shortHash(value?: string) {
  if (!value) return "no runSpec hash";
  return value.length > 16 ? `${value.slice(0, 16)}…` : value;
}
