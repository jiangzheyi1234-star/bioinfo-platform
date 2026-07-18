"use client";

import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  Clock3,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  agentEventLabel,
  agentStatusLabel,
  shortAgentIdentity,
  type AgentEvent,
} from "./agent-workbench-model";

export type AgentEventTimelineProps = {
  error?: string;
  events: AgentEvent[];
  loading?: boolean;
  onRefresh?: () => void | Promise<void>;
  refreshing?: boolean;
  statusMessage?: string;
};

export function AgentEventTimeline({
  error = "",
  events,
  loading = false,
  onRefresh,
  refreshing = false,
  statusMessage = "",
}: AgentEventTimelineProps) {
  const orderedEvents = events.slice().sort((left, right) => left.sequence - right.sequence);

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-event-timeline-title"
      data-testid="agent-event-timeline"
    >
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Clock3 strokeWidth={1.5} className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <h2 id="agent-event-timeline-title" className="text-sm font-semibold text-slate-950">
              审计时间线
            </h2>
          </div>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {events.length} 个持久事件 · 仅展示稳定审计字段
          </p>
        </div>
        {onRefresh ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            aria-label="刷新审计时间线"
            disabled={refreshing}
            onClick={() => void onRefresh()}
            data-testid="agent-event-refresh"
          >
            {refreshing ? (
              <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        ) : null}
      </div>

      <p className="sr-only" aria-live="polite" aria-atomic="true" data-testid="agent-event-status">
        {statusMessage || (refreshing ? "正在刷新审计时间线" : "")}
      </p>

      <div className="px-4 py-4">
        {error ? (
          <Alert variant="destructive" className="mb-4" data-testid="agent-event-error">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {loading ? (
          <div className="flex min-h-28 items-center justify-center gap-2 text-sm text-slate-500" data-testid="agent-event-loading">
            <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
            正在读取持久事件…
          </div>
        ) : orderedEvents.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center" data-testid="agent-event-empty">
            <CircleDot strokeWidth={1.5} className="mx-auto h-5 w-5 text-slate-400" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium text-slate-700">还没有审计事件</p>
            <p className="mt-1 text-xs text-slate-500">会话创建后，状态转换会按 sequence 出现在这里。</p>
          </div>
        ) : (
          <ol className="space-y-0" aria-label="Agent 会话审计事件">
            {orderedEvents.map((event, index) => (
              <EventRow
                key={event.eventId}
                event={event}
                first={index === 0}
                last={index === orderedEvents.length - 1}
              />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function EventRow({ event, first, last }: { event: AgentEvent; first: boolean; last: boolean }) {
  const tone = eventTone(event.eventType);
  const transitionChanged = Boolean(event.fromStatus && event.fromStatus !== event.toStatus);

  return (
    <li
      className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-3 pb-4 last:pb-0"
      data-event-type={event.eventType}
      data-sequence={event.sequence}
      data-testid="agent-event-row"
    >
      {!last ? <span className="absolute bottom-0 left-[13px] top-7 w-px bg-slate-200" aria-hidden="true" /> : null}
      <span
        className={cn(
          "relative z-10 mt-0.5 flex h-7 w-7 items-center justify-center rounded-full border bg-white",
          tone.ring,
          tone.text
        )}
        aria-hidden="true"
      >
        <EventIcon kind={tone.kind} />
      </span>

      <article className={cn("min-w-0 rounded-lg border px-3 py-3", first ? "border-slate-300 bg-slate-50/70" : "border-slate-200 bg-white")}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900">{agentEventLabel(event.eventType)}</h3>
            <div className="mt-0.5 break-all font-mono text-[11px] text-slate-500">{event.eventType}</div>
          </div>
          <div className="shrink-0 text-right">
            <div className="font-mono text-[11px] font-medium text-slate-600">#{event.sequence}</div>
            <time dateTime={event.createdAt} className="mt-0.5 block text-[11px] text-slate-400">
              {formatDateTime(event.createdAt)}
            </time>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]" data-testid="agent-event-transition">
          {transitionChanged ? (
            <>
              <StatusPill value={event.fromStatus || event.toStatus} muted />
              <span className="text-slate-400" aria-hidden="true">→</span>
            </>
          ) : null}
          <StatusPill value={event.toStatus} />
          <span className="rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-slate-600">
            state v{event.stateVersion}
          </span>
          <span className="rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-slate-600">
            plan g{event.planGeneration}
          </span>
        </div>

        <dl className="mt-3 grid gap-x-3 gap-y-1 text-xs sm:grid-cols-[84px_minmax(0,1fr)]">
          <AuditTerm label="actor" value={event.actor} />
          <AuditTerm label="request" value={event.requestId} />
          {event.correlationId ? <AuditTerm label="correlation" value={event.correlationId} /> : null}
          <AuditTerm label="idempotency" value={event.idempotencyKey} />
          <AuditTerm label="eventId" value={event.eventId} />
        </dl>

        <details className="mt-3 rounded-md border border-slate-200 bg-slate-50/70" data-testid="agent-event-integrity">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-2.5 py-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-300">
            <span className="flex items-center gap-1.5 font-medium text-slate-700">
              <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
              公开 Hash-chain 字段（浏览器不重算 eventHash）
            </span>
            <code className="text-[11px] text-slate-500">{shortAgentIdentity(event.eventHash, 16)}</code>
          </summary>
          <dl className="grid gap-x-3 gap-y-1 border-t border-slate-200 bg-white px-2.5 py-2 font-mono text-[11px] sm:grid-cols-[92px_minmax(0,1fr)]">
            <AuditTerm label="payloadHash" value={event.payloadHash} breakAll />
            <AuditTerm label="eventHash" value={event.eventHash} breakAll />
            <AuditTerm label="prevEventHash" value={event.prevEventHash || "genesis"} breakAll />
          </dl>
        </details>
      </article>
    </li>
  );
}

function AuditTerm({ breakAll = false, label, value }: { breakAll?: boolean; label: string; value: string }) {
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className={cn("min-w-0 font-mono text-slate-700", breakAll ? "break-all" : "truncate")} title={value}>
        {value || "—"}
      </dd>
    </>
  );
}

function StatusPill({ muted = false, value }: { muted?: boolean; value: AgentEvent["toStatus"] }) {
  return (
    <span className={cn("rounded border px-2 py-1 font-medium", muted ? "border-slate-200 bg-white text-slate-500" : "border-blue-200 bg-blue-50 text-blue-700")}>
      {agentStatusLabel(value)}
    </span>
  );
}

function EventIcon({ kind }: { kind: "error" | "success" | "neutral" }) {
  if (kind === "error") return <XCircle strokeWidth={1.5} className="h-3.5 w-3.5" />;
  if (kind === "success") return <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5" />;
  return <CircleDot strokeWidth={1.5} className="h-3.5 w-3.5" />;
}

function eventTone(eventType: string): { kind: "error" | "success" | "neutral"; ring: string; text: string } {
  if (eventType.includes("rejected") || eventType.includes("cancelled")) {
    return { kind: "error", ring: "border-red-200", text: "text-red-600" };
  }
  if (eventType.includes("validated") || eventType.includes("approved") || eventType.includes("compiled")) {
    return { kind: "success", ring: "border-emerald-200", text: "text-emerald-600" };
  }
  return { kind: "neutral", ring: "border-slate-200", text: "text-slate-500" };
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}
