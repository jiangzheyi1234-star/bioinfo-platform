"use client";

import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock3,
  Loader2,
  PackageCheck,
  Play,
  RefreshCw,
  Rocket,
  Server,
  ShieldCheck,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { WorkflowServer } from "@/app/components/workflows-page-model";
import { friendlyFirstRunMessage } from "../_domain/first-run-display";
import type { FirstRunStep, FirstRunStepState } from "../_domain/first-run-progress";
import type { FirstRunContinueAction } from "./workflow-first-run-conductor";

export function FirstRunLaunchOverview({
  action,
  busy,
  error,
  onContinue,
  onRefresh,
  refreshing,
  resultId,
  runId,
  runSubmitted,
  sampleReady,
  server,
  serverConnected,
  serverReady,
  steps,
  validationReady,
}: {
  action: FirstRunContinueAction;
  busy: boolean;
  error: string;
  onContinue: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  resultId: string;
  runId: string;
  runSubmitted: boolean;
  sampleReady: boolean;
  server: WorkflowServer | null;
  serverConnected: boolean;
  serverReady: boolean;
  steps: FirstRunStep[];
  validationReady: boolean;
}) {
  const disabled = busy || action.disabled === true || action.code === "COMPLETE";
  const completedCount = steps.filter((step) => step.state === "done").length;
  const currentStep = steps.find((step) => step.state === "current" || step.state === "blocked") || steps[completedCount] || steps[steps.length - 1];
  const percent = steps.length ? Math.round((completedCount / steps.length) * 100) : 0;
  return (
    <section
      className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
      data-testid="first-run-overview"
    >
      <div className="grid lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 p-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
              <Rocket strokeWidth={1.5} className="h-3.5 w-3.5" />
              Moving Pictures 16S
            </span>
            <span className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-500">
              {completedCount}/{steps.length} 已完成
            </span>
          </div>
          <div className="mt-5 max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-normal text-slate-950">
              完成第一次可信运行
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              连接远端、准备官方样例、提交运行，并在结束后得到可下载的结果包与验证证据。
            </p>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <OverviewSignal
              icon={Server}
              label="远端连接"
              value={server?.label || server?.serverId || "待连接"}
              ready={serverConnected}
            />
            <OverviewSignal
              icon={ShieldCheck}
              label="运行环境"
              value={serverReady ? "runner 已就绪" : "等待检查"}
              ready={serverReady}
            />
            <OverviewSignal
              icon={Play}
              label="示例运行"
              value={runSubmitted ? runId || "已提交" : sampleReady ? "可提交" : "准备样例"}
              ready={runSubmitted}
            />
            <OverviewSignal
              icon={PackageCheck}
              label="交付物"
              value={validationReady ? "证据包可下载" : resultId ? "等待验证" : "等待结果"}
              ready={validationReady}
            />
          </div>

          <div className="mt-6">
            <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
              <span>整体进度</span>
              <span>{percent}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${percent}%` }} />
            </div>
          </div>

          <FirstRunStepRail steps={steps} />
        </div>

        <div
          className={cn("border-t border-slate-200 bg-slate-50/70 p-6 lg:border-l lg:border-t-0", nextActionToneClass(action.tone))}
          data-testid="first-run-conductor"
          data-first-run-next-action={action.code}
          data-first-run-next-target={action.target}
        >
          <div className="text-xs font-medium uppercase tracking-[0.08em] text-slate-500">下一步</div>
          <div className="mt-3 flex items-start gap-3">
            <div className="mt-0.5 rounded-full bg-white p-2 shadow-sm">
              {busy ? (
                <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin text-slate-600" />
              ) : (
                <ArrowRight strokeWidth={1.5} className="h-4 w-4 text-slate-600" />
              )}
            </div>
            <div className="min-w-0">
              <div className="text-lg font-semibold text-slate-950">{friendlyActionLabel(action.label)}</div>
              <p className="mt-1 text-sm leading-6 text-slate-600">{friendlyActionDetail(action.detail)}</p>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <Button
              type="button"
              className="h-10 bg-slate-950 px-4 text-sm text-white hover:bg-slate-800"
              disabled={disabled}
              onClick={onContinue}
              data-testid="first-run-continue"
            >
              {busy ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <ArrowRight strokeWidth={1.5} className="mr-2 h-4 w-4" />}
              继续首跑
            </Button>
            <Button
              type="button"
              variant="outline"
              className="h-10 bg-white px-3 text-sm text-slate-600"
              disabled={refreshing}
              onClick={onRefresh}
            >
              <RefreshCw strokeWidth={1.5} className={refreshing ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
              刷新
            </Button>
          </div>

          {error ? <div className="mt-3 text-xs font-medium text-red-700">{error}</div> : null}

          <div className="mt-5 rounded-md border border-white/80 bg-white/70 px-3 py-2 text-xs leading-5 text-slate-500">
            当前步骤：
            <span className="font-medium text-slate-800">{currentStep?.label || "等待状态"}</span>
            {currentStep?.detail ? <span>，{currentStep.detail}</span> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

export function FirstRunStepRail({ steps }: { steps: FirstRunStep[] }) {
  return (
    <div className="mt-6" data-testid="first-run-step-list">
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => (
          <a
            key={step.id}
            href={step.target}
            className={cn(
              "group min-w-0 rounded-md border px-3 py-3 transition focus:outline-none focus:ring-2 focus:ring-blue-200",
              stepRailClass(step.state)
            )}
            data-first-run-step={step.id}
            data-step-state={step.state}
            data-step-target={step.target}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-slate-400">{String(index + 1).padStart(2, "0")}</span>
              <StepStateIcon state={step.state} />
            </div>
            <div className="mt-2 text-xs font-semibold leading-5 text-slate-900">{step.label}</div>
          </a>
        ))}
      </div>
    </div>
  );
}

function OverviewSignal({
  icon: Icon,
  label,
  ready,
  value,
}: {
  icon: typeof Server;
  label: string;
  ready: boolean;
  value: string;
}) {
  return (
    <div className="min-w-0 border-t border-slate-100 pt-3">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <Icon strokeWidth={1.5} className={cn("h-3.5 w-3.5", ready ? "text-emerald-500" : "text-slate-400")} />
        {label}
      </div>
      <div className={cn("mt-1 truncate text-sm font-semibold", ready ? "text-slate-950" : "text-slate-500")}>{value}</div>
    </div>
  );
}

function StepStateIcon({ state }: { state: FirstRunStepState }) {
  if (state === "done") return <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-500" />;
  if (state === "blocked") return <Circle strokeWidth={2} className="h-4 w-4 fill-red-50 text-red-500" />;
  if (state === "current") return <Clock3 strokeWidth={1.5} className="h-4 w-4 text-blue-500" />;
  return <Circle strokeWidth={1.5} className="h-4 w-4 text-slate-300" />;
}

function stepRailClass(state: FirstRunStepState) {
  if (state === "done") return "border-emerald-200 bg-emerald-50/70 hover:bg-emerald-50";
  if (state === "blocked") return "border-red-200 bg-red-50 hover:bg-red-50";
  if (state === "current") return "border-blue-200 bg-blue-50/80 hover:bg-blue-50";
  return "border-slate-200 bg-white hover:bg-slate-50";
}

function nextActionToneClass(tone: FirstRunContinueAction["tone"]) {
  if (tone === "success") return "text-emerald-900";
  if (tone === "danger") return "text-red-900";
  if (tone === "warning") return "text-amber-900";
  return "text-blue-900";
}

function friendlyActionDetail(detail: string) {
  return friendlyFirstRunMessage(detail)
    .replace("首跑不会在未连接状态下猜测 runner。", "系统会先确认 SSH 和远端 runner，再继续后续步骤。")
    .replace("执行运行环境检查，确认 Snakemake、执行配置、示例目录和任务队列可用。", "检查远端服务、Snakemake 和任务队列，确保首跑可以稳定执行。");
}

function friendlyActionLabel(label: string) {
  return friendlyFirstRunMessage(label).replace("准备 runner", "检查运行环境");
}
