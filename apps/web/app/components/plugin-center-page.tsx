"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Activity, ArrowRight, Boxes, CheckCircle2, Clock3, Package, Plug, Server, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  isRunnerPreparing,
  isRunnerRepairRequired,
  resolveRemoteStatus,
  runnerEnsureActionLabel,
} from "./ssh-shell-model";
import { RunnerRepairPanel } from "./ssh-runner-repair-panel";
import { useToolPrepareTasks } from "./tool-prepare-task-context";
import { useWorkflowRunnerRepairState } from "./workflow-runner-repair-state";
import { WorkflowPageHeader } from "./workflow-page-header";

function statusTone(status: ReturnType<typeof resolveRemoteStatus>) {
  if (status.label === "已连接") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status.label.includes("需要修复")) return "border-amber-200 bg-amber-50 text-amber-800";
  if (status.label.includes("连接中") || status.label.includes("SSH 已连接")) return "border-blue-200 bg-blue-50 text-blue-800";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function CardShell({
  children,
  className = "",
  testId,
}: {
  children: ReactNode;
  className?: string;
  testId: string;
}) {
  return (
    <section
      data-testid={testId}
      className={cn("rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-900/5", className)}
    >
      {children}
    </section>
  );
}

export function PluginCenterPage() {
  const runnerRepair = useWorkflowRunnerRepairState();
  const { activeTasks, tasks } = useToolPrepareTasks();
  const status = runnerRepair.status;
  const remote = resolveRemoteStatus(status);
  const serverId = status?.serverId || runnerRepair.server?.serverId || "";
  const runnerReady = Boolean(status?.connected && status.runner?.ready);
  const runnerPreparing = isRunnerPreparing(status);
  const runnerNeedsRepair = isRunnerRepairRequired(status);
  const canPrepareRunner = Boolean(status?.connected && serverId && !runnerReady);

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-4 py-6 text-slate-800 sm:px-6 sm:py-10 lg:px-8">
      <div className="mx-auto max-w-5xl space-y-6" data-testid="plugin-center-page">
        <WorkflowPageHeader title="插件" />

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
          <div className="space-y-4">
            <CardShell testId="plugin-center-remote-executor-card" className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Server strokeWidth={1.5} className="h-4 w-4 text-blue-600" />
                    <h2 className="text-base font-semibold text-slate-950">远端执行器</h2>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    通过 SSH 信任通道安装和管理 H2OMeta remote runner。
                  </p>
                </div>
                <span
                  className={cn("rounded-md border px-2 py-1 text-xs font-medium", statusTone(remote))}
                  data-testid="plugin-center-remote-executor-status"
                >
                  {remote.label}
                </span>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">服务器</div>
                  <div className="mt-1 truncate font-mono text-xs text-slate-900">{serverId || "未连接"}</div>
                </div>
                <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">服务端口</div>
                  <div className="mt-1 font-mono text-xs text-slate-900">{status?.runner?.servicePort || "未记录"}</div>
                </div>
                <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
                  <div className="text-[11px] text-slate-500">本地隧道</div>
                  <div className="mt-1 font-mono text-xs text-slate-900">{status?.runner?.tunnelPort || "未记录"}</div>
                </div>
              </div>

              <div className="space-y-2" data-testid="plugin-center-remote-executor-stage-list">
                {remote.stages.map((stage) => (
                  <div key={stage} className="flex items-center gap-2 text-sm text-slate-600">
                    {runnerReady ? (
                      <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-600" />
                    ) : runnerPreparing ? (
                      <Activity strokeWidth={1.5} className="h-4 w-4 animate-pulse text-blue-600" />
                    ) : runnerNeedsRepair ? (
                      <Wrench strokeWidth={1.5} className="h-4 w-4 text-amber-600" />
                    ) : (
                      <Clock3 strokeWidth={1.5} className="h-4 w-4 text-slate-400" />
                    )}
                    <span>{stage}</span>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {canPrepareRunner ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={runnerRepair.runnerEnsureBusy}
                    onClick={() => void runnerRepair.ensureRunner()}
                    data-testid="plugin-center-remote-executor-prepare"
                  >
                    <Wrench strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    {runnerEnsureActionLabel(status, runnerRepair.runnerEnsureBusy)}
                  </Button>
                ) : null}
                <Button asChild variant="outline" size="sm" data-testid="plugin-center-tools-link">
                  <Link href="/workflows/tools">
                    管理工具插件
                    <ArrowRight strokeWidth={1.5} className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </CardShell>

            {status?.connected && (!status.runner || !status.runner.ready) ? (
              <RunnerRepairPanel
                status={status}
                ensureRunnerBusy={runnerRepair.runnerEnsureBusy}
                onEnsureRunner={() => void runnerRepair.ensureRunner()}
                onRefreshStatus={runnerRepair.refreshWorkflowServer}
                diagnosticsOnly={false}
                className="shadow-none"
              />
            ) : null}
          </div>

          <div className="space-y-4">
            <CardShell testId="plugin-center-tool-plugins-card">
              <div className="flex items-start gap-3">
                <Package strokeWidth={1.5} className="mt-0.5 h-4 w-4 text-slate-500" />
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-slate-950">工具插件</h2>
                  <p className="mt-1 text-xs text-slate-500">Bioconda、conda-forge 和 Snakemake wrapper 工具继续由工具页准备和验证。</p>
                  <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                    <span className="text-slate-500">
                      活跃验证任务 <span className="font-mono text-slate-900">{activeTasks.length}</span>
                    </span>
                    <Link href="/workflows/tools" className="font-medium text-blue-700 hover:text-blue-900">
                      打开工具
                    </Link>
                  </div>
                </div>
              </div>
            </CardShell>

            <CardShell testId="plugin-center-runtime-components-card">
              <div className="flex items-start gap-3">
                <Boxes strokeWidth={1.5} className="mt-0.5 h-4 w-4 text-slate-500" />
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-slate-950">运行环境组件</h2>
                  <p className="mt-1 text-xs text-slate-500">托管 Snakemake runtime、wrapper 缓存和数据库运行层会逐步汇入这里。</p>
                  <div className="mt-3 rounded-md border border-slate-100 bg-slate-50 px-2 py-1 text-[11px] text-slate-500">
                    下一阶段接入 provisioning job 后展示安装事件。
                  </div>
                </div>
              </div>
            </CardShell>

            <CardShell testId="plugin-center-installation-tasks-card">
              <div className="flex items-start gap-3">
                <Plug strokeWidth={1.5} className="mt-0.5 h-4 w-4 text-slate-500" />
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-slate-950">安装任务</h2>
                  <p className="mt-1 text-xs text-slate-500">工具验证任务已接入；远端执行器 provisioning job 是下一阶段。</p>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                      <div className="text-[10px] text-slate-500">活跃</div>
                      <div className="font-mono text-slate-900">{activeTasks.length}</div>
                    </div>
                    <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                      <div className="text-[10px] text-slate-500">最近</div>
                      <div className="font-mono text-slate-900">{tasks.length}</div>
                    </div>
                  </div>
                </div>
              </div>
            </CardShell>
          </div>
        </div>
      </div>
    </div>
  );
}
