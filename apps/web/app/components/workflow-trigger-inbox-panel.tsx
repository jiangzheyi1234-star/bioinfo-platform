"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Inbox,
  Loader2,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { WorkflowTriggerInboxEvent } from "./workflow-trigger-model";

export function WorkflowTriggerInboxPanel({
  inboxEvents,
  inboxLoading,
  onReplayInboxEvent,
  replayingInboxEventId,
}: {
  inboxEvents: WorkflowTriggerInboxEvent[];
  inboxLoading: boolean;
  onReplayInboxEvent: (inboxEventId: string) => void;
  replayingInboxEventId: string;
}) {
  const deadLettered = inboxEvents.filter((event) => event.state === "dead_lettered").length;
  const verified = inboxEvents.filter((event) => event.signatureState === "verified").length;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Inbox strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            Webhook inbox
          </div>
          <div className="mt-1 text-xs text-slate-500">Deliveries / signatures / dead-letter replay</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <SummaryPill value={`${inboxEvents.length} deliveries`} />
          {deadLettered ? <SummaryPill tone="red" value={`${deadLettered} dead-lettered`} /> : null}
          {verified ? <SummaryPill tone="emerald" value={`${verified} verified`} /> : null}
        </div>
      </div>

      {inboxLoading ? (
        <div className="flex h-24 items-center justify-center text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取 inbox
        </div>
      ) : inboxEvents.length === 0 ? (
        <div className="rounded-lg border border-slate-200 px-4 py-6 text-center text-sm text-slate-400">暂无 inbox delivery</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="w-[20%] px-3 py-2 font-medium">Delivery</th>
                <th className="w-[16%] px-3 py-2 font-medium">状态</th>
                <th className="w-[18%] px-3 py-2 font-medium">签名</th>
                <th className="w-[22%] px-3 py-2 font-medium">证据</th>
                <th className="w-[14%] px-3 py-2 font-medium">运行</th>
                <th className="w-[10%] px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {inboxEvents.map((event) => (
                <InboxRow
                  key={event.inboxEventId}
                  event={event}
                  onReplayInboxEvent={onReplayInboxEvent}
                  replaying={replayingInboxEventId === event.inboxEventId}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function InboxRow({
  event,
  onReplayInboxEvent,
  replaying,
}: {
  event: WorkflowTriggerInboxEvent;
  onReplayInboxEvent: (inboxEventId: string) => void;
  replaying: boolean;
}) {
  const canReplay = event.state === "dead_lettered";
  return (
    <tr>
      <td className="px-3 py-2">
        <div className="truncate font-medium text-slate-800">{event.eventType || "webhook"}</div>
        <div className="truncate font-mono text-[10px] text-slate-400">{event.inboxEventId}</div>
        <div className="mt-1 truncate text-[10px] text-slate-500">{event.source || "unknown source"}</div>
        {event.receivedAt ? <div className="mt-1 truncate text-[10px] text-slate-400">{formatDate(event.receivedAt)}</div> : null}
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-flex rounded border px-1.5 py-0.5 text-[11px]", inboxStateStyle(event.state))}>
          {inboxStateLabel(event.state)}
        </span>
        <div className="mt-1 truncate text-[10px] text-slate-400">{event.deliveryCount ?? 0} deliveries</div>
        {event.failureCode ? <div className="mt-1 truncate text-[10px] text-red-600">{event.failureCode}</div> : null}
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]", signatureStyle(event.signatureState))}>
          <ShieldCheck strokeWidth={1.5} className="mr-1 h-3 w-3" />
          {signatureLabel(event.signatureState)}
        </span>
        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{event.rawContentType || "content-type unknown"}</div>
        <HeaderNames names={event.rawHeaderNames || []} />
      </td>
      <td className="px-3 py-2">
        <div className="truncate font-mono text-[10px] text-slate-500">{shortHash(event.payloadHash, "no payload hash")}</div>
        <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{shortHash(event.rawBodySha256, "no raw-body hash")}</div>
        <div className="mt-1 truncate text-[10px] text-slate-400">
          {event.payloadSizeBytes ?? 0} payload bytes / {event.rawBodySizeBytes ?? 0} raw bytes
        </div>
        {event.error ? <div className="mt-1 truncate text-[10px] text-red-600">{errorLabel(event.error)}</div> : null}
      </td>
      <td className="px-3 py-2">
        {event.runId ? (
          <Link
            href={`/workflows/results/detail?run=${encodeURIComponent(event.runId)}`}
            className="inline-flex min-w-0 max-w-full items-center gap-1 text-blue-600 hover:text-blue-700"
          >
            <span className="truncate font-mono">{event.runId}</span>
            <ArrowRight strokeWidth={1.5} className="h-3 w-3 shrink-0" />
          </Link>
        ) : (
          <span className="text-slate-400">—</span>
        )}
        {event.triggerEventId ? <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{event.triggerEventId}</div> : null}
      </td>
      <td className="px-3 py-2">
        {canReplay ? (
          <Button
            type="button"
            variant="outline"
            className="h-7 border-amber-200 bg-white px-2 text-[11px] text-amber-700 hover:bg-amber-50 hover:text-amber-800"
            disabled={replaying}
            onClick={() => onReplayInboxEvent(event.inboxEventId)}
          >
            {replaying ? (
              <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <RotateCcw strokeWidth={1.5} className="mr-1 h-3 w-3" />
            )}
            Replay
          </Button>
        ) : event.state === "submitted" ? (
          <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-500" />
        ) : event.state === "replay_failed" ? (
          <AlertCircle strokeWidth={1.5} className="h-4 w-4 text-red-500" />
        ) : (
          <span className="text-slate-400">—</span>
        )}
      </td>
    </tr>
  );
}

function HeaderNames({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  const label = names.slice(0, 3).join(", ");
  const suffix = names.length > 3 ? ` +${names.length - 3}` : "";
  return <div className="mt-1 truncate text-[10px] text-slate-400">{label}{suffix}</div>;
}

function SummaryPill({ tone = "slate", value }: { value: string; tone?: "slate" | "emerald" | "red" }) {
  const toneClass = {
    slate: "border-slate-200 bg-slate-50 text-slate-600",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-700",
    red: "border-red-200 bg-red-50 text-red-700",
  }[tone];
  return <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", toneClass)}>{value}</span>;
}

function inboxStateStyle(state: string | undefined) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "submitted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "dispatching") return "border-blue-200 bg-blue-50 text-blue-700";
  if (normalized === "dead_lettered" || normalized === "replay_failed") return "border-red-200 bg-red-50 text-red-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function inboxStateLabel(state: string | undefined) {
  if (state === "submitted") return "已提交";
  if (state === "dispatching") return "提交中";
  if (state === "dead_lettered") return "Dead-letter";
  if (state === "replay_failed") return "重放失败";
  return state || "unknown";
}

function signatureStyle(state: string | undefined) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "verified") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (normalized === "unsupported") return "border-slate-200 bg-slate-50 text-slate-600";
  if (["missing", "malformed", "expired", "mismatch"].includes(normalized)) return "border-red-200 bg-red-50 text-red-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function signatureLabel(state: string | undefined) {
  if (state === "verified") return "verified";
  if (state === "unsupported") return "unsupported";
  return state || "unknown";
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}

function shortHash(value: string | undefined, fallback: string) {
  if (!value) return fallback;
  return value.length > 16 ? `${value.slice(0, 16)}...` : value;
}

function errorLabel(value: unknown) {
  const record = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  return typeof record.errorType === "string" ? record.errorType : "dispatch error";
}
