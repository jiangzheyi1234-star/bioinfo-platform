"use client";

import { Clock3, Loader2, Plus, RefreshCw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  agentStatusLabel,
  shortAgentIdentity,
  type AgentSession,
  type AgentSessionStatus,
} from "./agent-workbench-model";

export type AgentSessionListProps = {
  activeSessionId?: string;
  disabled?: boolean;
  error?: string;
  loading?: boolean;
  onRefresh: () => void | Promise<void>;
  onSelect: (sessionId: string) => void;
  onStartNew: () => void;
  refreshing?: boolean;
  sessions: AgentSession[];
};

export function AgentSessionList({
  activeSessionId = "",
  disabled = false,
  error = "",
  loading = false,
  onRefresh,
  onSelect,
  onStartNew,
  refreshing = false,
  sessions,
}: AgentSessionListProps) {
  const orderedSessions = sessions.slice().sort((left, right) => dateValue(right.updatedAt) - dateValue(left.updatedAt));

  return (
    <aside
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-session-list-title"
      data-testid="agent-session-list"
    >
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <h2 id="agent-session-list-title" className="text-sm font-semibold text-slate-950">
            Agent 会话
          </h2>
          <p className="mt-0.5 text-[11px] text-slate-500">{sessions.length} 个持久会话</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label="刷新 Agent 会话"
            disabled={disabled || refreshing}
            onClick={() => void onRefresh()}
            data-testid="agent-session-refresh"
          >
            {refreshing ? (
              <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 bg-white px-2.5"
            disabled={disabled}
            onClick={onStartNew}
            data-testid="agent-session-new"
          >
            <Plus strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
            新建
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive" className="m-3 py-2 text-xs" data-testid="agent-session-list-error">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading && sessions.length === 0 ? (
        <div className="flex items-center justify-center px-4 py-10 text-sm text-slate-400" aria-live="polite">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          正在读取会话
        </div>
      ) : orderedSessions.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <div className="text-sm text-slate-500">还没有 Agent 会话</div>
          <p className="mt-1 text-xs leading-5 text-slate-400">从一个 FASTQ 目标开始，系统会保留方案与审批历史。</p>
        </div>
      ) : (
        <ul className="max-h-[34rem] divide-y divide-slate-100 overflow-y-auto" aria-label="Agent 会话列表">
          {orderedSessions.map((session) => {
            const active = session.sessionId === activeSessionId;
            return (
              <li key={session.sessionId}>
                <button
                  type="button"
                  disabled={disabled}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "w-full px-4 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-300 disabled:cursor-not-allowed disabled:opacity-60",
                    active ? "bg-blue-50/70" : "bg-white hover:bg-slate-50"
                  )}
                  onClick={() => onSelect(session.sessionId)}
                  data-session-status={session.status}
                  data-testid={`agent-session-row-${session.sessionId}`}
                >
                  <span className="flex min-w-0 items-start justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-900">{session.goal.summary}</span>
                      <span className="mt-1 block truncate font-mono text-[11px] text-slate-400">
                        {shortAgentIdentity(session.sessionId, 16)} · generation {session.planGeneration}
                      </span>
                    </span>
                    <StatusBadge status={session.status} />
                  </span>
                  <span className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-500">
                    <Clock3 strokeWidth={1.5} className="h-3 w-3" aria-hidden="true" />
                    更新于 {formatDateTime(session.updatedAt)}
                  </span>
                  {session.lastErrorCode ? (
                    <span className="mt-1 block truncate font-mono text-[10px] text-red-600">{session.lastErrorCode}</span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}

function StatusBadge({ status }: { status: AgentSessionStatus }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium",
        statusClass(status)
      )}
    >
      {agentStatusLabel(status)}
    </span>
  );
}

function statusClass(status: AgentSessionStatus) {
  if (status === "ready_to_run") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "awaiting_approval") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "planning") return "border-cyan-200 bg-cyan-50 text-cyan-700";
  if (status === "plan_failed") return "border-red-200 bg-red-50 text-red-700";
  if (status === "changes_requested") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function dateValue(value?: string) {
  if (!value) return 0;
  const date = new Date(value).getTime();
  return Number.isNaN(date) ? 0 : date;
}
