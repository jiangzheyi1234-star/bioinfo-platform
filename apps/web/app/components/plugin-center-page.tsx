"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  executePluginCenterExtensionAction,
  fetchPluginCenterExtensions,
  fetchRemoteProvisioningJobQueue,
  fetchServerProfiles,
} from "./plugin-center-api";
import {
  PluginCenterExtensionDetails,
  type PluginCenterTargetContext,
} from "./plugin-center-extension-details";
import { PluginCenterExtensionManager } from "./plugin-center-extension-manager";
import {
  isActiveRemoteProvisioningJob,
  type PluginCenterExtensionList,
  type PluginCenterExtensionItem,
  type PluginCenterManagedManifestAction,
  type PluginCenterViewMode,
  type RemoteProvisioningJob,
  type RemoteProvisioningJobQueue,
  type ServerProfile,
  type ServerProfileList,
} from "./plugin-center-model";
import { buildPluginCenterTasks } from "./plugin-center-view-model";
import { RunnerRepairPanel } from "./ssh-runner-repair-panel";
import { useSshShell } from "./ssh-shell";
import {
  normalizeFetchError,
  toForm,
  type RunnerLifecycleStatus,
  type RunnerRepairStatus,
} from "./ssh-shell-model";
import { fetchToolPrepareJobQueue } from "./tools-page-api";
import { TOOL_PREPARE_ACTIVE_STATUSES, type ToolPrepareJobQueue } from "./tools-page-model";
import { useWorkflowRunnerRepairState } from "./workflow-runner-repair-state";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

const REMOTE_PROVISIONING_POLL_MS = 1500;
const TOOL_PREPARE_QUEUE_POLL_MS = 2500;
const PREFLIGHT_ACTIONS = new Set(["install", "repair", "update"]);

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

type UninstallPreviewState = {
  item: PluginCenterExtensionItem;
  plan: Record<string, unknown>;
  serverId: string;
};

type ExtensionDetailsState = {
  itemId: string;
  pendingAction: string | null;
};

function recordString(value: Record<string, unknown> | null, key: string): string {
  const next = value?.[key];
  return typeof next === "string" ? next : "";
}

function recordNumber(value: Record<string, unknown> | null, key: string): number {
  const next = value?.[key];
  return typeof next === "number" && Number.isFinite(next) ? next : 0;
}

function recordArrayLength(value: Record<string, unknown> | null, key: string): number {
  const next = value?.[key];
  return Array.isArray(next) ? next.length : 0;
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
  const [viewMode, setViewMode] = useState<PluginCenterViewMode>("plugins");
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [provisioningQueue, setProvisioningQueue] = useState<RemoteProvisioningJobQueue | null>(null);
  const [managedExtensionList, setManagedExtensionList] = useState<PluginCenterExtensionList | null>(null);
  const [extensionListLoading, setExtensionListLoading] = useState(true);
  const [serverProfiles, setServerProfiles] = useState<ServerProfileList | null>(null);
  const [serverProfilesLoading, setServerProfilesLoading] = useState(true);
  const [toolPrepareQueue, setToolPrepareQueue] = useState<ToolPrepareJobQueue | null>(null);
  const [extensionListError, setExtensionListError] = useState("");
  const [extensionActionBusyKey, setExtensionActionBusyKey] = useState("");
  const [extensionActionError, setExtensionActionError] = useState("");
  const [extensionDetails, setExtensionDetails] = useState<ExtensionDetailsState | null>(null);
  const [uninstallPreview, setUninstallPreview] = useState<UninstallPreviewState | null>(null);
  const [uninstallConfirmation, setUninstallConfirmation] = useState("");
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
  const persistentToolPrepareActiveCount = toolPrepareActiveCount(toolPrepareQueue);
  const extensions = useMemo(() => managedExtensionList?.items || [], [managedExtensionList]);
  const selectedExtension = useMemo(
    () => extensions.find((item) => item.id === extensionDetails?.itemId) || null,
    [extensionDetails?.itemId, extensions]
  );
  const activeTarget = useMemo<PluginCenterTargetContext>(
    () => ({
      profileId: activeServerProfile?.profileId || managedExtensionList?.activeProfileId || "",
      serverId: activeServerProfile?.serverId || serverId,
      label:
        activeServerProfile?.displayName ||
        status?.displayTarget ||
        serverId ||
        "未选择 active server profile",
      connected: Boolean(status?.connected || activeServerProfile?.connected),
      trusted: Boolean(activeServerProfile?.hostKeyTrust.trusted),
      loading: serverProfilesLoading && !activeServerProfile,
    }),
    [activeServerProfile, managedExtensionList?.activeProfileId, serverId, serverProfilesLoading, status]
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

  const refreshManagedExtensions = useCallback(async (signal?: AbortSignal, showLoading = false) => {
    if (showLoading) setExtensionListLoading(true);
    try {
      const next = await fetchPluginCenterExtensions(signal);
      setManagedExtensionList(next);
      setExtensionListError("");
      return next;
    } catch (error) {
      if (!signal?.aborted) setExtensionListError(normalizeFetchError(error));
      return null;
    } finally {
      if (showLoading) setExtensionListLoading(false);
    }
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
    void refreshManagedExtensions(controller.signal, true);
    void refreshProvisioningJobs(controller.signal).catch(() => undefined);
    void refreshToolPrepareQueue(controller.signal);
    void fetchServerProfiles(controller.signal)
      .then(setServerProfiles)
      .catch(() => undefined)
      .finally(() => setServerProfilesLoading(false));
    return () => controller.abort();
  }, [refreshManagedExtensions, refreshProvisioningJobs, refreshToolPrepareQueue]);

  useEffect(() => {
    if (activeProvisioningJobs.length === 0) return;
    const timer = window.setInterval(() => {
      void refreshManagedExtensions().catch(() => undefined);
      void refreshProvisioningJobs().catch(() => undefined);
    }, REMOTE_PROVISIONING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [activeProvisioningJobs.length, refreshManagedExtensions, refreshProvisioningJobs]);

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
    void refreshManagedExtensions().catch(() => undefined);
    void runnerRepair.refreshWorkflowServer().catch(() => undefined);
  }, [latestRunnerProvisioningJob, refreshManagedExtensions, runnerRepair]);

  const openConnectDialog = () => {
    sshShell.clearFormError();
    sshShell.setForm(toForm(sshShell.status));
    sshShell.setDialogOpen(true);
  };

  const executeExtensionAction = async (
    item: PluginCenterExtensionItem,
    action: string,
    options: {
      mode?: "run" | "preview";
      confirmation?: string;
      planHash?: string;
      expectedServerId?: string;
    } = {}
  ) => {
    const requiresServerProfile = item.manifest.installTargets.some((target) => target.requiresServerProfile);
    if (requiresServerProfile && !status?.connected) {
      setExtensionDetails(null);
      openConnectDialog();
      return;
    }
    const targetServerId = requiresServerProfile ? options.expectedServerId || serverId : item.serverId || serverId;
    if (requiresServerProfile && !targetServerId) {
      setExtensionActionError("没有可执行的远端 server profile。");
      return;
    }
    if (
      requiresServerProfile &&
      ((options.expectedServerId && options.expectedServerId !== serverId) ||
        (item.serverId && item.serverId !== targetServerId))
    ) {
      setExtensionActionError("远端目标已变化，请刷新插件状态后重新核对预检。");
      return;
    }
    if (requiresServerProfile && !activeTarget.trusted) {
      setExtensionActionError("请先确认当前远端目标的 Host key。");
      return;
    }
    if (action !== "uninstall" && activeRunnerProvisioningJob) {
      setExtensionActionError("远端执行器已有安装任务在运行。");
      return;
    }
    const busyKey = `${item.id}:${action}:${options.mode || "run"}`;
    setExtensionActionBusyKey(busyKey);
    setExtensionActionError("");
    try {
      const result = await executePluginCenterExtensionAction(item.id, {
        action,
        serverId: targetServerId || undefined,
        mode: options.mode || "run",
        confirmation: options.confirmation,
        planHash: options.planHash,
      });
      if (result.job) {
        setProvisioningQueue((current) => mergeRemoteProvisioningJob(current, result.job as RemoteProvisioningJob));
      }
      if (action === "uninstall" && result.plan) {
        setUninstallPreview({ item, plan: result.plan, serverId: result.serverId });
        setUninstallConfirmation("");
      }
      if (action === "uninstall" && result.result) {
        setUninstallPreview(null);
        setUninstallConfirmation("");
      }
      if (action !== "uninstall") {
        setExtensionDetails((current) =>
          current?.itemId === item.id ? { itemId: item.id, pendingAction: null } : current
        );
      }
      await refreshManagedExtensions();
      await refreshProvisioningJobs();
      await runnerRepair.refreshWorkflowServer().catch(() => undefined);
    } catch (error) {
      setExtensionActionError(normalizeFetchError(error));
    } finally {
      setExtensionActionBusyKey("");
    }
  };

  const handleViewModeChange = (mode: PluginCenterViewMode) => {
    setViewMode(mode);
    setSourceFilter("all");
    setQuery("");
  };

  const openExtensionDetails = (item: PluginCenterExtensionItem, pendingAction: string | null = null) => {
    setExtensionActionError("");
    setExtensionDetails({ itemId: item.id, pendingAction });
  };

  const handlePrimaryAction = (item: PluginCenterExtensionItem) => {
    if (PREFLIGHT_ACTIONS.has(item.primaryAction)) {
      if (item.primaryAction !== "update" || item.updateAvailable === true) {
        openExtensionDetails(item, item.primaryAction);
      }
      return;
    }
  };

  const handleSecondaryAction = (item: PluginCenterExtensionItem, action: string) => {
    if (PREFLIGHT_ACTIONS.has(action)) {
      if (action !== "update" || item.updateAvailable === true) openExtensionDetails(item, action);
      return;
    }
    if (action === "uninstall") {
      setExtensionDetails(null);
      void executeExtensionAction(item, action, { mode: "preview" });
      return;
    }
    void executeExtensionAction(item, action);
  };

  const confirmExtensionAction = (item: PluginCenterExtensionItem, action: string, expectedServerId: string) => {
    const declaredAction = item.manifest.actions.find(
      (candidate): candidate is PluginCenterManagedManifestAction =>
        candidate.id === action && candidate.type === "managed-extension-action"
    );
    if (!declaredAction) {
      setExtensionActionError("v2 manifest 未声明该 managed action。");
      return;
    }
    if (declaredAction.requiresConfirmation && !declaredAction.confirmation) {
      setExtensionActionError("v2 manifest 缺少服务端确认合同。");
      return;
    }
    void executeExtensionAction(item, action, {
      confirmation: declaredAction.requiresConfirmation ? declaredAction.confirmation : undefined,
      expectedServerId,
    });
  };

  const runUninstall = () => {
    if (!uninstallPreview) return;
    const planHash = recordString(uninstallPreview.plan, "planHash");
    if (!planHash || uninstallConfirmation.trim() !== uninstallPreview.serverId) return;
    void executeExtensionAction(uninstallPreview.item, "uninstall", {
      mode: "run",
      confirmation: "uninstall-runner-control-plane",
      planHash,
    });
  };

  const uninstallTargetCount = recordNumber(uninstallPreview?.plan || null, "targetCount");
  const uninstallPreservedCount = recordArrayLength(uninstallPreview?.plan || null, "preservedPaths");
  const uninstallPlanHash = recordString(uninstallPreview?.plan || null, "planHash");
  const uninstallConfirmed = Boolean(uninstallPreview && uninstallConfirmation.trim() === uninstallPreview.serverId);

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
    </div>
  ) : null;

  return (
    <PluginCenterExtensionManager
      actionError={extensionActionError}
      activeTarget={activeTarget}
      items={extensions}
      registries={managedExtensionList?.registries || []}
      tasks={installationTasks}
      viewMode={viewMode}
      query={query}
      sourceFilter={sourceFilter}
      loadError={extensionListError}
      loading={extensionListLoading}
      busyActionKey={extensionActionBusyKey}
      remoteDetail={remoteDetail}
      onViewModeChange={handleViewModeChange}
      onQueryChange={setQuery}
      onSourceFilterChange={setSourceFilter}
      onPrimaryAction={handlePrimaryAction}
      onExtensionAction={handleSecondaryAction}
      onOpenDetails={(item) => openExtensionDetails(item)}
      onRetry={() => void refreshManagedExtensions(undefined, true)}
    >
      <PluginCenterExtensionDetails
        actionError={extensionActionError}
        busy={Boolean(selectedExtension && extensionActionBusyKey.startsWith(`${selectedExtension.id}:`))}
        item={selectedExtension}
        open={Boolean(extensionDetails && selectedExtension)}
        pendingAction={extensionDetails?.pendingAction || null}
        target={activeTarget}
        onActionConfirm={confirmExtensionAction}
        onActionRequest={handleSecondaryAction}
        onOpenChange={(open) => (!open ? setExtensionDetails(null) : null)}
      />
      <Dialog open={Boolean(uninstallPreview)} onOpenChange={(open) => (!open ? setUninstallPreview(null) : null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>卸载远端执行器</DialogTitle>
            <DialogDescription>
              仅卸载 runner 控制面，保留 shared 数据边界。输入 serverId 后才能执行。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">
              将移除 {uninstallTargetCount} 个控制面目标，保留 {uninstallPreservedCount} 个 shared 数据边界。
            </div>
            <label className="block text-xs font-medium text-slate-600">
              确认 serverId
              <Input
                className="mt-1 font-mono"
                value={uninstallConfirmation}
                placeholder={uninstallPreview?.serverId || ""}
                onChange={(event) => setUninstallConfirmation(event.target.value)}
              />
            </label>
            {extensionActionError ? <p className="text-xs text-red-600">{extensionActionError}</p> : null}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setUninstallPreview(null)}>
                取消
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={!uninstallPlanHash || !uninstallConfirmed || Boolean(extensionActionBusyKey)}
                onClick={runUninstall}
              >
                卸载
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </PluginCenterExtensionManager>
  );
}
