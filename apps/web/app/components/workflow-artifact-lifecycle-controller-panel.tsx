"use client";

import { useState } from "react";
import { Clock3, Eye, Loader2, PlayCircle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { WorkflowArtifactLifecycleControllerTick } from "./workflow-artifact-lifecycle-model";

const CONTROLLER_RUN_ONCE_CONFIRMATION = "run-artifact-lifecycle-controller-once";

export function WorkflowArtifactLifecycleControllerPanel({
  busyTickId,
  error,
  notice,
  onPreviewPolicy,
  onRunControllerOnce,
  runningController,
  ticks,
}: {
  busyTickId: string;
  error: string;
  notice: string;
  onPreviewPolicy: (tick: WorkflowArtifactLifecycleControllerTick) => void;
  onRunControllerOnce: () => void;
  runningController: boolean;
  ticks: WorkflowArtifactLifecycleControllerTick[];
}) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");

  function closeDialog(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) setConfirmation("");
  }

  function confirmRunOnce() {
    if (confirmation.trim() !== CONTROLLER_RUN_ONCE_CONFIRMATION || runningController) return;
    onRunControllerOnce();
    closeDialog(false);
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <Clock3 strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-900">Controller ticks</h2>
          <span className="text-xs text-slate-400">{ticks.length} 条</span>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs text-slate-600"
          disabled={runningController}
          onClick={() => setOpen(true)}
        >
          {runningController ? (
            <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          )}
          运行一次 controller
        </Button>
      </div>
      {notice ? (
        <div className="border-b border-emerald-100 bg-emerald-50 px-5 py-2 text-xs text-emerald-700">
          {notice}
        </div>
      ) : null}
      {error ? (
        <Alert variant="destructive" className="m-5">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <ControllerTickList
        busyTickId={busyTickId}
        ticks={ticks}
        onPreviewPolicy={onPreviewPolicy}
      />
      <Dialog open={open} onOpenChange={closeDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">确认运行 controller</DialogTitle>
            <DialogDescription className="text-xs">
              本次操作只执行 preview-only artifact lifecycle controller tick，生成聚合证据和 GC 预览，不会删除产物 payload。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              输入 <span className="font-mono text-slate-800">{CONTROLLER_RUN_ONCE_CONFIRMATION}</span> 确认操作。
            </div>
            <Input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              className="h-8 font-mono text-xs"
              placeholder={CONTROLLER_RUN_ONCE_CONFIRMATION}
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
              disabled={confirmation.trim() !== CONTROLLER_RUN_ONCE_CONFIRMATION || runningController}
              onClick={confirmRunOnce}
            >
              执行 tick
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function ControllerTickList({
  busyTickId,
  onPreviewPolicy,
  ticks,
}: {
  busyTickId: string;
  onPreviewPolicy: (tick: WorkflowArtifactLifecycleControllerTick) => void;
  ticks: WorkflowArtifactLifecycleControllerTick[];
}) {
  if (ticks.length === 0) {
    return <div className="px-5 py-10 text-center text-sm text-slate-400">暂无 controller tick</div>;
  }
  return (
    <div className="divide-y divide-slate-100">
      {ticks.map((tick) => {
        const tickId = tick.tickId || tick.evidenceId || "";
        const previewReady = controllerTickCanPreviewPolicy(tick);
        const busy = Boolean(tickId && busyTickId === tickId);
        return (
          <article key={tickId} className="px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-700">{tick.tickId || "—"}</span>
                  <DecisionBadge decision={tick.policyDecision?.decision} />
                  <span className="text-xs text-slate-400">{formatDateTime(tick.evaluatedAt || tick.occurredAt)}</span>
                </div>
                <p className="mt-1 text-sm text-slate-600">{tick.policyDecision?.message || tick.policyDecision?.reasonCode || "—"}</p>
              </div>
              <div className="grid min-w-[280px] grid-cols-3 gap-2 text-right">
                <Metric label="候选" value={formatCount(tick.gcPreview?.candidateCount)} compact />
                <Metric label="候选字节" value={formatBytes(tick.gcPreview?.deleteBytes)} compact />
                <Metric label="保护" value={formatCount(tick.gcPreview?.protectedCount)} compact />
              </div>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-4">
              <TickField label="策略" value={`${tick.policy?.retentionDays ?? "—"} 天 / ${formatBytes(tick.policy?.maxDeleteBytesPerTick)}`} />
              <TickField label="用量" value={`${formatBytes(tick.usage?.activeBytes)} / ${formatCount(tick.usage?.activeStorageObjectCount)} 对象`} />
              <TickField label="批安全" value={batchSafetyText(tick)} />
              <TickField label="计划指纹" value={shortFingerprint(tick.gcPreview?.planFingerprint)} />
            </div>
            <div className="mt-3 flex justify-end">
              <Button
                type="button"
                variant="outline"
                className="h-8 bg-white px-2.5 text-xs text-slate-600"
                disabled={!previewReady || busy}
                onClick={() => onPreviewPolicy(tick)}
              >
                {busy ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Eye strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
                按策略预览
              </Button>
            </div>
            {tick.retentionHolds?.reasons?.length ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {tick.retentionHolds.reasons.slice(0, 6).map((reason) => (
                  <span key={reason.reason} className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-600">
                    {reason.reason || "hold"} · {formatCount(reason.groupCount)} 组 · {formatBytes(reason.bytes)}
                  </span>
                ))}
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function controllerTickCanPreviewPolicy(tick: WorkflowArtifactLifecycleControllerTick) {
  const preview = tick.gcPreview;
  return (
    tick.policyDecision?.decision === "preview_ready" &&
    Boolean(preview?.planId.trim()) &&
    Boolean(preview?.planFingerprint.trim()) &&
    (preview?.candidateCount || 0) > 0 &&
    (preview?.deleteBytes || 0) > 0
  );
}

function Metric({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("rounded-lg border border-slate-200 bg-white px-3 py-2", compact ? "px-2 py-1.5" : "")}>
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className={cn("mt-1 font-semibold text-slate-900", compact ? "text-xs" : "text-sm")}>{value}</div>
    </div>
  );
}

function DecisionBadge({ decision }: { decision?: string }) {
  const normalized = (decision || "").toLowerCase();
  const warn = normalized.includes("ready") || normalized.includes("candidate");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]",
        warn ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-50 text-slate-600"
      )}
    >
      {decision || "no decision"}
    </span>
  );
}

function TickField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 text-xs font-medium text-slate-700">{value}</div>
    </div>
  );
}

function batchSafetyText(tick: WorkflowArtifactLifecycleControllerTick) {
  const safety = tick.batchSafety;
  if (!safety) return "—";
  const limited = safety.maxDeleteBytesApplied ? `限制 ${formatCount(safety.limitedGroupCount)} 组` : "未触发限制";
  return `${formatBytes(safety.candidateBytes)} / ${limited}`;
}

function shortFingerprint(value?: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "—";
  return normalized.length > 22 ? `${normalized.slice(0, 18)}...${normalized.slice(-6)}` : normalized;
}

function formatCount(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatBytes(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = Math.max(0, value);
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  const digits = current >= 10 || unitIndex === 0 ? 0 : 1;
  return `${current.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}
