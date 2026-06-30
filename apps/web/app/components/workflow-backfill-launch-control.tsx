"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import { CalendarClock, CheckCircle2, Loader2, PlayCircle, Search } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import {
  launchWorkflowTriggerBackfill,
  previewWorkflowTriggerBackfill,
} from "./workflow-backfill-api";
import type {
  WorkflowBackfillLaunchDetail,
  WorkflowBackfillPreview,
  WorkflowBackfillPreviewRequest,
} from "./workflow-backfill-model";
import type { WorkflowTrigger } from "./workflow-trigger-model";
import { workflowErrorMessage } from "./workflows-page-model";

type BackfillFormState = {
  concurrencyLimit: string;
  maxPartitions: string;
  paramsJson: string;
  partitionUnit: "hour" | "day";
  rangeEnd: string;
  rangeStart: string;
  reprocessBehavior: "none" | "failed" | "completed";
  runOrder: "forward" | "backward";
  timezone: string;
  triggerId: string;
};

export function WorkflowBackfillLaunchControl({
  onLaunched,
  triggers,
}: {
  onLaunched: (launch: WorkflowBackfillLaunchDetail) => void;
  triggers: WorkflowTrigger[];
}) {
  const backfillTriggers = useMemo(
    () => triggers.filter((trigger) => trigger.sourceType === "backfill"),
    [triggers]
  );
  const [form, setForm] = useState<BackfillFormState>(() => defaultBackfillForm(backfillTriggers[0]?.triggerId || ""));
  const [preview, setPreview] = useState<WorkflowBackfillPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");

  const selectedTrigger = backfillTriggers.find((trigger) => trigger.triggerId === form.triggerId) || null;
  const canPreview = Boolean(selectedTrigger?.triggerId) && !previewing && !launching;
  const canLaunch = Boolean(preview?.launchSupported && preview.previewId && selectedTrigger?.triggerId) && !launching;
  const expectedConfirmation = preview?.previewId || "";

  useEffect(() => {
    if (!form.triggerId && backfillTriggers[0]?.triggerId) {
      setForm((current) => ({ ...current, triggerId: backfillTriggers[0].triggerId }));
    }
  }, [backfillTriggers, form.triggerId]);

  function updateForm<K extends keyof BackfillFormState>(key: K, value: BackfillFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setPreview(null);
    setNotice("");
    setError("");
  }

  async function handlePreview() {
    if (!selectedTrigger?.triggerId || previewing || launching) return;
    setPreviewing(true);
    setPreview(null);
    setNotice("");
    setError("");
    try {
      const payload = buildBackfillPreviewRequest(form);
      const result = await previewWorkflowTriggerBackfill(selectedTrigger.triggerId, payload);
      setPreview(result);
      setNotice(`Preview ${result.previewId}，预计 ${numberLabel(result.estimatedRunCount)} 个分区。`);
    } catch (err) {
      setError(workflowErrorMessage(err, "生成回填预览失败"));
    } finally {
      setPreviewing(false);
    }
  }

  async function handleLaunch() {
    if (!selectedTrigger?.triggerId || !preview?.previewId || confirmation !== expectedConfirmation) return;
    setLaunching(true);
    setError("");
    setNotice("");
    try {
      const payload = buildBackfillPreviewRequest(form);
      const launch = await launchWorkflowTriggerBackfill(selectedTrigger.triggerId, {
        ...payload,
        actor: "workflow-ui",
        confirmation: "launch-backfill",
        previewId: preview.previewId,
      });
      setConfirmOpen(false);
      setConfirmation("");
      setNotice(`已启动回填批次 ${launch.launchId}`);
      onLaunched(launch);
    } catch (err) {
      setError(workflowErrorMessage(err, "启动回填失败"));
    } finally {
      setLaunching(false);
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white" data-testid="workflow-backfill-launch-control">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <CalendarClock strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            Backfill launch
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            {selectedTrigger ? selectedTrigger.name || selectedTrigger.triggerId : "no backfill trigger"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            className="h-8 bg-white px-2.5 text-xs"
            disabled={!canPreview}
            onClick={() => void handlePreview()}
            data-testid="workflow-backfill-preview"
          >
            {previewing ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Search strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
            Preview
          </Button>
          <Button
            type="button"
            className="h-8 bg-blue-600 px-2.5 text-xs text-white hover:bg-blue-700"
            disabled={!canLaunch}
            onClick={() => setConfirmOpen(true)}
            data-testid="workflow-backfill-launch"
          >
            {launching ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <PlayCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
            Launch
          </Button>
        </div>
      </div>

      <div className="grid gap-4 px-4 py-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,380px)]">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <Field label="Trigger">
            <Select value={form.triggerId || undefined} onValueChange={(value) => updateForm("triggerId", value)}>
              <SelectTrigger className="h-9 bg-white text-xs">
                <SelectValue placeholder="选择 backfill trigger" />
              </SelectTrigger>
              <SelectContent>
                {backfillTriggers.map((trigger) => (
                  <SelectItem key={trigger.triggerId} value={trigger.triggerId}>
                    {trigger.name || trigger.triggerId}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Range start">
            <Input
              className="h-9 text-xs"
              value={form.rangeStart}
              onChange={(event) => updateForm("rangeStart", event.target.value)}
              placeholder="2026-06-01"
            />
          </Field>
          <Field label="Range end">
            <Input
              className="h-9 text-xs"
              value={form.rangeEnd}
              onChange={(event) => updateForm("rangeEnd", event.target.value)}
              placeholder="2026-06-08"
            />
          </Field>
          <Field label="Unit">
            <Select value={form.partitionUnit} onValueChange={(value) => updateForm("partitionUnit", value as BackfillFormState["partitionUnit"])}>
              <SelectTrigger className="h-9 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="day">day</SelectItem>
                <SelectItem value="hour">hour</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Timezone">
            <Input
              className="h-9 text-xs"
              value={form.timezone}
              onChange={(event) => updateForm("timezone", event.target.value)}
              placeholder="UTC"
            />
          </Field>
          <Field label="Max partitions">
            <Input
              className="h-9 text-xs"
              inputMode="numeric"
              value={form.maxPartitions}
              onChange={(event) => updateForm("maxPartitions", event.target.value)}
            />
          </Field>
          <Field label="Max active runs">
            <Input
              className="h-9 text-xs"
              inputMode="numeric"
              value={form.concurrencyLimit}
              onChange={(event) => updateForm("concurrencyLimit", event.target.value)}
            />
          </Field>
          <Field label="Run order">
            <Select value={form.runOrder} onValueChange={(value) => updateForm("runOrder", value as BackfillFormState["runOrder"])}>
              <SelectTrigger className="h-9 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="forward">forward</SelectItem>
                <SelectItem value="backward">backward</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Reprocess">
            <Select
              value={form.reprocessBehavior}
              onValueChange={(value) => updateForm("reprocessBehavior", value as BackfillFormState["reprocessBehavior"])}
            >
              <SelectTrigger className="h-9 bg-white text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">none</SelectItem>
                <SelectItem value="failed">failed</SelectItem>
                <SelectItem value="completed">completed</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Params JSON" className="md:col-span-2 xl:col-span-3">
            <Input
              className="h-9 font-mono text-xs"
              value={form.paramsJson}
              onChange={(event) => updateForm("paramsJson", event.target.value)}
              placeholder='{"sampleBatch":"batch_42"}'
            />
          </Field>
        </div>

        <PreviewSummary preview={preview} />
      </div>

      {error ? (
        <div className="px-4 pb-4">
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      {notice ? (
        <div className="px-4 pb-4">
          <Alert>
            <CheckCircle2 strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">确认启动 backfill</DialogTitle>
            <DialogDescription className="text-xs">
              Preview {preview?.previewId || "—"} / creates {numberLabel(preview?.creationRunCount)} / skips {numberLabel(preview?.skippedRunCount)}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <LabelValue label="Trigger" value={selectedTrigger?.triggerId || "—"} />
              <LabelValue label="Range" value={`${preview?.range?.start || "—"} to ${preview?.range?.end || "—"}`} />
              <LabelValue label="Max active runs" value={String(preview?.concurrency?.limit ?? "—")} />
              <LabelValue label="Active-run blocks" value={numberLabel(preview?.blockedActiveRunCount)} />
            </div>
            <Input
              className="h-9 font-mono text-xs"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={preview?.previewId || "preview id"}
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
              className="h-8 bg-blue-600 px-3 text-xs text-white hover:bg-blue-700"
              disabled={confirmation !== expectedConfirmation || launching}
              onClick={() => void handleLaunch()}
            >
              {launching ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
              Launch backfill
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function PreviewSummary({ preview }: { preview: WorkflowBackfillPreview | null }) {
  if (!preview) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-400">
        Preview will show partition count, launch support, concurrency batches, and the first returned partitions.
      </div>
    );
  }
  const tone = preview.launchSupported ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <div className="space-y-3">
      <div className={`rounded-lg border px-3 py-3 text-xs ${tone}`} data-testid="workflow-backfill-preview-summary">
        <div className="font-mono text-[11px]">{preview.previewId}</div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <LabelValue label="Launch" value={preview.launchSupported ? "supported" : preview.reason || "blocked"} />
          <LabelValue label="Partitions" value={`${numberLabel(preview.returnedRunCount)} / ${numberLabel(preview.estimatedRunCount)}`} />
          <LabelValue label="Creates" value={numberLabel(preview.creationRunCount)} />
          <LabelValue label="Skips" value={numberLabel(preview.skippedRunCount)} />
          <LabelValue label="Active blocks" value={numberLabel(preview.blockedActiveRunCount)} />
          <LabelValue label="Max active" value={numberLabel(preview.concurrency?.limit)} />
          <LabelValue label="Batches" value={numberLabel(preview.concurrency?.estimatedBatches)} />
          <LabelValue label="Truncated" value={preview.truncated ? "yes" : "no"} />
        </div>
      </div>
      <div className="max-h-52 overflow-y-auto rounded-lg border border-slate-200">
        {(preview.partitions || []).slice(0, 8).map((partition) => (
          <div key={partition.partitionId || partition.partitionKey} className="border-b border-slate-100 px-3 py-2 text-xs last:border-b-0">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-slate-800">{partition.partitionKey || `#${partition.index}`}</span>
              <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500">
                {partition.action || "create"}
              </span>
            </div>
            <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{partition.window?.start || "—"} to {partition.window?.end || "—"}</div>
            {partition.reprocessDecision?.reason ? (
              <div className="mt-1 text-[11px] text-slate-500">{partition.reprocessDecision.reason}</div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({
  children,
  className = "",
  label,
}: {
  children: ReactNode;
  className?: string;
  label: string;
}) {
  return (
    <label className={`grid gap-1.5 text-xs font-medium text-slate-600 ${className}`}>
      {label}
      {children}
    </label>
  );
}

function LabelValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="text-[10px] uppercase text-slate-400">{label}</span>
      <div className="truncate font-mono text-[11px] text-slate-700">{value || "—"}</div>
    </div>
  );
}

function buildBackfillPreviewRequest(form: BackfillFormState): WorkflowBackfillPreviewRequest {
  return {
    concurrencyLimit: boundedInteger(form.concurrencyLimit, 1, 100),
    maxPartitions: boundedInteger(form.maxPartitions, 1, 1000),
    params: parseParamsJson(form.paramsJson),
    partitionUnit: form.partitionUnit,
    rangeEnd: form.rangeEnd.trim(),
    rangeStart: form.rangeStart.trim(),
    reprocessBehavior: form.reprocessBehavior,
    runOrder: form.runOrder,
    timezone: form.timezone.trim() || "UTC",
  };
}

function boundedInteger(value: string, min: number, max: number) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return min;
  return Math.min(max, Math.max(min, parsed));
}

function parseParamsJson(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("WORKFLOW_BACKFILL_PARAMS_MUST_BE_OBJECT");
  }
  return parsed as Record<string, unknown>;
}

function defaultBackfillForm(triggerId: string): BackfillFormState {
  const today = new Date();
  const end = utcDateInput(today);
  const start = utcDateInput(new Date(today.getTime() - 24 * 60 * 60 * 1000));
  return {
    concurrencyLimit: "1",
    maxPartitions: "30",
    paramsJson: "",
    partitionUnit: "day",
    rangeEnd: end,
    rangeStart: start,
    reprocessBehavior: "none",
    runOrder: "forward",
    timezone: "UTC",
    triggerId,
  };
}

function utcDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function numberLabel(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "0";
}
