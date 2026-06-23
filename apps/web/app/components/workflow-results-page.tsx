"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, ArrowRight, CalendarClock, CheckCircle2, Clock, Loader2, RefreshCw, XCircle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { fetchWorkflowBackfillLaunches } from "./workflow-backfill-api";
import { fetchWorkflowTriggers } from "./workflow-trigger-api";
import { fetchRunsList } from "./workflows-page-api";
import { workflowErrorMessage, type WorkflowRun } from "./workflows-page-model";
import { WorkflowPageHeader } from "./workflow-page-header";

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "success") {
    return <span className="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700"><CheckCircle2 strokeWidth={1.5} className="h-3 w-3" />完成</span>;
  }
  if (s === "failed" || s === "error") {
    return <span className="inline-flex items-center gap-1 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[11px] text-red-700"><XCircle strokeWidth={1.5} className="h-3 w-3" />失败</span>;
  }
  if (s === "running") {
    return <span className="inline-flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700"><Loader2 strokeWidth={1.5} className="h-3 w-3 animate-spin" />运行中</span>;
  }
  return <span className="inline-flex items-center gap-1 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600"><Clock strokeWidth={1.5} className="h-3 w-3" />{status}</span>;
}

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "running", label: "运行中" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "失败" },
];

export function WorkflowResultsPage() {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");

  const load = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      const items = await fetchRunsList({ forceRefresh });
      setRuns(items);
    } catch (err) {
      setError(workflowErrorMessage(err, "读取运行记录失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(() => {
    return [...runs].sort((a, b) => {
      const ta = a.createdAt ? new Date(a.createdAt).getTime() : 0;
      const tb = b.createdAt ? new Date(b.createdAt).getTime() : 0;
      return tb - ta;
    });
  }, [runs]);

  const filtered = useMemo(() => {
    if (filter === "all") return sorted;
    return sorted.filter((r) => r.status.toLowerCase() === filter);
  }, [sorted, filter]);

  return (
    <div className="relative flex-1 w-full h-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <div className="mx-auto max-w-5xl space-y-6">
        <WorkflowPageHeader
          title="运行记录"
          actions={
            <div className="flex items-center gap-2">
              <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
                <Link
                  href="/workflows/results/triggers"
                  onFocus={() => void fetchWorkflowTriggers().catch(() => undefined)}
                  onPointerEnter={() => void fetchWorkflowTriggers().catch(() => undefined)}
                >
                  <Activity strokeWidth={1.5} className="mr-2 h-4 w-4" />
                  触发器事件
                </Link>
              </Button>
              <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
                <Link
                  href="/workflows/results/backfills"
                  onFocus={() => void fetchWorkflowBackfillLaunches().catch(() => undefined)}
                  onPointerEnter={() => void fetchWorkflowBackfillLaunches().catch(() => undefined)}
                >
                  <CalendarClock strokeWidth={1.5} className="mr-2 h-4 w-4" />
                  回填批次
                </Link>
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-9 bg-white px-3 text-slate-600"
                disabled={loading}
                onClick={() => void load(true)}
              >
                <RefreshCw strokeWidth={1.5} className={loading ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
                刷新
              </Button>
            </div>
          }
        />

        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex items-center gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-xs font-medium transition",
                filter === f.key
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取运行记录
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-12 text-center text-sm text-slate-400">
            {filter === "all" ? "暂无运行记录" : "该状态下暂无运行记录"}
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">状态</th>
                  <th className="px-4 py-2 font-medium">Run ID</th>
                  <th className="px-4 py-2 font-medium">阶段</th>
                  <th className="px-4 py-2 font-medium">提交时间</th>
                  <th className="px-4 py-2 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((run) => (
                  <tr key={run.runId} className="bg-white">
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">{run.runId}</td>
                    <td className="px-4 py-3 text-xs text-slate-600">{run.stage || "—"}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {run.createdAt ? new Date(run.createdAt).toLocaleString("zh-CN") : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/workflows/results/detail?run=${encodeURIComponent(run.runId)}`}
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                      >
                        查看结果 <ArrowRight strokeWidth={1.5} className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
