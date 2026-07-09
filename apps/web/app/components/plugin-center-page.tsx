"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createRemoteProvisioningJob, fetchRemoteProvisioningJobQueue, fetchServerProfiles } from "./plugin-center-api";
import { PluginCenterExtensionManager } from "./plugin-center-extension-manager";
import {
  isActiveRemoteProvisioningJob,
  type PluginCenterExtensionItem,
  type PluginCenterViewMode,
  type RemoteProvisioningJob,
  type RemoteProvisioningJobAction,
  type RemoteProvisioningJobQueue,
  type ServerProfile,
  type ServerProfileList,
} from "./plugin-center-model";
import { buildPluginCenterExtensions, buildPluginCenterTasks } from "./plugin-center-view-model";
import { RunnerRepairPanel } from "./ssh-runner-repair-panel";
import { useSshShell } from "./ssh-shell";
import {
  isRunnerManuallyStopped,
  normalizeFetchError,
  runnerNeedsDiagnosticsRepair,
  toForm,
  type RunnerLifecycleStatus,
  type RunnerRepairStatus,
} from "./ssh-shell-model";
import { useToolPrepareTasks } from "./tool-prepare-task-context";
import { fetchToolPrepareJobQueue } from "./tools-page-api";
import { TOOL_PREPARE_ACTIVE_STATUSES, type ToolPrepareJobQueue } from "./tools-page-model";
import { useWorkflowRunnerRepairState } from "./workflow-runner-repair-state";

const REMOTE_PROVISIONING_POLL_MS = 1500;
const TOOL_PREPARE_QUEUE_POLL_MS = 2500;

function remoteProvisioningAction(status: RunnerRepairStatus | null): RemoteProvisioningJobAction {
  if (runnerNeedsDiagnosticsRepair(status)) return "repair-runner";
  return isRunnerManuallyStopped(status) ? "start-runner" : "ensure-runner";
}

function toolPrepareActiveCount(queue: ToolPrepareJobQueue | null): number {
  if (!queue) return 0;
  return TOOL_PREPARE_ACTIVE_STATUSES.reduce((total, status) => total + Number(queue.statusCounts?.[status] || 0), 0);
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

function mergePluginRemoteStatus(
  status: RunnerRepairStatus | null,
  profile: ServerProfile | null
): RunnerRepairStatus | null {
  if (!profile) return status;
  const connected = Boolean(status?.connected || profile.connected);
  const profileRunner = profile.runner;
  const runnerReady = Boolean(status?.runner?.ready || profileRunner.ready);
  const runner: RunnerLifecycleStatus = {
    state: runnerReady ? "ready" : status?.runner?.state || profileRunner.state || "preparing",
    ready: runnerReady,
    message: runnerReady
      ? profileRunner.message || status?.runner?.message || "Remote runner control plane is ready."
      : status?.runner?.message || profileRunner.message || "",
    reasonCode: runnerReady ? "" : status?.runner?.reasonCode || profileRunner.reasonCode || "",
    deploymentAction: status?.runner?.deploymentAction || profileRunner.deploymentAction,
    servicePort: status?.runner?.servicePort || profileRunner.servicePort,
    tunnelPort: status?.runner?.tunnelPort || profileRunner.tunnelPort,
    localTunnels: status?.runner?.localTunnels || [],
  };
  return {
    connected,
    connecting: status?.connecting,
    auto_connect_in_progress: status?.auto_connect_in_progress,
    displayTarget: status?.displayTarget || profile.displayName,
    host: status?.host || profile.connection.host,
    message: status?.message || profileRunner.message || "",
    serverId: status?.serverId || profile.serverId,
    runner,
  };
}

export function PluginCenterPage() {
  const sshShell = useSshShell();
  const runnerRepair = useWorkflowRunnerRepairState();
  const { activeTasks: activeToolPrepareTasks } = useToolPrepareTasks();
  const [viewMode, setViewMode] = useState<PluginCenterViewMode>("plugins");
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [provisioningQueue, setProvisioningQueue] = useState<RemoteProvisioningJobQueue | null>(null);
  const [serverProfiles, setServerProfiles] = useState<ServerProfileList | null>(null);
  const [toolPrepareQueue, setToolPrepareQueue] = useState<ToolPrepareJobQueue | null>(null);
  const [provisioningBusy, setProvisioningBusy] = useState(false);
  const [provisioningError, setProvisioningError] = useState("");
  const refreshedTerminalJobKeyRef = useRef("");
  const rawStatus = runnerRepair.status || sshShell.status;
  const rawServerId = rawStatus?.serverId || runnerRepair.server?.serverId || "";
  const activeServerProfile = useMemo(
    () =>
      serverProfiles?.items.find((profile) => profile.serverId === rawServerId) ||
      serverProfiles?.items.find((profile) => profile.profileId === serverProfiles.activeProfileId) ||
      null,
    [serverProfiles, rawServerId]
  );
  const status = useMemo(
    () => mergePluginRemoteStatus(rawStatus || null, activeServerProfile),
    [activeServerProfile, rawStatus]
  );
  const serverId = status?.serverId || rawServerId;
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
  const runnerReady = Boolean(status?.connected && status.runner?.ready);
  const persistentToolPrepareActiveCount = toolPrepareActiveCount(toolPrepareQueue);
  const activeToolPrepareTaskCount = Math.max(activeToolPrepareTasks.length, persistentToolPrepareActiveCount);
  const extensions = useMemo(
    () =>
      buildPluginCenterExtensions({
        activeProvisioningJob: activeRunnerProvisioningJob,
        activeServerProfile,
        activeToolPrepareTaskCount,
        provisioningQueue,
        status: status || null,
        toolPrepareQueue,
      }),
    [activeRunnerProvisioningJob, activeServerProfile, activeToolPrepareTaskCount, provisioningQueue, status, toolPrepareQueue]
  );
  const installationTasks = useMemo(
    () => buildPluginCenterTasks(provisioningQueue, toolPrepareQueue),
    [provisioningQueue, toolPrepareQueue]
  );

  const refreshProvisioningJobs = useCallback(async (signal?: AbortSignal) => {
    const queue = await fetchRemoteProvisioningJobQueue({ limit: 12, signal });
    setProvisioningQueue(queue);
    return queue;
  }, []);

  const refreshToolPrepareQueue = useCallback(async (signal?: AbortSignal) => {
    try {
      const queue = await fetchToolPrepareJobQueue({ limit: 12, signal });
      setToolPrepareQueue(queue);
      return queue;
    } catch {
      setToolPrepareQueue(null);
      return null;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshProvisioningJobs(controller.signal).catch(() => undefined);
    void refreshToolPrepareQueue(controller.signal);
    void fetchServerProfiles(controller.signal)
      .then(setServerProfiles)
      .catch(() => undefined);
    return () => controller.abort();
  }, [refreshProvisioningJobs, refreshToolPrepareQueue]);

  useEffect(() => {
    if (activeProvisioningJobs.length === 0) return;
    const timer = window.setInterval(() => {
      void refreshProvisioningJobs().catch(() => undefined);
    }, REMOTE_PROVISIONING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [activeProvisioningJobs.length, refreshProvisioningJobs]);

  useEffect(() => {
    if (persistentToolPrepareActiveCount === 0) return;
    const timer = window.setInterval(() => {
      void refreshToolPrepareQueue();
    }, TOOL_PREPARE_QUEUE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [persistentToolPrepareActiveCount, refreshToolPrepareQueue]);

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
      const job = await createRemoteProvisioningJob(serverId, remoteProvisioningAction(status || null));
      setProvisioningQueue((current) => mergeRemoteProvisioningJob(current, job));
      await refreshProvisioningJobs();
    } catch (error) {
      setProvisioningError(normalizeFetchError(error));
    } finally {
      setProvisioningBusy(false);
    }
  };

  const handleViewModeChange = (mode: PluginCenterViewMode) => {
    setViewMode(mode);
    setSourceFilter("all");
    setQuery("");
  };

  const handlePrimaryAction = (item: PluginCenterExtensionItem) => {
    if (item.id === "h2ometa-remote-runner") {
      if (!status?.connected) {
        openConnectDialog();
        return;
      }
      if (!runnerReady) {
        void startRemoteExecutorProvisioning();
        return;
      }
      document.getElementById("remote-runner-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (item.primaryAction === "try_in_chat") {
      setViewMode("skills");
      setQuery(item.name);
    }
  };

  const remoteDetail = status?.connected ? (
    <div className="space-y-3">
      <div className="border-b border-slate-100 pb-3">
        <h2 className="text-base font-semibold text-slate-950">远端执行器详情</h2>
        <p className="mt-1 text-sm text-slate-500">Runner repair、诊断、停止、清理和卸载控制。</p>
      </div>
      <RunnerRepairPanel
        status={status}
        ensureRunnerBusy={runnerRepair.runnerEnsureBusy}
        onEnsureRunner={() => void runnerRepair.ensureRunner()}
        onRefreshStatus={runnerRepair.refreshWorkflowServer}
        diagnosticsOnly={false}
        className="shadow-none"
      />
      {provisioningError ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {provisioningError}
        </div>
      ) : null}
    </div>
  ) : null;

  return (
    <PluginCenterExtensionManager
      items={extensions}
      tasks={installationTasks}
      viewMode={viewMode}
      query={query}
      sourceFilter={sourceFilter}
      remoteDetail={remoteDetail}
      onViewModeChange={handleViewModeChange}
      onQueryChange={setQuery}
      onSourceFilterChange={setSourceFilter}
      onPrimaryAction={handlePrimaryAction}
    />
  );
}
