"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Loader2,
  PlayCircle,
  RefreshCw,
  ToggleLeft,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import type {
  WorkflowTrigger,
  WorkflowTriggerDispatch,
  WorkflowTriggerEvent,
  WorkflowTriggerEventPayload,
  WorkflowTriggerInboxEvent,
  WorkflowTriggerReadinessObservation,
  WorkflowRunAdmissionSummary,
} from "./workflow-trigger-model";
import { WorkflowTriggerInboxPanel } from "./workflow-trigger-inbox-panel";

export function WorkflowTriggerObservabilityPanel({
  error,
  events,
  eventsLoading,
  inboxEvents,
  inboxLoading,
  loading,
  notice,
  onRefresh,
  onReplayInboxEvent,
  onSelectTrigger,
  onSubmitManualTrigger,
  readinessObservation,
  replayingInboxEventId,
  selectedTrigger,
  selectedTriggerId,
  submittingManualTriggerId,
  triggers,
}: {
  error: string;
  events: WorkflowTriggerEvent[];
  eventsLoading: boolean;
  inboxEvents: WorkflowTriggerInboxEvent[];
  inboxLoading: boolean;
  loading: boolean;
  notice: string;
  onRefresh: () => void;
  onReplayInboxEvent: (inboxEventId: string) => void;
  onSelectTrigger: (triggerId: string) => void;
  onSubmitManualTrigger: (triggerId: string) => void;
  readinessObservation: WorkflowTriggerReadinessObservation | null;
  replayingInboxEventId: string;
  selectedTrigger: WorkflowTrigger | null;
  selectedTriggerId: string;
  submittingManualTriggerId: string;
  triggers: WorkflowTrigger[];
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Activity strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            触发器事件
          </div>
          <div className="mt-1 text-xs text-slate-500">Trigger definitions / immutable events / dispatch runs</div>
        </div>
        <Button type="button" variant="outline" className="h-8 bg-white px-2.5 text-xs" disabled={loading} onClick={onRefresh}>
          <RefreshCw strokeWidth={1.5} className={loading ? "mr-1.5 h-3.5 w-3.5 animate-spin" : "mr-1.5 h-3.5 w-3.5"} />
          刷新触发器
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

      {notice ? (
        <div className="px-4 pt-4">
          <Alert>
            <CheckCircle2 strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      {loading && triggers.length === 0 ? (
        <div className="flex h-28 items-center justify-center text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取触发器
        </div>
      ) : triggers.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-slate-400">暂无触发器</div>
      ) : (
        <div className="grid gap-0 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
          <TriggerList
            selectedTriggerId={selectedTriggerId}
            triggers={triggers}
            onSelectTrigger={onSelectTrigger}
          />
          <div className="min-w-0 p-4">
            {selectedTrigger ? (
              <TriggerDetail
                trigger={selectedTrigger}
                events={events}
                eventsLoading={eventsLoading}
                inboxEvents={inboxEvents}
                inboxLoading={inboxLoading}
                onReplayInboxEvent={onReplayInboxEvent}
                onSubmitManualTrigger={onSubmitManualTrigger}
                readinessObservation={readinessObservation}
                replayingInboxEventId={replayingInboxEventId}
                submittingManualTriggerId={submittingManualTriggerId}
              />
            ) : (
              <div className="py-12 text-center text-sm text-slate-400">选择一个触发器</div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function TriggerList({
  onSelectTrigger,
  selectedTriggerId,
  triggers,
}: {
  onSelectTrigger: (triggerId: string) => void;
  selectedTriggerId: string;
  triggers: WorkflowTrigger[];
}) {
  return (
    <div className="border-b border-slate-100 lg:border-b-0 lg:border-r">
      <div className="divide-y divide-slate-100">
        {triggers.map((trigger) => (
          <button
            key={trigger.triggerId}
            type="button"
            className={cn(
              "flex w-full min-w-0 items-start gap-3 px-4 py-3 text-left transition",
              selectedTriggerId === trigger.triggerId ? "bg-slate-50" : "hover:bg-slate-50"
            )}
            onClick={() => onSelectTrigger(trigger.triggerId)}
          >
            {trigger.enabled ? (
              <CheckCircle2 strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            ) : (
              <ToggleLeft strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-medium text-slate-900">{trigger.name || trigger.triggerId}</span>
                <span className={cn("shrink-0 rounded border px-1.5 py-0.5 text-[10px]", sourceStyle(trigger.sourceType))}>
                  {sourceLabel(trigger.sourceType)}
                </span>
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{trigger.triggerId}</div>
              <div className="mt-1 truncate text-xs text-slate-500">{trigger.pipelineId || "pipeline —"}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function TriggerDetail({
  events,
  eventsLoading,
  inboxEvents,
  inboxLoading,
  onReplayInboxEvent,
  onSubmitManualTrigger,
  readinessObservation,
  replayingInboxEventId,
  submittingManualTriggerId,
  trigger,
}: {
  events: WorkflowTriggerEvent[];
  eventsLoading: boolean;
  inboxEvents: WorkflowTriggerInboxEvent[];
  inboxLoading: boolean;
  onReplayInboxEvent: (inboxEventId: string) => void;
  onSubmitManualTrigger: (triggerId: string) => void;
  readinessObservation: WorkflowTriggerReadinessObservation | null;
  replayingInboxEventId: string;
  submittingManualTriggerId: string;
  trigger: WorkflowTrigger;
}) {
  const isWebhook = trigger.sourceType === "webhook";
  const isReadiness = isReadinessSourceType(trigger.sourceType);
  const isManual = trigger.sourceType === "manual";
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <DetailMetric label="来源" value={sourceLabel(trigger.sourceType)} tone={trigger.enabled ? "emerald" : "slate"} />
        <DetailMetric label="定义状态" value={trigger.enabled ? "definition enabled" : "definition disabled"} tone={trigger.enabled ? "emerald" : "amber"} />
        <DetailMetric label="事件" value={String(events.length)} />
        <DetailMetric label="最近更新" value={formatDate(trigger.updatedAt)} />
      </div>

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600 md:grid-cols-2">
        <LabelValue label="Trigger ID" value={trigger.triggerId} />
        <LabelValue label="Server" value={trigger.serverId || "—"} />
        <LabelValue label="Pipeline" value={trigger.pipelineId || "—"} />
        <LabelValue label="RunSpec" value={triggerRunSpecLabel(trigger)} />
        <LabelValue label={triggerSpecLabel(trigger)} value={triggerSpecSummary(trigger)} />
        <LabelValue label="Resource" value={triggerResourceLabel(trigger)} />
      </div>

      {isManual ? (
        <ManualTriggerRunControl
          submitting={submittingManualTriggerId === trigger.triggerId}
          trigger={trigger}
          onSubmitManualTrigger={onSubmitManualTrigger}
        />
      ) : null}

      {isWebhook ? (
        <WorkflowTriggerInboxPanel
          inboxEvents={inboxEvents}
          inboxLoading={inboxLoading}
          onReplayInboxEvent={onReplayInboxEvent}
          replayingInboxEventId={replayingInboxEventId}
        />
      ) : null}

      {isReadiness ? <ReadinessObservationPanel observation={readinessObservation} /> : null}

      {eventsLoading ? (
        <div className="flex h-32 items-center justify-center text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取触发事件
        </div>
      ) : events.length === 0 ? (
        <div className="py-8 text-center text-sm text-slate-400">暂无触发事件</div>
      ) : (
        <EventTable events={events} />
      )}
    </div>
  );
}

function ManualTriggerRunControl({
  onSubmitManualTrigger,
  submitting,
  trigger,
}: {
  onSubmitManualTrigger: (triggerId: string) => void;
  submitting: boolean;
  trigger: WorkflowTrigger;
}) {
  const [open, setOpen] = useState(false);
  const disabled = !trigger.enabled || submitting;
  function confirmRun() {
    onSubmitManualTrigger(trigger.triggerId);
    setOpen(false);
  }
  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium text-blue-900">Manual trigger</div>
          <div className="mt-1 truncate text-xs text-blue-700">
            {trigger.enabled ? "通过统一 trigger event 路径提交一次运行" : "定义已禁用，不能提交运行"}
          </div>
        </div>
        <Button
          type="button"
          className="h-8 bg-blue-600 px-3 text-xs text-white hover:bg-blue-700"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          {submitting ? (
            <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <PlayCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
          )}
          立即运行
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">确认提交 manual trigger</DialogTitle>
            <DialogDescription className="text-xs">
              本次操作会创建一个 immutable trigger event，并通过现有 run admission 路径提交运行。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <LabelValue label="Trigger" value={trigger.triggerId} />
            <LabelValue label="Pipeline" value={trigger.pipelineId || "—"} />
            <LabelValue label="RunSpec" value={triggerRunSpecLabel(trigger)} />
          </div>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" className="h-8 px-3 text-xs">
                取消
              </Button>
            </DialogClose>
            <Button type="button" className="h-8 bg-blue-600 px-3 text-xs text-white hover:bg-blue-700" onClick={confirmRun}>
              提交运行
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReadinessObservationPanel({ observation }: { observation: WorkflowTriggerReadinessObservation | null }) {
  if (!observation) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-3 py-3 text-xs text-slate-500">
        <div className="font-medium text-slate-700">Readiness watcher</div>
        <div className="mt-1">暂无观察记录</div>
      </div>
    );
  }
  const runId = observation.runId || "";
  const resourceIdentity = observation.resourceIdentity || {};
  const resourceType = resourceIdentity.type || observation.resourceType || "";
  const resourceLabel = [
    resourceType,
    resourceIdentity.idHash ? `id ${shortIdentity(resourceIdentity.idHash, "")}` : "",
  ].filter(Boolean).join(" / ") || (resourceIdentity.idPresent ? "id present" : "—");
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-medium text-slate-700">Readiness watcher</div>
        <span className={cn("inline-flex rounded border px-1.5 py-0.5 text-[11px]", observationStateStyle(observation.observedState))}>
          {observationStateLabel(observation.observedState)}
        </span>
      </div>
      <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
        <LabelValue label="Adapter" value={observation.watcherAdapter || "—"} />
        <LabelValue label="Resource" value={resourceLabel} />
        <LabelValue label="Version" value={shortIdentity(observation.observedVersion, "—")} />
        <LabelValue label="Checksum" value={shortIdentity(observation.observedChecksum, "—")} />
        <LabelValue label="Observed" value={formatDate(observation.observedAt)} />
        <LabelValue label="Dispatch" value={dispatchLabel(observation.dispatchState)} />
        <LabelValue label="Trigger event" value={shortIdentity(observation.triggerEventId || "", "—")} />
        {runId ? (
          <div className="min-w-0">
            <span className="text-slate-400">Run</span>
            <Link
              href={`/workflows/results/detail?run=${encodeURIComponent(runId)}`}
              className="ml-2 inline-flex min-w-0 max-w-full items-center gap-1 text-blue-600 hover:text-blue-700"
            >
              <span className="truncate font-mono">{runId}</span>
              <ArrowRight strokeWidth={1.5} className="h-3 w-3 shrink-0" />
            </Link>
          </div>
        ) : (
          <LabelValue label="Run" value="—" />
        )}
        {observation.error ? <LabelValue label="Error" value={observation.error.reasonCode || observation.error.errorType || "—"} /> : null}
      </div>
    </div>
  );
}

function EventTable({ events }: { events: WorkflowTriggerEvent[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <table className="w-full table-fixed text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="w-[18%] px-3 py-2 font-medium">事件</th>
            <th className="w-[15%] px-3 py-2 font-medium">Dispatch</th>
            <th className="w-[20%] px-3 py-2 font-medium">运行</th>
            <th className="w-[22%] px-3 py-2 font-medium">上下文</th>
            <th className="w-[25%] px-3 py-2 font-medium">证据</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {events.map((event) => (
            <EventRow key={event.triggerEventId} event={event} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventRow({ event }: { event: WorkflowTriggerEvent }) {
  const dispatch = event.dispatch || null;
  return (
    <tr>
      <td className="px-3 py-2">
        <div className="truncate font-medium text-slate-800">{event.eventType || "event"}</div>
        <div className="truncate font-mono text-[10px] text-slate-400">{event.triggerEventId}</div>
        <div className="mt-1 truncate text-[10px] text-slate-400">{formatDate(event.createdAt)}</div>
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]", dispatchStyle(dispatch?.state))}>
          {dispatchLabel(dispatch?.state)}
        </span>
        {dispatch?.requestId ? <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{dispatch.requestId}</div> : null}
      </td>
      <td className="px-3 py-2">
        <RunSummary dispatch={dispatch} />
      </td>
      <td className="px-3 py-2 text-slate-600">
        <EventContext event={event} />
      </td>
      <td className="px-3 py-2">
        <div className="truncate font-mono text-[10px] text-slate-500">{shortIdentity(event.externalEventId, "no external event id")}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{shortIdentity(event.cursor, "no cursor")}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{shortHash(event.payloadHash)}</div>
        {dispatch?.error ? <div className="mt-1 truncate text-[10px] text-red-600">{errorLabel(dispatch.error)}</div> : null}
      </td>
    </tr>
  );
}

function RunSummary({ dispatch }: { dispatch: WorkflowTriggerDispatch | null }) {
  const run = dispatch?.run || null;
  const runId = run?.runId || "";
  if (!runId) return <span className="text-slate-400">—</span>;
  return (
    <div className="min-w-0">
      <Link
        href={`/workflows/results/detail?run=${encodeURIComponent(runId)}`}
        className="inline-flex min-w-0 max-w-full items-center gap-1 text-blue-600 hover:text-blue-700"
      >
        <span className="truncate font-mono">{runId}</span>
        <ArrowRight strokeWidth={1.5} className="h-3 w-3 shrink-0" />
      </Link>
      {run ? (
        <div className="mt-1 space-y-1">
          <div className="flex min-w-0 flex-wrap gap-1">
            {run.status ? (
              <span className={cn("inline-flex rounded border px-1.5 py-0.5 text-[10px]", runStatusStyle(run.status))}>
                {run.status}
              </span>
            ) : null}
            {run.stage ? (
              <span className="inline-flex min-w-0 max-w-full rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-600">
                <span className="truncate">{run.stage}</span>
              </span>
            ) : null}
          </div>
          <AdmissionSummary admission={run.admission} />
          {run.lastUpdatedAt ? <div className="truncate text-[10px] text-slate-400">{formatDate(run.lastUpdatedAt)}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function AdmissionSummary({ admission }: { admission?: WorkflowRunAdmissionSummary | null }) {
  if (!admission) return null;
  const wait = admission.waitReason || null;
  return (
    <div className="flex min-w-0 flex-wrap gap-1">
      {admission.jobState ? (
        <span className="inline-flex max-w-full rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
          <span className="truncate">job {admission.jobState}</span>
        </span>
      ) : null}
      {admission.queueName ? (
        <span className="inline-flex max-w-full rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
          <span className="truncate">queue {admission.queueName}</span>
        </span>
      ) : null}
      {admission.maxAttempts ? (
        <span className="inline-flex max-w-full rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
          <span className="truncate">attempt {admission.attemptCount ?? 0}/{admission.maxAttempts}</span>
        </span>
      ) : null}
      {admission.availableAt ? (
        <span className="inline-flex max-w-full rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-600">
          <span className="truncate">available {formatDate(admission.availableAt)}</span>
        </span>
      ) : null}
      {wait?.code ? (
        <span className="inline-flex max-w-full rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
          <span className="truncate">{admissionWaitLabel(wait)}</span>
        </span>
      ) : null}
    </div>
  );
}

function admissionWaitLabel(wait: NonNullable<WorkflowRunAdmissionSummary["waitReason"]>) {
  if (wait.code === "ADMISSION_RESOURCES_UNAVAILABLE") {
    return `等待资源 ${wait.resource || "unknown"} ${wait.requested ?? 0}/${wait.available ?? 0}`;
  }
  if (wait.code === "ADMISSION_SLOT_UNAVAILABLE") {
    return `等待槽位 max ${wait.maxActiveSlots ?? 0}`;
  }
  if (wait.code === "ADMISSION_SLOT_BUSY") {
    return "等待 worker 槽位";
  }
  return "等待 admission";
}

function EventContext({ event }: { event: WorkflowTriggerEvent }) {
  const payload = event.payload || {};
  const context = recordValue(payload.eventContext);
  const resource = recordValue(payload.resource);
  const schedule = recordValue(payload.schedule);
  const contextItems = compactEntries(context, ["source", "eventId", "correlationId", "resourceType"]);
  const resourceItems = compactEntries(resource, ["type", "version", "checksum"]);
  const scheduleItems = compactEntries(schedule, ["cron", "timezone"]);
  const scheduledAt = stringValue(payload.scheduledAt);
  const scheduleVersion = stringValue(payload.scheduleVersion);
  const backfill = recordValue(payload.backfill);
  const backfillItems = compactEntries(backfill, ["partitionKey", "partitionId"]);
  if (
    contextItems.length === 0 &&
    resourceItems.length === 0 &&
    scheduleItems.length === 0 &&
    backfillItems.length === 0 &&
    !scheduledAt &&
    !scheduleVersion &&
    !payload.state &&
    !payload.observedAt
  ) {
    return <span className="text-slate-400">payload hash only</span>;
  }
  return (
    <div className="space-y-1">
      {scheduledAt ? <div className="truncate"><span className="text-slate-400">scheduled</span> {formatDate(scheduledAt)}</div> : null}
      {scheduleItems.map(([key, value]) => (
        <div key={`schedule-${key}`} className="truncate"><span className="text-slate-400">schedule.{key}</span> {value}</div>
      ))}
      {scheduleVersion ? <div className="truncate"><span className="text-slate-400">schedule.version</span> {shortIdentity(scheduleVersion, "—")}</div> : null}
      {contextItems.map(([key, value]) => (
        <div key={`context-${key}`} className="truncate"><span className="text-slate-400">{key}</span> {value}</div>
      ))}
      {resourceItems.map(([key, value]) => (
        <div key={`resource-${key}`} className="truncate"><span className="text-slate-400">resource.{key}</span> {value}</div>
      ))}
      {backfillItems.map(([key, value]) => (
        <div key={`backfill-${key}`} className="truncate"><span className="text-slate-400">backfill.{key}</span> {value}</div>
      ))}
      {payload.state ? <div className="truncate"><span className="text-slate-400">state</span> {payload.state}</div> : null}
      {payload.observedAt ? <div className="truncate"><span className="text-slate-400">observed</span> {formatDate(payload.observedAt)}</div> : null}
    </div>
  );
}

function DetailMetric({ label, tone = "slate", value }: { label: string; value: string; tone?: "slate" | "emerald" | "amber" }) {
  const toneClass = {
    slate: "border-slate-200 bg-white text-slate-900",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
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

function sourceLabel(sourceType: string | undefined) {
  if (sourceType === "database_ready") return "database-ready";
  return sourceType || "unknown";
}

function sourceStyle(sourceType: string | undefined) {
  const source = String(sourceType || "").toLowerCase();
  if (source === "cron") return "border-blue-200 bg-blue-50 text-blue-700";
  if (source === "webhook") return "border-violet-200 bg-violet-50 text-violet-700";
  if (source === "dataset" || source === "file" || source === "database_ready") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (source === "backfill") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function isReadinessSourceType(sourceType: string | undefined) {
  return sourceType === "dataset" || sourceType === "file" || sourceType === "database_ready";
}

function dispatchStyle(state: string | undefined) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "submitted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "failed" || normalized === "error") return "border-red-200 bg-red-50 text-red-700";
  if (normalized === "pending") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function dispatchLabel(state: string | undefined) {
  if (state === "submitted") return "已提交";
  if (state === "pending") return "待提交";
  if (state === "failed") return "失败";
  return state || "unknown";
}

function observationStateStyle(state: string | undefined) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "ready") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "missing") return "border-amber-200 bg-amber-50 text-amber-700";
  if (normalized === "error") return "border-red-200 bg-red-50 text-red-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function observationStateLabel(state: string | undefined) {
  if (state === "ready") return "ready";
  if (state === "missing") return "missing";
  if (state === "error") return "error";
  return state || "unknown";
}

function runStatusStyle(status: string | undefined) {
  const normalized = String(status || "").toLowerCase();
  if (["completed", "success", "succeeded"].includes(normalized)) return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (["failed", "error", "crashed"].includes(normalized)) return "border-red-200 bg-red-50 text-red-700";
  if (["running", "started", "processing"].includes(normalized)) return "border-violet-200 bg-violet-50 text-violet-700";
  if (["queued", "pending", "scheduled"].includes(normalized)) return "border-blue-200 bg-blue-50 text-blue-700";
  if (["cancelled", "canceled", "canceling", "cancelling"].includes(normalized)) return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function triggerSpecLabel(trigger: WorkflowTrigger) {
  const source = String(trigger.sourceType || "").toLowerCase();
  if (source === "cron") return "Cron";
  if (source === "webhook") return "Inbox source";
  if (source === "backfill") return "Partition policy";
  if (source === "dataset" || source === "file" || source === "database_ready") return "Readiness";
  return "Trigger spec";
}

function triggerSpecSummary(trigger: WorkflowTrigger) {
  const source = String(trigger.sourceType || "").toLowerCase();
  if (source === "cron") return triggerScheduleLabel(trigger);
  if (source === "webhook") return triggerInboxLabel(trigger);
  if (source === "backfill") return triggerPartitionPolicyLabel(trigger);
  if (isReadinessSourceType(source)) return triggerResourceLabel(trigger);
  return "—";
}

function triggerScheduleLabel(trigger: WorkflowTrigger) {
  const spec = recordValue(trigger.triggerSpec);
  const cron = stringValue(spec.cron);
  const timezone = stringValue(spec.timezone);
  if (cron && timezone) return `${cron} / ${timezone}`;
  if (cron) return cron;
  const mode = stringValue(spec.mode);
  return mode || "—";
}

function triggerInboxLabel(trigger: WorkflowTrigger) {
  const spec = recordValue(trigger.triggerSpec);
  return stringValue(spec.provider) || stringValue(spec.source) || "webhook inbox";
}

function triggerPartitionPolicyLabel(trigger: WorkflowTrigger) {
  const spec = recordValue(trigger.triggerSpec);
  return stringValue(spec.partitionUnit) || "partitioned backfill";
}

function triggerResourceLabel(trigger: WorkflowTrigger) {
  const resource = recordValue(recordValue(trigger.triggerSpec).resource);
  const type = stringValue(resource.type);
  if (isReadinessSourceType(trigger.sourceType)) {
    return type ? `${type} / id redacted` : "id redacted";
  }
  const id = stringValue(resource.id);
  return [type, id].filter(Boolean).join(" / ") || "—";
}

function triggerRunSpecLabel(trigger: WorkflowTrigger) {
  const runSpec = recordValue(trigger.runSpec);
  const pipelineVersion = stringValue(runSpec.pipelineVersion);
  const workflowRevisionId = stringValue(runSpec.workflowRevisionId);
  const params = recordValue(runSpec.params);
  const paramsLabel = Object.keys(params).length > 0 ? `${Object.keys(params).length} params` : "";
  return [pipelineVersion, workflowRevisionId, paramsLabel].filter(Boolean).join(" / ") || "template";
}

function compactEntries(record: Record<string, unknown>, keys: string[]): [string, string][] {
  return keys
    .map((key) => [key, stringValue(record[key])] as [string, string])
    .filter(([, value]) => Boolean(value));
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function shortHash(value?: string) {
  if (!value) return "no payload hash";
  return value.length > 16 ? `${value.slice(0, 16)}…` : value;
}

function shortIdentity(value: string | undefined, fallback: string) {
  if (!value) return fallback;
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

function errorLabel(value: unknown) {
  const record = recordValue(value);
  return stringValue(record.errorType) || "dispatch error";
}
