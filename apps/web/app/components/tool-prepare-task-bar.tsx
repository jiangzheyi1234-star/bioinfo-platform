"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, Clock3, Loader2, Trash2, X, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { isActiveJob, isTerminalJob, useToolPrepareTasks } from "./tool-prepare-task-context";
import type { ToolPrepareJob, ToolPrepareJobEvent } from "./tools-page-model";

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中",
  validating_spec: "验证规格",
  profile_schema_validation: "Profile schema",
  static_rulespec_validation: "静态 RuleSpec",
  environment_resolution: "解析环境",
  runtime_check: "检查运行时",
  preparing_workflow: "生成验证流程",
  dry_run: "Snakemake dry-run",
  smoke_fixture: "检查 smoke 输入",
  smoke_run: "Smoke run",
  output_validation: "输出验证",
  publishing: "发布版本",
  published: "发布完成",
  failed: "失败",
  cancelled: "已取消",
  spec_valid: "验证规格",
};

const PREPARE_STAGES = [
  "profile_schema_validation",
  "static_rulespec_validation",
  "environment_resolution",
  "runtime_check",
  "preparing_workflow",
  "dry_run",
  "smoke_run",
  "output_validation",
  "publishing",
];

export function ToolPrepareTaskBar() {
  const { activeTasks, cancelToolPrepareTask, dismissToolPrepareTask, tasks } = useToolPrepareTasks();
  const [expanded, setExpanded] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState("");
  const selectedJob = useMemo(() => tasks.find((task) => task.jobId === selectedJobId) || tasks[0], [selectedJobId, tasks]);
  const latest = activeTasks[0] || tasks[0];

  useEffect(() => {
    if (!selectedJob && tasks[0]) {
      setSelectedJobId(tasks[0].jobId);
      return;
    }
    if (selectedJob && !tasks.some((task) => task.jobId === selectedJob.jobId)) {
      setSelectedJobId(tasks[0]?.jobId || "");
    }
  }, [selectedJob, tasks]);

  if (tasks.length === 0 || !latest) return null;

  return (
    <div className="pointer-events-none absolute bottom-3 right-3 z-30 w-[min(760px,calc(100%-1.5rem))]">
      <div className="pointer-events-auto overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl shadow-slate-900/10">
        <button
          type="button"
          className="flex min-h-12 w-full items-center gap-3 px-3 py-2 text-left transition hover:bg-slate-50"
          onClick={() => {
            setExpanded((current) => !current);
            setSelectedJobId(selectedJob?.jobId || latest.jobId);
          }}
        >
          <TaskStatusIcon job={latest} />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-medium text-slate-900">{summaryTitle(latest, activeTasks.length)}</span>
              {activeTasks.length > 1 ? (
                <span className="rounded border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">
                  {activeTasks.length} 个运行中
                </span>
              ) : null}
            </div>
            <div className="mt-0.5 truncate text-xs text-slate-500">{stageLabel(latest.stage)} · {latest.message}</div>
          </div>
          {expanded ? <ChevronDown strokeWidth={1.5} className="h-4 w-4 text-slate-400" /> : <ChevronUp strokeWidth={1.5} className="h-4 w-4 text-slate-400" />}
        </button>

        {expanded ? (
          <div className="grid max-h-[460px] border-t border-slate-100 bg-slate-50/70 min-[760px]:grid-cols-[230px_minmax(0,1fr)]">
            <div className="max-h-[460px] overflow-y-auto border-b border-slate-100 bg-white p-2 min-[760px]:border-b-0 min-[760px]:border-r">
              {tasks.map((task) => (
                <button
                  key={task.jobId}
                  type="button"
                  onClick={() => setSelectedJobId(task.jobId)}
                  className={cn(
                    "mb-1 flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition last:mb-0",
                    selectedJob?.jobId === task.jobId ? "bg-slate-900 text-white" : "hover:bg-slate-100"
                  )}
                >
                  <TaskStatusIcon job={task} compact />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">{taskName(task)}</div>
                    <div className={cn("mt-0.5 truncate text-[11px]", selectedJob?.jobId === task.jobId ? "text-slate-300" : "text-slate-500")}>
                      {stageLabel(task.stage)}
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {selectedJob ? (
              <TaskDetails
                job={selectedJob}
                onCancel={() => void cancelToolPrepareTask(selectedJob.jobId)}
                onDismiss={() => dismissToolPrepareTask(selectedJob.jobId)}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TaskDetails({ job, onCancel, onDismiss }: { job: ToolPrepareJob; onCancel: () => void; onDismiss: () => void }) {
  const events = job.events || [];
  return (
    <div className="min-w-0 p-3">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-950">{taskName(job)}</div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{stageLabel(job.stage)}</span>
            <span>{elapsedLabel(job)}</span>
            {job.errorCode ? <span className="text-red-600">{job.errorCode}</span> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isActiveJob(job) ? (
            <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-slate-500 hover:text-red-600" onClick={onCancel} title="取消任务">
              <X strokeWidth={1.5} className="h-3.5 w-3.5" />
              <span className="sr-only">取消任务</span>
            </Button>
          ) : null}
          {isTerminalJob(job) ? (
            <Button type="button" variant="ghost" size="icon" className="h-7 w-7 text-slate-500 hover:text-slate-900" onClick={onDismiss} title="移除任务">
              <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
              <span className="sr-only">移除任务</span>
            </Button>
          ) : null}
        </div>
      </div>

      <StageRail job={job} />

      <div className="mt-3 max-h-[270px] overflow-y-auto rounded-md border border-slate-200 bg-white">
        {events.length > 0 ? (
          events.map((event) => <TaskEventRow key={event.eventId} event={event} />)
        ) : (
          <div className="px-3 py-6 text-center text-xs text-slate-400">暂无日志</div>
        )}
      </div>
    </div>
  );
}

function StageRail({ job }: { job: ToolPrepareJob }) {
  const currentIndex = PREPARE_STAGES.indexOf(job.stage);
  return (
    <div className="mt-3 flex min-w-0 items-center gap-1 overflow-x-auto pb-1">
      {PREPARE_STAGES.map((stage, index) => {
        const active = stage === job.stage;
        const done = job.status === "succeeded" || (currentIndex >= 0 && index < currentIndex);
        return (
          <div
            key={stage}
            className={cn(
              "flex h-6 shrink-0 items-center rounded-md border px-2 text-[11px]",
              active && "border-blue-200 bg-blue-50 text-blue-700",
              done && !active && "border-emerald-200 bg-emerald-50 text-emerald-700",
              !done && !active && "border-slate-200 bg-white text-slate-400"
            )}
          >
            {stageLabel(stage)}
          </div>
        );
      })}
    </div>
  );
}

function TaskEventRow({ event }: { event: ToolPrepareJobEvent }) {
  const details = eventDetails(event.details);
  return (
    <div className="border-b border-slate-100 px-3 py-2 last:border-b-0">
      <div className="flex min-w-0 items-start gap-2">
        <EventDot level={event.level} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium text-slate-500">{stageLabel(event.stage)}</span>
            <span className="text-[11px] text-slate-400">{timeLabel(event.createdAt)}</span>
          </div>
          <div className="mt-0.5 whitespace-pre-wrap text-xs leading-5 text-slate-700">{event.message}</div>
          {details ? <pre className="mt-1 max-h-24 overflow-auto rounded bg-slate-950 px-2 py-1.5 text-[11px] leading-4 text-slate-100">{details}</pre> : null}
        </div>
      </div>
    </div>
  );
}

function TaskStatusIcon({ compact = false, job }: { compact?: boolean; job: ToolPrepareJob }) {
  const className = compact ? "h-3.5 w-3.5" : "h-4 w-4";
  if (job.status === "succeeded") return <CheckCircle2 strokeWidth={1.5} className={cn(className, "shrink-0 text-emerald-500")} />;
  if (job.status === "failed") return <XCircle strokeWidth={1.5} className={cn(className, "shrink-0 text-red-500")} />;
  if (job.status === "cancelled") return <X strokeWidth={1.5} className={cn(className, "shrink-0 text-amber-500")} />;
  if (job.status === "queued") return <Clock3 strokeWidth={1.5} className={cn(className, "shrink-0 text-blue-500")} />;
  return <Loader2 strokeWidth={1.5} className={cn(className, "shrink-0 animate-spin text-blue-500")} />;
}

function EventDot({ level }: { level: string }) {
  return (
    <span
      className={cn(
        "mt-1 h-2 w-2 shrink-0 rounded-full",
        level === "success" && "bg-emerald-500",
        level === "error" && "bg-red-500",
        level === "warning" && "bg-amber-500",
        level !== "success" && level !== "error" && level !== "warning" && "bg-blue-500"
      )}
    />
  );
}

function summaryTitle(job: ToolPrepareJob, activeCount: number) {
  if (activeCount > 1) return "工具验证任务正在运行";
  return `${taskName(job)} · ${statusLabel(job.status)}`;
}

function taskName(job: ToolPrepareJob) {
  return String(job.result?.name || job.request?.name || job.toolId || "工具验证");
}

function statusLabel(status: string) {
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  if (status === "succeeded") return "已发布";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  return status;
}

function stageLabel(stage: string) {
  return STAGE_LABELS[stage] || stage || "准备中";
}

function elapsedLabel(job: ToolPrepareJob) {
  const start = Date.parse(job.startedAt || job.createdAt || "");
  const end = Date.parse(job.finishedAt || "");
  if (!Number.isFinite(start)) return "";
  const seconds = Math.max(0, Math.round(((Number.isFinite(end) ? end : Date.now()) - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function timeLabel(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function eventDetails(raw: Record<string, unknown> | undefined) {
  if (!raw) return "";
  const lines = [
    detailLine("returncode", raw.returncode),
    detailLine("logPath", raw.logPath),
    detailLine("runId", raw.runId),
    detailLine("snakefile", raw.snakefile),
    detailLine("code", raw.code),
    detailLine("artifactCount", raw.artifactCount),
    detailLine("artifactNames", raw.artifactNames),
    typeof raw.tail === "string" && raw.tail.trim() ? raw.tail.trim() : "",
  ].filter(Boolean);
  return lines.join("\n");
}

function detailLine(label: string, value: unknown) {
  const text = String(value ?? "").trim();
  return text ? `${label}: ${text}` : "";
}
