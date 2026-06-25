"use client";

import type { ReactNode } from "react";
import { Clock, GitBranch, Inbox, Layers, ShieldCheck } from "lucide-react";

import type { WorkflowRunTrigger } from "./workflows-page-model";
import type { WorkflowRunTriggerProvenance } from "./workflow-run-trigger-provenance-model";

type WorkflowRunTriggerWithProvenance = WorkflowRunTrigger & {
  provenance?: WorkflowRunTriggerProvenance | null;
};

export function WorkflowRunTriggerSummary({ trigger }: { trigger?: WorkflowRunTriggerWithProvenance | null }) {
  if (!trigger) return null;
  const provenance = trigger.provenance;
  return (
    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-blue-700">
      <Clock strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-blue-500" />
      <span className="shrink-0 font-sans text-slate-500">Trigger</span>
      <span className="truncate">{trigger.triggerId || trigger.source || "trigger"}</span>
      {trigger.triggerEventId ? <span className="truncate text-blue-500">{trigger.triggerEventId}</span> : null}
      {provenance?.available === false ? (
        <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-sans text-[10px] text-amber-700">
          provenance unavailable
        </span>
      ) : null}
    </div>
  );
}

export function WorkflowRunTriggerProvenancePanel({ trigger }: { trigger?: WorkflowRunTriggerWithProvenance | null }) {
  const provenance = trigger?.provenance;
  if (!trigger || !provenance) return null;
  if (provenance.available === false) {
    return (
      <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
          <ShieldCheck strokeWidth={1.5} className="h-4 w-4" />
          <span>触发 provenance</span>
        </div>
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Trigger" value={provenance.triggerId || trigger.triggerId} />
          <Field label="Event" value={provenance.triggerEventId || trigger.triggerEventId} />
          <Field label="Source" value={provenance.source || trigger.source} mono={false} />
          <Field label="Reason" value={provenance.reasonCode || "RUN_TRIGGER_PROVENANCE_UNAVAILABLE"} mono={false} />
        </div>
      </section>
    );
  }

  const event = provenance.event || {};
  const dispatch = provenance.dispatch || {};
  const backfill = provenance.backfillPartition;
  const inbox = provenance.inboxDelivery;

  return (
    <section className="rounded-lg border border-blue-100 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
          <GitBranch strokeWidth={1.5} className="h-4 w-4 text-blue-500" />
          <span>触发 provenance</span>
        </div>
        <span className="rounded border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
          {event.sourceType || provenance.source || trigger.source || "trigger"}
        </span>
      </div>

      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Trigger" value={provenance.trigger?.name || provenance.triggerId || trigger.triggerId} />
        <Field label="Event type" value={event.eventType} mono={false} />
        <Field label="Event" value={event.triggerEventId || provenance.triggerEventId || trigger.triggerEventId} />
        <Field label="Cursor" value={event.cursor || provenance.cursor || trigger.cursor} />
        <Field label="External event" value={event.externalEventId} />
        <Field label="Idempotency" value={event.idempotencyKey || dispatch.idempotencyKey} />
        <Field label="Payload hash" value={shortHash(event.payloadHash)} />
        <Field label="Created" value={formatDateTime(event.createdAt)} mono={false} />
        <Field label="Dispatch" value={dispatch.state} mono={false} />
        <Field label="Request" value={dispatch.requestId} />
        <Field label="Dispatch ID" value={dispatch.dispatchId} />
        <Field label="Dispatch error" value={shortHash(dispatch.errorHash)} />
      </div>

      {backfill ? (
        <Subsection icon={<Layers strokeWidth={1.5} className="h-3.5 w-3.5 text-emerald-500" />} title="Backfill partition">
          <Field label="Partition" value={backfill.partitionKey || backfill.partitionId} />
          <Field label="Launch" value={backfill.launchId} />
          <Field label="Window" value={windowLabel(backfill.window)} mono={false} />
          <Field label="State" value={backfill.state} mono={false} />
          <Field label="Run spec" value={shortHash(backfill.runSpecHash)} />
          <Field label="Cursor" value={backfill.cursor} />
        </Subsection>
      ) : null}

      {inbox ? (
        <Subsection icon={<Inbox strokeWidth={1.5} className="h-3.5 w-3.5 text-indigo-500" />} title="Webhook inbox">
          <Field label="Inbox event" value={inbox.inboxEventId} />
          <Field label="Provider event" value={inbox.eventId} />
          <Field label="Source" value={inbox.source} mono={false} />
          <Field label="Signature" value={inbox.signatureState} mono={false} />
          <Field label="Correlation" value={inbox.correlationId} />
          <Field label="Payload hash" value={shortHash(inbox.payloadHash)} />
          <Field label="Raw body" value={shortHash(inbox.rawBodySha256)} />
          <Field label="Deliveries" value={inbox.deliveryCount === undefined ? "" : String(inbox.deliveryCount)} mono={false} />
        </Subsection>
      ) : null}
    </section>
  );
}

function Subsection({
  children,
  icon,
  title,
}: {
  children: ReactNode;
  icon: ReactNode;
  title: string;
}) {
  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-700">
        {icon}
        <span>{title}</span>
      </div>
      <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">{children}</div>
    </div>
  );
}

function Field({ label, value, mono = true }: { label: string; value?: string | null; mono?: boolean }) {
  if (!value) return null;
  return (
    <div className="min-w-0 rounded border border-slate-100 bg-slate-50 px-2 py-1.5">
      <div className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className={mono ? "mt-0.5 truncate font-mono text-[11px] text-slate-700" : "mt-0.5 truncate text-[11px] text-slate-700"}>
        {value}
      </div>
    </div>
  );
}

function formatDateTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortHash(value?: string) {
  if (!value) return "";
  return value.length > 16 ? `${value.slice(0, 12)}...${value.slice(-4)}` : value;
}

function windowLabel(window?: { start?: string; end?: string; semantics?: string }) {
  if (!window?.start && !window?.end) return "";
  return `${window.start || "?"} -> ${window.end || "?"}${window.semantics ? ` (${window.semantics})` : ""}`;
}
