"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, RefreshCw, Square, Trash2, X } from "lucide-react";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  isRunnerManuallyStopped,
  normalizeFetchError,
  resolveRemoteStatus,
  runnerEnsureActionLabel,
  type RunnerRepairStatus,
} from "./ssh-shell-model";

type RunnerReleasePrunePlan = {
  planHash?: string;
  deletableReleaseCount?: number;
  deletableBytes?: number;
  releases?: Array<{
    name?: string;
    deletable?: boolean;
    protectedReasons?: string[];
    sizeBytes?: number;
  }>;
};

type RunnerUninstallPlan = {
  planHash?: string;
  targetCount?: number;
  removedTargetCount?: number;
  controlPlaneOnly?: boolean;
  blockReasons?: string[];
  preservedPaths?: Array<{ path?: string; reason?: string }>;
};

type RunnerRepairPanelProps = {
  status: RunnerRepairStatus | null;
  ensureRunnerBusy: boolean;
  onEnsureRunner: () => void;
  onRefreshStatus: () => Promise<unknown>;
  onClose?: () => void;
  diagnosticsOnly?: boolean;
  className?: string;
};

function formatRunnerPort(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? String(value) : "未记录";
}

function formatTunnelEndpoint(host: string | undefined, port: number | undefined): string {
  const safeHost = String(host || "").trim();
  const safePort = formatRunnerPort(port);
  if (!safeHost || safePort === "未记录") {
    return "未记录";
  }
  return `${safeHost}:${safePort}`;
}

function formatBytes(value: number | undefined): string {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`;
}

function compactJson(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2).slice(0, 4000);
}

function confirmationMatches(value: string, target: string): boolean {
  return Boolean(target && value.trim() === target);
}

function DestructiveConfirmation({
  action,
  disabled = false,
  target,
  value,
  onChange,
}: {
  action: string;
  disabled?: boolean;
  target: string;
  value: string;
  onChange: (value: string) => void;
}) {
  if (!target) {
    return null;
  }
  return (
    <label className="mt-2 block text-[11px] text-slate-500">
      <span className="flex items-center gap-1 text-[10px] font-semibold text-amber-700">
        <AlertTriangle className="size-3" />
        {action} 确认
      </span>
      <Input
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        placeholder={`输入 ${target}`}
        aria-label={`${action} 确认 serverId`}
        className="mt-1 h-7 rounded border-amber-200 px-2 py-1 font-mono text-[11px] focus:border-amber-400"
      />
    </label>
  );
}

export function RunnerRepairPanel({
  status,
  ensureRunnerBusy,
  onEnsureRunner,
  onRefreshStatus,
  onClose,
  diagnosticsOnly = false,
  className = "",
}: RunnerRepairPanelProps) {
  const [portsLoading, setPortsLoading] = useState(false);
  const [portsOutput, setPortsOutput] = useState("");
  const [portsError, setPortsError] = useState("");
  const [stopLoading, setStopLoading] = useState(false);
  const [stopOutput, setStopOutput] = useState("");
  const [stopError, setStopError] = useState("");
  const [upgradeLoading, setUpgradeLoading] = useState(false);
  const [upgradeOutput, setUpgradeOutput] = useState("");
  const [upgradeError, setUpgradeError] = useState("");
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
  const [diagnosticsOutput, setDiagnosticsOutput] = useState("");
  const [diagnosticsError, setDiagnosticsError] = useState("");
  const [pruneLoading, setPruneLoading] = useState(false);
  const [prunePlan, setPrunePlan] = useState<RunnerReleasePrunePlan | null>(null);
  const [pruneMessage, setPruneMessage] = useState("");
  const [pruneError, setPruneError] = useState("");
  const [pruneConfirmation, setPruneConfirmation] = useState("");
  const [uninstallLoading, setUninstallLoading] = useState(false);
  const [uninstallPlan, setUninstallPlan] = useState<RunnerUninstallPlan | null>(null);
  const [uninstallMessage, setUninstallMessage] = useState("");
  const [uninstallError, setUninstallError] = useState("");
  const [uninstallConfirmation, setUninstallConfirmation] = useState("");
  const [stopConfirmation, setStopConfirmation] = useState("");

  const runner = status?.runner;
  const remote = resolveRemoteStatus(status);
  const serverId = status?.serverId || "";
  const canEnsureRunner = Boolean(status?.connected && serverId && !status.runner?.ready);
  const canStopRunner = Boolean(!diagnosticsOnly && status?.connected && serverId && runner && !isRunnerManuallyStopped(status));
  const canUpgradeRunner = Boolean(!diagnosticsOnly && status?.connected && serverId && runner && !isRunnerManuallyStopped(status));
  const canPrune = Boolean(!diagnosticsOnly && status?.connected && serverId);
  const canUninstall = Boolean(!diagnosticsOnly && status?.connected && serverId && runner);
  const deletableReleaseCount = Number(prunePlan?.deletableReleaseCount || 0);
  const uninstallTargetCount = Number(uninstallPlan?.targetCount || 0);
  const localTunnels = Array.isArray(runner?.localTunnels) ? runner.localTunnels : [];
  const activeLocalTunnelCount = localTunnels.filter((tunnel) => tunnel.active).length;
  const stopConfirmed = confirmationMatches(stopConfirmation, serverId);
  const pruneConfirmed = confirmationMatches(pruneConfirmation, serverId);
  const uninstallConfirmed = confirmationMatches(uninstallConfirmation, serverId);

  useEffect(() => {
    setStopConfirmation("");
    setPruneConfirmation("");
    setPrunePlan(null);
    setPruneMessage("");
    setPruneError("");
    setUninstallConfirmation("");
    setUninstallPlan(null);
    setUninstallMessage("");
    setUninstallError("");
  }, [serverId]);

  const loadListeningPorts = async () => {
    if (!status?.connected || !serverId || portsLoading) {
      return;
    }
    setPortsLoading(true);
    setPortsError("");
    try {
      const payload = await requestLocalApiJson("GET", `/api/v1/servers/${encodeURIComponent(serverId)}/listening-ports`, { cache: "no-store" });
      const output = String(payload?.data?.output || "").trim();
      setPortsOutput(output || "远端没有返回监听端口信息。");
    } catch (error) {
      setPortsError(normalizeFetchError(error));
    } finally {
      setPortsLoading(false);
    }
  };

  const stopRemoteService = async () => {
    if (!canStopRunner || !stopConfirmed || stopLoading) {
      return;
    }
    setStopLoading(true);
    setStopError("");
    setStopOutput("");
    try {
      const payload = await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(serverId)}/runner/stop`);
      const output = String(payload?.data?.output || "").trim();
      setStopOutput(output || "远程服务停止命令已执行。");
      setStopConfirmation("");
      await onRefreshStatus();
    } catch (error) {
      setStopError(normalizeFetchError(error));
    } finally {
      setStopLoading(false);
    }
  };

  const upgradeRunner = async () => {
    if (!canUpgradeRunner || upgradeLoading) {
      return;
    }
    setUpgradeLoading(true);
    setUpgradeError("");
    setUpgradeOutput("");
    try {
      const payload = await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(serverId)}/runner/upgrade`, {
        timeoutMs: 180_000,
      });
      setUpgradeOutput(String(payload?.data?.health?.ready?.message || "Runner upgrade completed."));
      await onRefreshStatus();
    } catch (error) {
      setUpgradeError(normalizeFetchError(error));
    } finally {
      setUpgradeLoading(false);
    }
  };

  const previewPrune = async () => {
    if (!canPrune || pruneLoading) {
      return;
    }
    setPruneLoading(true);
    setPruneError("");
    setPruneMessage("");
    try {
      const payload = await requestLocalApiJson(
        "POST",
        `/api/v1/servers/${encodeURIComponent(serverId)}/runner/releases/prune/preview`,
        { cache: "no-store" }
      );
      setPrunePlan((payload?.data || null) as RunnerReleasePrunePlan | null);
      setPruneConfirmation("");
    } catch (error) {
      setPruneError(normalizeFetchError(error));
    } finally {
      setPruneLoading(false);
    }
  };

  const runPrune = async () => {
    const planHash = String(prunePlan?.planHash || "");
    if (!canPrune || !planHash || !pruneConfirmed || pruneLoading || deletableReleaseCount <= 0) {
      return;
    }
    setPruneLoading(true);
    setPruneError("");
    setPruneMessage("");
    try {
      const payload = await requestLocalApiJson(
        "POST",
        `/api/v1/servers/${encodeURIComponent(serverId)}/runner/releases/prune/run`,
        { body: { confirmation: "prune-runner-releases", planHash }, timeoutMs: 180_000 }
      );
      setPrunePlan((payload?.data || prunePlan) as RunnerReleasePrunePlan);
      setPruneMessage("旧版本清理已完成。");
      setPruneConfirmation("");
      await onRefreshStatus();
    } catch (error) {
      setPruneError(normalizeFetchError(error));
    } finally {
      setPruneLoading(false);
    }
  };

  const previewUninstall = async () => {
    if (!canUninstall || uninstallLoading) {
      return;
    }
    setUninstallLoading(true);
    setUninstallError("");
    setUninstallMessage("");
    try {
      const payload = await requestLocalApiJson(
        "POST",
        `/api/v1/servers/${encodeURIComponent(serverId)}/runner/uninstall/preview`,
        { cache: "no-store" }
      );
      setUninstallPlan((payload?.data || null) as RunnerUninstallPlan | null);
      setUninstallConfirmation("");
    } catch (error) {
      setUninstallError(normalizeFetchError(error));
    } finally {
      setUninstallLoading(false);
    }
  };

  const runUninstall = async () => {
    const planHash = String(uninstallPlan?.planHash || "");
    if (!canUninstall || !planHash || !uninstallConfirmed || uninstallLoading || uninstallTargetCount <= 0) {
      return;
    }
    setUninstallLoading(true);
    setUninstallError("");
    setUninstallMessage("");
    try {
      const payload = await requestLocalApiJson(
        "POST",
        `/api/v1/servers/${encodeURIComponent(serverId)}/runner/uninstall/run`,
        { body: { confirmation: "uninstall-runner-control-plane", planHash }, timeoutMs: 180_000 }
      );
      setUninstallPlan((payload?.data || uninstallPlan) as RunnerUninstallPlan);
      setUninstallMessage("Runner 控制面已卸载，shared 数据已保留。");
      setUninstallConfirmation("");
      await onRefreshStatus();
    } catch (error) {
      setUninstallError(normalizeFetchError(error));
    } finally {
      setUninstallLoading(false);
    }
  };

  const loadOperatorDiagnostics = async () => {
    if (!status?.connected || !serverId || diagnosticsLoading) {
      return;
    }
    setDiagnosticsLoading(true);
    setDiagnosticsError("");
    try {
      const payload = await requestLocalApiJson(
        "GET",
        `/api/v1/servers/${encodeURIComponent(serverId)}/operator-diagnostics`,
        { cache: "no-store", timeoutMs: 60_000 }
      );
      setDiagnosticsOutput(compactJson(payload?.data || payload));
    } catch (error) {
      setDiagnosticsError(normalizeFetchError(error));
    } finally {
      setDiagnosticsLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-md border border-slate-200 bg-white p-2 shadow-xl shadow-slate-900/10",
        className
      )}
      data-testid="runner-repair-panel"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold text-slate-900">{remote.label}</p>
        {onClose ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="关闭远程状态详情"
            onClick={onClose}
            className="size-6 text-slate-400 hover:text-slate-700"
          >
            <X />
          </Button>
        ) : null}
      </div>
      <p className="mt-1 truncate text-[11px] text-slate-500">{remote.message}</p>
      <div className="mt-2 space-y-1">
        {remote.stages.map((stage) => (
          <div key={stage} className="flex items-center gap-2 text-[11px] text-slate-600">
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            <span>{stage}</span>
          </div>
        ))}
      </div>

      {status?.connected && serverId ? (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold text-slate-400">Runner Repair</p>
            {canEnsureRunner ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={ensureRunnerBusy}
                onClick={onEnsureRunner}
                className="h-6 px-2 text-[11px] text-slate-600"
              >
                <RefreshCw className={cn("mr-1 size-3", ensureRunnerBusy ? "animate-spin" : "")} />
                {runnerEnsureActionLabel(status, ensureRunnerBusy)}
              </Button>
            ) : null}
          </div>
          {runner ? (
            <>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded border border-slate-100 bg-slate-50 px-2 py-1">
                  <p className="text-[10px] text-slate-400">远端服务</p>
                  <p className="font-mono text-slate-700">{formatRunnerPort(runner.servicePort)}</p>
                </div>
                <div className="rounded border border-slate-100 bg-slate-50 px-2 py-1">
                  <p className="text-[10px] text-slate-400">本地隧道</p>
                  <p className="font-mono text-slate-700">{formatRunnerPort(runner.tunnelPort)}</p>
                </div>
              </div>
              <div className="mt-2 rounded border border-slate-100 bg-slate-50 px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] font-semibold text-slate-400">本地 SSH 隧道投影</p>
                  <span className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] text-slate-500">
                    {activeLocalTunnelCount}/{localTunnels.length} active
                  </span>
                </div>
                {localTunnels.length ? (
                  <div className="mt-1 space-y-1" data-testid="runner-local-tunnels">
                    {localTunnels.map((tunnel, index) => (
                      <div
                        key={`${tunnel.name || "tunnel"}-${index}`}
                        className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 text-[10px]"
                        data-runner-local-tunnel={tunnel.name || ""}
                      >
                        <div className="min-w-0">
                          <p className="truncate font-mono text-slate-700">{tunnel.name || "unnamed-tunnel"}</p>
                          <p className="truncate font-mono text-slate-500">
                            {formatTunnelEndpoint(tunnel.localHost, tunnel.localPort)} →{" "}
                            {formatTunnelEndpoint(tunnel.remoteHost, tunnel.remotePort)}
                          </p>
                        </div>
                        <span
                          className={cn(
                            "self-start rounded border px-1.5 py-0.5 font-mono",
                            tunnel.active
                              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                              : "border-slate-200 bg-white text-slate-500"
                          )}
                        >
                          {tunnel.active ? "active" : "closed"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-1 text-[11px] text-slate-400">尚无本地 tunnel snapshot；刷新 runner 状态后再确认。</p>
                )}
              </div>
              {!diagnosticsOnly ? (
                <>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!canUpgradeRunner || upgradeLoading}
                      onClick={upgradeRunner}
                      className="h-7 px-2 text-[11px]"
                    >
                      <RefreshCw className={cn("mr-1 size-3", upgradeLoading ? "animate-spin" : "")} />
                      {upgradeLoading ? "升级中" : "升级 Runner"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!canStopRunner || !stopConfirmed || stopLoading}
                      onClick={stopRemoteService}
                      className="h-7 px-2 text-[11px] text-red-700 hover:text-red-700"
                    >
                      <Square className={cn("mr-1 size-3", stopLoading ? "animate-pulse" : "")} />
                      {stopLoading ? "停止中" : "停止 Runner"}
                    </Button>
                  </div>
                  {upgradeError ? <p className="mt-1 text-[11px] text-red-600">{upgradeError}</p> : null}
                  {upgradeOutput ? <p className="mt-1 text-[10px] text-slate-500">{upgradeOutput}</p> : null}
                  {canStopRunner ? (
                    <DestructiveConfirmation
                      action="停止 Runner"
                      disabled={stopLoading}
                      target={serverId}
                      value={stopConfirmation}
                      onChange={setStopConfirmation}
                    />
                  ) : null}
                  {stopError ? <p className="mt-1 text-[11px] text-red-600">{stopError}</p> : null}
                  {stopOutput ? <p className="mt-1 whitespace-pre-wrap text-[10px] text-slate-500">{stopOutput}</p> : null}
                </>
              ) : null}
            </>
          ) : (
            <p className="mt-1 text-[11px] text-slate-500">Runner 状态尚未返回，可先准备远程服务。</p>
          )}
        </div>
      ) : null}

      {!diagnosticsOnly ? (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold text-slate-400">旧版本清理</p>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!canPrune || pruneLoading}
                onClick={previewPrune}
                className="h-6 px-2 text-[11px] text-slate-600"
              >
                <RefreshCw className={cn("mr-1 size-3", pruneLoading ? "animate-spin" : "")} />
                预览
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={
                  !canPrune || pruneLoading || deletableReleaseCount <= 0 || !prunePlan?.planHash || !pruneConfirmed
                }
                onClick={runPrune}
                className="h-6 px-2 text-[11px] text-red-700 hover:text-red-700"
              >
                <Trash2 className="mr-1 size-3" />
                清理
              </Button>
            </div>
          </div>
          {prunePlan ? (
            <p className="mt-1 text-[11px] text-slate-500">
              可清理 {deletableReleaseCount} 个版本，约 {formatBytes(prunePlan.deletableBytes)}。
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-slate-400">先预览；保留 current、previous、active run 引用版本。</p>
          )}
          {prunePlan?.planHash && deletableReleaseCount > 0 ? (
            <DestructiveConfirmation
              action="清理旧版本"
              disabled={pruneLoading}
              target={serverId}
              value={pruneConfirmation}
              onChange={setPruneConfirmation}
            />
          ) : null}
          {pruneError ? <p className="mt-1 text-[11px] text-red-600">{pruneError}</p> : null}
          {pruneMessage ? <p className="mt-1 text-[11px] text-emerald-700">{pruneMessage}</p> : null}
        </div>
      ) : null}

      {!diagnosticsOnly ? (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold text-slate-400">控制面卸载</p>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!canUninstall || uninstallLoading}
                onClick={previewUninstall}
                className="h-6 px-2 text-[11px] text-slate-600"
              >
                <RefreshCw className={cn("mr-1 size-3", uninstallLoading ? "animate-spin" : "")} />
                预览
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={
                  !canUninstall ||
                  uninstallLoading ||
                  uninstallTargetCount <= 0 ||
                  !uninstallPlan?.planHash ||
                  !uninstallConfirmed
                }
                onClick={runUninstall}
                className="h-6 px-2 text-[11px] text-red-700 hover:text-red-700"
              >
                <Trash2 className="mr-1 size-3" />
                卸载
              </Button>
            </div>
          </div>
          {uninstallPlan ? (
            <p className="mt-1 text-[11px] text-slate-500">
              将移除 {uninstallTargetCount} 个控制面目标；保留 {uninstallPlan.preservedPaths?.length || 0} 个 shared 数据边界。
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-slate-400">先预览；仅卸载 runner 控制面，不删除结果、上传、数据库和 workdir。</p>
          )}
          {uninstallPlan?.blockReasons?.length ? (
            <p className="mt-1 text-[11px] text-amber-700">{uninstallPlan.blockReasons.join(" · ")}</p>
          ) : null}
          {uninstallPlan?.planHash && uninstallTargetCount > 0 ? (
            <DestructiveConfirmation
              action="卸载控制面"
              disabled={uninstallLoading}
              target={serverId}
              value={uninstallConfirmation}
              onChange={setUninstallConfirmation}
            />
          ) : null}
          {uninstallError ? <p className="mt-1 text-[11px] text-red-600">{uninstallError}</p> : null}
          {uninstallMessage ? <p className="mt-1 text-[11px] text-emerald-700">{uninstallMessage}</p> : null}
        </div>
      ) : null}

      <div className="mt-2 border-t border-slate-100 pt-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold text-slate-400">诊断</p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!status?.connected || diagnosticsLoading}
            onClick={loadOperatorDiagnostics}
            className="h-6 px-2 text-[11px] text-slate-600"
          >
            <Activity className={cn("mr-1 size-3", diagnosticsLoading ? "animate-pulse" : "")} />
            {diagnosticsLoading ? "读取中" : "Operator"}
          </Button>
        </div>
        {diagnosticsError ? <p className="mt-1 text-[11px] text-red-600">{diagnosticsError}</p> : null}
        {diagnosticsOutput ? (
          <pre className="mt-2 max-h-36 overflow-auto rounded border border-slate-100 bg-slate-950 px-2 py-2 font-mono text-[10px] leading-relaxed text-slate-100">
            {diagnosticsOutput}
          </pre>
        ) : null}
      </div>

      <div className="mt-2 border-t border-slate-100 pt-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-semibold text-slate-400">远端监听端口</p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!status?.connected || !serverId || portsLoading}
            onClick={loadListeningPorts}
            className="h-6 px-2 text-[11px] text-slate-600"
          >
            <RefreshCw className={cn("mr-1 size-3", portsLoading ? "animate-spin" : "")} />
            {portsLoading ? "读取中" : "刷新"}
          </Button>
        </div>
        {portsError ? <p className="mt-1 text-[11px] text-red-600">{portsError}</p> : null}
        {portsOutput ? (
          <pre className="mt-2 max-h-36 overflow-auto rounded border border-slate-100 bg-slate-950 px-2 py-2 font-mono text-[10px] leading-relaxed text-slate-100">
            {portsOutput}
          </pre>
        ) : (
          <p className="mt-1 text-[11px] text-slate-400">点击刷新查看远端正在监听的端口和进程。</p>
        )}
      </div>
    </div>
  );
}
