"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Activity, ArrowRight, Boxes, CheckCircle2, Clock3, Package, Plug, Server, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useSshShell } from "./ssh-shell";
import {
  isRunnerManuallyStopped,
  isRunnerPreparing,
  isRunnerRepairRequired,
  normalizeFetchError,
  resolveRemoteStatus,
  runnerEnsureActionLabel,
  toForm,
  type RunnerRepairStatus,
} from "./ssh-shell-model";
import { createRemoteProvisioningJob, fetchRemoteProvisioningJobQueue } from "./plugin-center-api";
import {
  isActiveRemoteProvisioningJob,
  type RemoteProvisioningJob,
  type RemoteProvisioningJobAction,
  type RemoteProvisioningJobQueue,
} from "./plugin-center-model";
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

type InstallStageState = "done" | "current" | "pending" | "blocked";

type InstallStage = {
  id: "connect" | "trust-host-key" | "install-runner" | "canary" | "ready";
  label: string;
  detail: string;
  state: InstallStageState;
};

function remoteExecutorInstallStages(
  status: RunnerRepairStatus | null,
  activeProvisioningJob: RemoteProvisioningJob | null
): InstallStage[] {
  const connected = Boolean(status?.connected);
  const runner = status?.runner;
  const ready = Boolean(connected && runner?.ready);
  const preparing = isRunnerPreparing(status);
  const provisioningActive = Boolean(activeProvisioningJob);
  const needsRepair = isRunnerRepairRequired(status);
  const manuallyStopped = isRunnerManuallyStopped(status);
  const installBlocked = needsRepair || manuallyStopped || runner?.state === "failed";

  return [
    {
      id: "connect",
      label: "连接 SSH",
      detail: connected ? status?.displayTarget || status?.host || "SSH 已连接" : "从插件中心打开 SSH 连接对话框",
      state: connected ? "done" : "current",
    },
    {
      id: "trust-host-key",
      label: "信任 SSH 主机密钥",
      detail: connected ? "主机密钥已通过当前 known_hosts 校验" : "首次连接会要求确认 SHA256 fingerprint",
      state: connected ? "done" : "pending",
    },
    {
      id: "install-runner",
      label: "安装或复用远端执行器",
      detail: activeProvisioningJob?.message || runner?.message || "使用 manifest artifact 安装、复用或修复 runner",
      state: ready ? "done" : provisioningActive ? "current" : connected ? (installBlocked ? "blocked" : "current") : "pending",
    },
    {
      id: "canary",
      label: "运行 bootstrap canary",
      detail: ready ? "上传、提交运行和结果预览已通过" : "安装后提交最小样例运行并验证产物",
      state: ready ? "done" : preparing || provisioningActive ? "current" : installBlocked ? "blocked" : "pending",
    },
    {
      id: "ready",
      label: "远端执行器就绪",
      detail: ready ? "健康检查、认证隧道和执行能力已就绪" : runner?.reasonCode || "等待远端执行器完成安装验证",
      state: ready ? "done" : installBlocked ? "blocked" : "pending",
    },
  ];
}

function stageIconTone(state: InstallStageState) {
  switch (state) {
    case "done":
      return "text-emerald-600";
    case "current":
      return "text-blue-600";
    case "blocked":
      return "text-amber-600";
    default:
      return "text-slate-400";
  }
}

const REMOTE_PROVISIONING_POLL_MS = 1500;

function remoteProvisioningAction(status: RunnerRepairStatus | null): RemoteProvisioningJobAction {
  return isRunnerManuallyStopped(status) ? "start-runner" : "ensure-runner";
}

function remoteProvisioningJobLabel(job: RemoteProvisioningJob | null): string {
  if (!job) return "暂无远端执行器安装任务";
  const action = job.action === "start-runner" ? "启动" : job.action === "upgrade-runner" ? "升级" : "安装";
  return `${action} · ${job.status} · ${job.stage}`;
}

function mergeRemoteProvisioningJob(
  queue: RemoteProvisioningJobQueue | null,
  job: RemoteProvisioningJob
): RemoteProvisioningJobQueue {
  const items = [job, ...(queue?.items || []).filter((item) => item.jobId !== job.jobId)];
  const activeCount = items.filter(isActiveRemoteProvisioningJob).length;
  return {
    items,
    total: Math.max(queue?.total || 0, items.length),
    limit: queue?.limit || 8,
    offset: queue?.offset || 0,
    status: queue?.status || "",
    statusCounts: statusCountsFromRemoteProvisioningItems(items),
    activeCount,
    queuedCount: items.filter((item) => item.status === "queued").length,
    runningCount: items.filter((item) => item.status === "running").length,
    activeStatuses: queue?.activeStatuses || ["queued", "running"],
    terminalStatuses: queue?.terminalStatuses || ["succeeded", "failed", "cancelled"],
  };
}

function statusCountsFromRemoteProvisioningItems(items: RemoteProvisioningJob[]): Record<string, number> {
  return items.reduce<Record<string, number>>((counts, item) => {
    counts[item.status] = (counts[item.status] || 0) + 1;
    return counts;
  }, {});
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
  const sshShell = useSshShell();
  const runnerRepair = useWorkflowRunnerRepairState();
  const { activeTasks, tasks } = useToolPrepareTasks();
  const [provisioningQueue, setProvisioningQueue] = useState<RemoteProvisioningJobQueue | null>(null);
  const [provisioningBusy, setProvisioningBusy] = useState(false);
  const [provisioningError, setProvisioningError] = useState("");
  const refreshedTerminalJobKeyRef = useRef("");
  const status = runnerRepair.status || sshShell.status;
  const remote = resolveRemoteStatus(status);
  const serverId = status?.serverId || runnerRepair.server?.serverId || "";
  const activeProvisioningJobs = useMemo(
    () => (provisioningQueue?.items || []).filter(isActiveRemoteProvisioningJob),
    [provisioningQueue?.items]
  );
  const activeRunnerProvisioningJob = useMemo(
    () => activeProvisioningJobs.find((job) => job.serverId === serverId) || null,
    [activeProvisioningJobs, serverId]
  );
  const latestProvisioningJob = provisioningQueue?.items?.[0] || null;
  const latestRunnerProvisioningJob =
    provisioningQueue?.items.find((job) => job.serverId === serverId) || latestProvisioningJob;
  const installStages = remoteExecutorInstallStages(status, activeRunnerProvisioningJob);
  const runnerReady = Boolean(status?.connected && status.runner?.ready);
  const canPrepareRunner = Boolean(status?.connected && serverId && !runnerReady);
  const connecting = Boolean(sshShell.connectBusy || status?.connecting || status?.auto_connect_in_progress);
  const activeInstallationTaskCount = activeTasks.length + activeProvisioningJobs.length;

  const refreshProvisioningJobs = useCallback(async (signal?: AbortSignal) => {
    const queue = await fetchRemoteProvisioningJobQueue({ limit: 8, signal });
    setProvisioningQueue(queue);
    return queue;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshProvisioningJobs(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [refreshProvisioningJobs]);

  useEffect(() => {
    if (activeProvisioningJobs.length === 0) return;
    const timer = window.setInterval(() => {
      void refreshProvisioningJobs().catch(() => undefined);
    }, REMOTE_PROVISIONING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [activeProvisioningJobs.length, refreshProvisioningJobs]);

  useEffect(() => {
    if (!latestRunnerProvisioningJob || isActiveRemoteProvisioningJob(latestRunnerProvisioningJob)) {
      return;
    }
    const key = `${latestRunnerProvisioningJob.jobId}:${latestRunnerProvisioningJob.status}:${latestRunnerProvisioningJob.updatedAt}`;
    if (key === refreshedTerminalJobKeyRef.current) {
      return;
    }
    refreshedTerminalJobKeyRef.current = key;
    void runnerRepair.refreshWorkflowServer().catch(() => undefined);
  }, [latestRunnerProvisioningJob, runnerRepair]);

  const openConnectDialog = () => {
    sshShell.clearFormError();
    sshShell.setForm(toForm(sshShell.status));
    sshShell.setDialogOpen(true);
  };

  const startRemoteExecutorProvisioning = async () => {
    if (!serverId || provisioningBusy || activeRunnerProvisioningJob) {
      return;
    }
    setProvisioningBusy(true);
    setProvisioningError("");
    try {
      const job = await createRemoteProvisioningJob(serverId, remoteProvisioningAction(status));
      setProvisioningQueue((current) => mergeRemoteProvisioningJob(current, job));
      await refreshProvisioningJobs();
    } catch (error) {
      setProvisioningError(normalizeFetchError(error));
    } finally {
      setProvisioningBusy(false);
    }
  };

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
                {installStages.map((stage) => (
                  <div
                    key={stage.id}
                    className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 rounded-md border border-slate-100 bg-slate-50 px-2 py-2 text-sm text-slate-600"
                    data-install-stage={stage.id}
                    data-install-stage-state={stage.state}
                  >
                    {stage.state === "done" ? (
                      <CheckCircle2 strokeWidth={1.5} className={cn("mt-0.5 h-4 w-4", stageIconTone(stage.state))} />
                    ) : stage.state === "current" ? (
                      <Activity
                        strokeWidth={1.5}
                        className={cn("mt-0.5 h-4 w-4 animate-pulse", stageIconTone(stage.state))}
                      />
                    ) : stage.state === "blocked" ? (
                      <Wrench strokeWidth={1.5} className={cn("mt-0.5 h-4 w-4", stageIconTone(stage.state))} />
                    ) : (
                      <Clock3 strokeWidth={1.5} className={cn("mt-0.5 h-4 w-4", stageIconTone(stage.state))} />
                    )}
                    <div className="min-w-0">
                      <div className="font-medium text-slate-900">{stage.label}</div>
                      <div className="mt-0.5 truncate text-xs text-slate-500">{stage.detail}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {!status?.connected ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={connecting}
                    onClick={openConnectDialog}
                    data-testid="plugin-center-connect-ssh"
                  >
                    <Plug strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    {connecting ? "连接中" : "连接 SSH"}
                  </Button>
                ) : null}
                {canPrepareRunner ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={runnerRepair.runnerEnsureBusy || provisioningBusy || Boolean(activeRunnerProvisioningJob)}
                    onClick={() => void startRemoteExecutorProvisioning()}
                    data-testid="plugin-center-remote-executor-prepare"
                  >
                    <Wrench strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    {activeRunnerProvisioningJob
                      ? "安装任务运行中"
                      : runnerEnsureActionLabel(status, runnerRepair.runnerEnsureBusy || provisioningBusy)}
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

            {status?.connected ? (
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
                    远端执行器 provisioning job 已接入本地控制面。
                  </div>
                </div>
              </div>
            </CardShell>

            <CardShell testId="plugin-center-installation-tasks-card">
              <div className="flex items-start gap-3">
                <Plug strokeWidth={1.5} className="mt-0.5 h-4 w-4 text-slate-500" />
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-slate-950">安装任务</h2>
                  <p className="mt-1 text-xs text-slate-500">工具验证任务和远端执行器 provisioning jobs 统一在这里跟踪。</p>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                    <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                      <div className="text-[10px] text-slate-500">活跃</div>
                      <div className="font-mono text-slate-900">{activeInstallationTaskCount}</div>
                    </div>
                    <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                      <div className="text-[10px] text-slate-500">工具</div>
                      <div className="font-mono text-slate-900">{tasks.length}</div>
                    </div>
                    <div className="rounded-md border border-slate-100 bg-slate-50 px-2 py-1">
                      <div className="text-[10px] text-slate-500">远端</div>
                      <div className="font-mono text-slate-900">{provisioningQueue?.total || 0}</div>
                    </div>
                  </div>
                  <div
                    className="mt-3 rounded-md border border-slate-100 bg-slate-50 px-2 py-2 text-xs text-slate-600"
                    data-testid="plugin-center-remote-provisioning-latest"
                  >
                    <div className="font-medium text-slate-900">{remoteProvisioningJobLabel(latestProvisioningJob)}</div>
                    <div className="mt-1 truncate text-[11px] text-slate-500">
                      {latestProvisioningJob?.message || "连接 SSH 后可从远端执行器卡片提交安装任务。"}
                    </div>
                  </div>
                  {provisioningError ? (
                    <div
                      className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-800"
                      data-testid="plugin-center-remote-provisioning-error"
                    >
                      {provisioningError}
                    </div>
                  ) : null}
                </div>
              </div>
            </CardShell>
          </div>
        </div>
      </div>
    </div>
  );
}
