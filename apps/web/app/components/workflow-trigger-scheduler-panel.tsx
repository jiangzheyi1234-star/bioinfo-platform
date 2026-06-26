"use client";

import { useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { WorkflowTriggerSchedulerTick } from "./workflow-trigger-model";

const SCHEDULER_RUN_ONCE_CONFIRMATION = "run-scheduler-once";

export function WorkflowTriggerSchedulerPanel({
  onRunSchedulerOnce,
  runningScheduler,
  ticks,
}: {
  onRunSchedulerOnce: () => void;
  runningScheduler: boolean;
  ticks: WorkflowTriggerSchedulerTick[];
}) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const latest = ticks[0] || null;
  const cron = latest?.cron || {};
  const backfills = latest?.backfills || {};

  function closeDialog(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) setConfirmation("");
  }

  function confirmRunOnce() {
    if (confirmation.trim() !== SCHEDULER_RUN_ONCE_CONFIRMATION || runningScheduler) return;
    onRunSchedulerOnce();
    closeDialog(false);
  }

  return (
    <div className="border-b border-slate-100 px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-700">Scheduler ticks</div>
          <div className="mt-1 text-[11px] text-slate-400">
            {latest ? `latest ${shortIdentity(latest.tickId, "tick")}` : "no tick evidence"}
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={runningScheduler}
          onClick={() => setOpen(true)}
        >
          {runningScheduler ? (
            <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          )}
          运行一次 scheduler
        </Button>
      </div>
      {latest ? (
        <div className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
          <SchedulerMetric label="Cron due" value={numberLabel(cron.due)} sub={`submitted ${numberLabel(cron.submitted)} / replayed ${numberLabel(cron.replayed)}`} />
          <SchedulerMetric label="Cron errors" value={numberLabel(cron.errorCount)} sub={reasonSummary(cron.reasonCodes)} tone={cron.errorCount ? "red" : "slate"} />
          <SchedulerMetric label="Backfill submitted" value={numberLabel(backfills.submitted)} sub={`pending ${numberLabel(backfills.pending)} / replayed ${numberLabel(backfills.replayed)}`} />
          <SchedulerMetric label="Backfill errors" value={numberLabel(backfills.errorCount)} sub={reasonSummary(backfills.reasonCodes)} tone={backfills.errorCount ? "red" : "slate"} />
          <div className="min-w-0 text-[11px] text-slate-500 sm:col-span-2 xl:col-span-4">
            evaluated {formatDate(latest.evaluatedAt)} / evidence {shortIdentity(latest.evidenceId, "—")}
          </div>
        </div>
      ) : (
        <div className="text-xs text-slate-400">暂无 scheduler tick evidence</div>
      )}
      <Dialog open={open} onOpenChange={closeDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">确认运行 scheduler</DialogTitle>
            <DialogDescription className="text-xs">
              本次操作会立即执行一次当前 scheduler tick，只返回聚合证据，不执行历史补跑。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              输入 <span className="font-mono text-slate-800">{SCHEDULER_RUN_ONCE_CONFIRMATION}</span> 确认操作。
            </div>
            <Input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              className="h-8 font-mono text-xs"
              placeholder={SCHEDULER_RUN_ONCE_CONFIRMATION}
            />
          </div>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" className="h-8 px-3 text-xs">
                取消
              </Button>
            </DialogClose>
            <Button
              type="button"
              className="h-8 bg-slate-900 px-3 text-xs text-white hover:bg-slate-800"
              disabled={confirmation.trim() !== SCHEDULER_RUN_ONCE_CONFIRMATION || runningScheduler}
              onClick={confirmRunOnce}
            >
              执行 tick
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SchedulerMetric({
  label,
  sub,
  tone = "slate",
  value,
}: {
  label: string;
  sub: string;
  tone?: "slate" | "red";
  value: string;
}) {
  const toneClass = tone === "red" ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-slate-50 text-slate-800";
  return (
    <div className={cn("min-w-0 rounded border px-2.5 py-2", toneClass)}>
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
      <div className="mt-1 truncate text-[11px] text-slate-500">{sub || "no reason codes"}</div>
    </div>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function shortIdentity(value: string | undefined, fallback: string) {
  if (!value) return fallback;
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

function numberLabel(value: unknown) {
  return String(typeof value === "number" && Number.isFinite(value) ? value : 0);
}

function reasonSummary(value: Record<string, number> | undefined) {
  const entries = Object.entries(value || {});
  if (entries.length === 0) return "";
  return entries.slice(0, 2).map(([key, count]) => `${key} ${count}`).join(" / ");
}
