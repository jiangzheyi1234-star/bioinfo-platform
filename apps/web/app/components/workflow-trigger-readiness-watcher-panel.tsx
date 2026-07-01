"use client";

import { useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { WorkflowTriggerReadinessWatcherRunOnceResult } from "./workflow-trigger-model";

const READINESS_WATCHER_RUN_ONCE_CONFIRMATION = "run-readiness-watcher-once";

export function WorkflowTriggerReadinessWatcherPanel({
  latest,
  onRunReadinessWatcherOnce,
  runningReadinessWatcher,
}: {
  latest: WorkflowTriggerReadinessWatcherRunOnceResult | null;
  onRunReadinessWatcherOnce: () => void;
  runningReadinessWatcher: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const readiness = latest?.readiness || {};

  function closeDialog(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) setConfirmation("");
  }

  function confirmRunOnce() {
    if (confirmation.trim() !== READINESS_WATCHER_RUN_ONCE_CONFIRMATION || runningReadinessWatcher) return;
    onRunReadinessWatcherOnce();
    closeDialog(false);
  }

  return (
    <div className="border-b border-slate-100 px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-700">Readiness watcher</div>
          <div className="mt-1 text-[11px] text-slate-400">
            {latest ? `latest ${shortIdentity(latest.runOnceId, "run-once")}` : "no run-once evidence"}
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs"
          disabled={runningReadinessWatcher}
          onClick={() => setOpen(true)}
        >
          {runningReadinessWatcher ? (
            <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          )}
          运行一次 readiness watcher
        </Button>
      </div>
      {latest ? (
        <div data-testid="workflow-trigger-readiness-watcher-summary" className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
          <WatcherMetric label="Checked" value={numberLabel(readiness.checked)} sub={`ready ${numberLabel(readiness.ready)} / missing ${numberLabel(readiness.missing)}`} />
          <WatcherMetric label="Submitted" value={numberLabel(readiness.submitted)} sub={`unchanged ${numberLabel(readiness.unchanged)} / skipped ${numberLabel(readiness.skipped)}`} />
          <WatcherMetric label="Observations" value={numberLabel(readiness.observationCount)} sub={badgeSummary(readiness.stateCounts)} />
          <WatcherMetric label="Errors" value={numberLabel(readiness.errorCount)} sub={badgeSummary(readiness.reasonCodes)} tone={readiness.errorCount ? "red" : "slate"} />
          <div className="min-w-0 text-[11px] text-slate-500 sm:col-span-2 xl:col-span-4">
            evaluated {formatDate(latest.evaluatedAt)} / limit {numberLabel(latest.limit)}
          </div>
          <BadgeSummary values={readiness.sourceTypeCounts} title="source" />
          <BadgeSummary values={readiness.resourceTypeCounts} title="resource" />
          <BadgeSummary values={readiness.watcherAdapterCounts} title="adapter" />
          <BadgeSummary values={readiness.dispatchStateCounts} title="dispatch" />
        </div>
      ) : (
        <div className="text-xs text-slate-400">暂无 readiness watcher run-once evidence</div>
      )}
      <Dialog open={open} onOpenChange={closeDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">确认运行 readiness watcher</DialogTitle>
            <DialogDescription className="text-xs">
              本次操作会立即扫描已声明的 readiness watcher，只返回聚合证据。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              输入 <span className="font-mono text-slate-800">{READINESS_WATCHER_RUN_ONCE_CONFIRMATION}</span> 确认操作。
            </div>
            <Input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              className="h-8 font-mono text-xs"
              placeholder={READINESS_WATCHER_RUN_ONCE_CONFIRMATION}
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
              disabled={confirmation.trim() !== READINESS_WATCHER_RUN_ONCE_CONFIRMATION || runningReadinessWatcher}
              onClick={confirmRunOnce}
            >
              执行 watcher
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function WatcherMetric({
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
      <div className="mt-1 truncate text-[11px] text-slate-500">{sub || "no evidence"}</div>
    </div>
  );
}

function BadgeSummary({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values || {}).filter(([, count]) => Number(count) > 0).slice(0, 4);
  if (entries.length === 0) return null;
  return (
    <div className="min-w-0 rounded border border-slate-100 bg-slate-50 px-2 py-1.5 text-[11px]">
      <div className="mb-1 font-medium text-slate-500">{title}</div>
      <div className="flex flex-wrap gap-1">
        {entries.map(([key, count]) => (
          <span key={key} className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
            {key}:{numberLabel(count)}
          </span>
        ))}
      </div>
    </div>
  );
}

function badgeSummary(value: Record<string, number> | undefined) {
  const entries = Object.entries(value || {});
  if (entries.length === 0) return "";
  return entries.slice(0, 2).map(([key, count]) => `${key} ${count}`).join(" / ");
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function shortIdentity(value: string | undefined, fallback: string) {
  if (!value) return fallback;
  return value.length > 24 ? `${value.slice(0, 12)}...${value.slice(-8)}` : value;
}

function numberLabel(value: unknown) {
  return String(typeof value === "number" && Number.isFinite(value) ? value : 0);
}
