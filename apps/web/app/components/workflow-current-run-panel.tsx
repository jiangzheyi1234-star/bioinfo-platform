"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

import type { WorkflowRun, WorkflowRunDetail } from "./workflows-page-model";

function RunStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "success") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
        <CheckCircle2 strokeWidth={1.5} className="h-3 w-3" />
        完成
      </span>
    );
  }
  if (s === "failed" || s === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700">
        <XCircle strokeWidth={1.5} className="h-3 w-3" />
        失败
      </span>
    );
  }
  if (s === "running") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
        <Loader2 strokeWidth={1.5} className="h-3 w-3 animate-spin" />
        运行中
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600">
      <Clock strokeWidth={1.5} className="h-3 w-3" />
      {status}
    </span>
  );
}

export function WorkflowCurrentRunPanel({
  run,
  detail,
}: {
  run: WorkflowRun | null;
  detail: WorkflowRunDetail | null;
}) {
  if (!run) return null;

  const artifacts = detail?.results?.artifacts || [];
  const failed = run.status === "failed" || run.status === "error";
  const completed = run.status === "completed" || run.status === "success";
  const running = run.status === "running";

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">当前运行</h3>
        <RunStatusBadge status={run.status} />
      </div>

      <div className="space-y-2">
        <div>
          <div className="text-[11px] text-slate-400">Run ID</div>
          <div className="mt-0.5 font-mono text-xs text-slate-700">{run.runId}</div>
        </div>

        <div>
          <div className="text-[11px] text-slate-400">阶段</div>
          <div className="mt-0.5 text-sm font-medium text-slate-800">{run.stage || "—"}</div>
        </div>

        {run.message && (
          <div>
            <div className="text-[11px] text-slate-400">消息</div>
            <div className={cn("mt-0.5 text-xs", failed ? "text-red-600" : "text-slate-600")}>{run.message}</div>
          </div>
        )}

        {artifacts.length > 0 && (
          <div>
            <div className="text-[11px] text-slate-400">产物</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {artifacts.map((a) => (
                <span key={a.artifactId} className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                  {a.kind}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="pt-1">
        <Link
          href={`/workflows/results/detail?run=${encodeURIComponent(run.runId)}`}
          className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
        >
          查看完整结果 <ArrowRight strokeWidth={1.5} className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}
