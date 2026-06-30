"use client";

import Link from "next/link";
import { useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import { CircleHelp, Clock3, Ellipsis, GripHorizontal, RefreshCw, Server, Square, Workflow, X } from "lucide-react";

import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import {
  isRunnerManuallyStopped,
  isRunnerPreparing,
  isRunnerRepairRequired,
  normalizeFetchError,
  runnerEnsureActionLabel,
  runnerSidebarSubcopy,
  type SSHFormState,
  type SSHStatus,
} from "./ssh-shell-model";
import { ToolPrepareTaskBar } from "./tool-prepare-task-bar";

function resolveRemoteStatus(status: SSHStatus | null) {
  if (status?.connecting || status?.auto_connect_in_progress) {
    const target = status.host ? `SSH: ${status.host}` : "SSH";
    return {
      label: "SSH 连接中",
      message: target,
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["正在建立 SSH 连接", "等待认证结果", "连接成功后准备远程服务"],
    };
  }
  if (!status?.connected) {
    return {
      label: "未连接",
      message: "",
      dotClass: "bg-slate-300",
      toneClass: "text-slate-500",
      stages: ["SSH 未连接", "远程服务未启动"],
    };
  }
  const target = status.host ? `SSH: ${status.host}` : "SSH";
  if (!status.runner) {
    return {
      label: "SSH 已连接",
      message: "正在检查远程服务...",
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "正在检查远程服务", "正在打开安全通道"],
    };
  }
  if (status.runner.ready) {
    return {
      label: "已连接",
      message: target,
      dotClass: "bg-emerald-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "远程服务已就绪", "安全通道已打开", "健康检查通过"],
    };
  }
  if (isRunnerManuallyStopped(status)) {
    return {
      label: "远程服务已停止",
      message: status.runner.message || "远程服务已手动停止",
      dotClass: "bg-slate-400",
      toneClass: "text-slate-700",
      stages: ["SSH 已连接", "远程服务已手动停止", "等待手动启动"],
    };
  }
  if (status.runner.state === "recovering") {
    return {
      label: "SSH 已连接",
      message: status.runner.message || "远程服务正在恢复...",
      dotClass: "animate-pulse bg-blue-500",
      toneClass: "text-blue-700",
      stages: ["SSH 已连接", "远程服务正在恢复", "正在重建安全通道"],
    };
  }
  const failed = isRunnerRepairRequired(status);
  return {
    label: failed ? "远程服务需要修复" : "SSH 已连接",
    message: status.runner.message || "",
    dotClass: failed ? "bg-amber-500" : "animate-pulse bg-blue-500",
    toneClass: failed ? "text-amber-700" : "text-blue-700",
    stages: failed
      ? ["SSH 已连接", "远程服务需要修复", status.runner.reasonCode || "请查看详情"]
      : ["SSH 已连接", "正在检查远程服务", "正在同步环境", "正在启动远程服务", "正在打开安全通道"],
  };
}

function formatRunnerPort(value: number | undefined): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? String(value) : "未记录";
}

function formatConnectedHost(status: SSHStatus | null): string {
  if (!status?.connected) {
    return "";
  }
  const rawHost = status.host || "";
  const host = rawHost.includes("@") ? rawHost.split("@").at(-1) || rawHost : rawHost;
  const port = typeof status.port === "number" && status.port !== 22 ? `:${status.port}` : "";
  return host ? `${host}${port}` : "已连接";
}

export function RemoteStatusBar({
  status,
  connectBusy,
  ensureRunnerBusy,
  onRefreshStatus,
  onEnsureRunner,
}: {
  status: SSHStatus | null;
  connectBusy: boolean;
  ensureRunnerBusy: boolean;
  onRefreshStatus: () => Promise<SSHStatus | null>;
  onEnsureRunner: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [portsLoading, setPortsLoading] = useState(false);
  const [portsOutput, setPortsOutput] = useState("");
  const [portsError, setPortsError] = useState("");
  const [stopLoading, setStopLoading] = useState(false);
  const [stopOutput, setStopOutput] = useState("");
  const [stopError, setStopError] = useState("");
  const remote = resolveRemoteStatus(status);
  const connectedHost = formatConnectedHost(status);
  const runner = status?.runner;
  const connectedTone = Boolean(status?.connected && remote.toneClass === "text-blue-700");
  const remotePreparing = Boolean(status?.connected && (!status.runner || isRunnerPreparing(status)));
  const remoteBusy = connectBusy || ensureRunnerBusy || remotePreparing;
  const canEnsureRunner = Boolean(status?.connected && !status.runner?.ready);
  const canStopRunner = Boolean(status?.connected);
  const loadListeningPorts = async () => {
    if (!status?.connected || portsLoading) {
      return;
    }
    setPortsLoading(true);
    setPortsError("");
    try {
      const payload = await requestLocalApiJson("GET", "/api/v1/ssh/listening-ports", { cache: "no-store" });
      const output = String(payload?.data?.output || "").trim();
      setPortsOutput(output || "远端没有返回监听端口信息。");
    } catch (error) {
      setPortsError(normalizeFetchError(error));
    } finally {
      setPortsLoading(false);
    }
  };
  const stopRemoteService = async () => {
    if (!status?.connected || stopLoading) {
      return;
    }
    setStopLoading(true);
    setStopError("");
    setStopOutput("");
    try {
      const payload = await requestLocalApiJson("POST", "/api/v1/ssh/remote-service/stop");
      const output = String(payload?.data?.output || "").trim();
      setStopOutput(output || "远程服务停止命令已执行。");
      await onRefreshStatus();
    } catch (error) {
      setStopError(normalizeFetchError(error));
    } finally {
      setStopLoading(false);
    }
  };

  return (
    <div className="relative border-t border-slate-200 bg-[#f7f7f5] text-slate-700">
      {remoteBusy ? (
        <div className="absolute inset-x-0 -top-px h-0.5 overflow-hidden bg-blue-100">
          <div className="remote-progress-bar h-full w-1/4 bg-blue-500/70" />
        </div>
      ) : null}
      {expanded ? (
        <div className="absolute bottom-full left-2 z-30 mb-1 w-[340px] rounded-md border border-slate-200 bg-white p-2 shadow-xl shadow-slate-900/10">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] font-semibold text-slate-900">{remote.label}</p>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="关闭远程状态详情"
              onClick={() => setExpanded(false)}
              className="size-6 text-slate-400 hover:text-slate-700"
            >
              <X />
            </Button>
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
          {runner ? (
            <div className="mt-2 border-t border-slate-100 pt-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold text-slate-400">远端服务端口</p>
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
              <div className="mt-2 flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!canStopRunner || stopLoading}
                  onClick={stopRemoteService}
                  className="h-7 px-2 text-[11px] text-red-700 hover:text-red-700"
                >
                  <Square className={cn("mr-1 size-3", stopLoading ? "animate-pulse" : "")} />
                  {stopLoading ? "停止中" : "停止远程服务"}
                </Button>
              </div>
              {stopError ? <p className="mt-1 text-[11px] text-red-600">{stopError}</p> : null}
              {stopOutput ? <p className="mt-1 whitespace-pre-wrap text-[10px] text-slate-500">{stopOutput}</p> : null}
              <div className="mt-1 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded border border-slate-100 bg-slate-50 px-2 py-1">
                  <p className="text-[10px] text-slate-400">远端服务</p>
                  <p className="font-mono text-slate-700">{formatRunnerPort(runner.servicePort)}</p>
                </div>
                <div className="rounded border border-slate-100 bg-slate-50 px-2 py-1">
                  <p className="text-[10px] text-slate-400">本地隧道</p>
                  <p className="font-mono text-slate-700">{formatRunnerPort(runner.tunnelPort)}</p>
                </div>
              </div>
            </div>
          ) : null}
          <div className="mt-2 border-t border-slate-100 pt-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] font-semibold text-slate-400">远端监听端口</p>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!status?.connected || portsLoading}
                onClick={loadListeningPorts}
                className="h-6 px-2 text-[11px] text-slate-600"
              >
                <RefreshCw className={cn("mr-1 size-3", portsLoading ? "animate-spin" : "")} />
                {portsLoading ? "读取中" : "刷新"}
              </Button>
            </div>
            {portsError ? <p className="mt-1 text-[11px] text-red-600">{portsError}</p> : null}
            {portsOutput ? (
              <pre className="mt-2 max-h-48 overflow-auto rounded border border-slate-100 bg-slate-950 px-2 py-2 font-mono text-[10px] leading-relaxed text-slate-100">
                {portsOutput}
              </pre>
            ) : (
              <p className="mt-1 text-[11px] text-slate-400">点击刷新查看远端正在监听的端口和进程。</p>
            )}
          </div>
        </div>
      ) : null}
      <div className="flex h-6 items-center gap-0 px-1 text-sm leading-none">
        <Button
          type="button"
          variant="ghost"
          onClick={() => setExpanded((value) => !value)}
          className={cn(
            "h-full min-w-0 justify-start rounded-none px-2 text-left text-sm hover:bg-slate-200/70",
            remote.toneClass,
            connectedTone ? "bg-blue-100 hover:bg-blue-200/70" : ""
          )}
        >
          <span className="truncate font-medium">{connectedHost || "未连接"}</span>
        </Button>
        <ToolPrepareTaskBar />
      </div>
    </div>
  );
}

type SshSidebarProps = {
  pathname: string;
  status: SSHStatus | null;
  connectBusy: boolean;
  disconnectBusy: boolean;
  ensureRunnerBusy: boolean;
  onOpenConnect: () => void;
  onDisconnect: () => void;
  onEnsureRunner: () => void;
};

export function SshSidebar({
  pathname,
  status,
  connectBusy,
  disconnectBusy,
  ensureRunnerBusy,
  onOpenConnect,
  onDisconnect,
  onEnsureRunner,
}: SshSidebarProps) {
  const workflowsActive = pathname.startsWith("/workflows");
  const resultsActive = pathname.startsWith("/workflows/results");
  const workflowCatalogActive = workflowsActive && !resultsActive;
  const remotePreparing = Boolean(status?.connected && (!status.runner || isRunnerPreparing(status)));
  const connecting = connectBusy || Boolean(status?.connecting || status?.auto_connect_in_progress);
  const canRepairRunner = Boolean(status?.connected && !status.runner?.ready);
  const runnerReady = Boolean(status?.connected && status.runner?.ready);
  const runnerFailed = isRunnerRepairRequired(status);
  const runnerStopped = isRunnerManuallyStopped(status);
  const connectionLabel = connecting
    ? "SSH 连接中"
    : runnerReady
      ? "已连接"
      : status?.connected
        ? "SSH 已连接"
        : "连接";
  const connectionIconBusy = connecting || remotePreparing;
  const connectionIconClass = runnerFailed
    ? "text-amber-600"
    : runnerStopped
      ? "text-slate-500"
      : status?.connected
        ? "text-blue-600"
        : "text-zinc-500";
  const connectionActionDisabled = Boolean(connecting || status?.connected);

  return (
    <aside className="overflow-hidden border-b border-slate-200 bg-[#f7f7f5] md:border-b-0 md:border-r md:border-slate-200">
      <div className="flex h-full flex-col gap-2 p-2 md:gap-3 md:p-3">
        <div className="rounded-xl px-0 py-1 md:px-2">
          <div
            className={cn(
              "group flex items-center overflow-hidden rounded-lg",
              status?.connected && !runnerReady ? "h-11" : "h-8",
              status?.connected ? "bg-transparent" : "hover:bg-slate-100/90"
            )}
          >
            <Button
              type="button"
              variant="ghost"
              aria-disabled={connectionActionDisabled}
              onClick={() => {
                if (!connectionActionDisabled) {
                  onOpenConnect();
                }
              }}
              className={cn(
                "h-full min-w-0 flex-1 justify-center rounded-none bg-transparent px-0 text-left hover:bg-transparent md:justify-start",
                connectionActionDisabled ? "cursor-default" : ""
              )}
            >
              {connectionIconBusy ? (
                <RefreshCw strokeWidth={1.5} className={cn("size-4 md:mr-2", connectionIconClass, "animate-spin")} />
              ) : (
                <Server
                  strokeWidth={1.5}
                  className={cn("size-4 md:mr-2", connectionIconClass)}
                />
              )}
              <div className="hidden min-w-0 flex-1 md:block">
                <p className="truncate text-sm font-medium text-slate-900">{connectionLabel}</p>
                {status?.connected && !runnerReady ? (
                  <p className={cn("truncate text-[11px]", runnerFailed ? "text-amber-700" : "text-slate-500")}>
                    {runnerSidebarSubcopy(status)}
                  </p>
                ) : null}
              </div>
            </Button>
            {status?.connected ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className={cn(
                      "hidden size-8 appearance-none rounded-none border-0 bg-transparent p-1 text-slate-400 md:inline-flex",
                      "opacity-0 shadow-none outline-none transition hover:bg-slate-100 hover:text-slate-700",
                      "group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                    )}
                    aria-label="连接菜单"
                  >
                    <Ellipsis />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {canRepairRunner ? (
                    <DropdownMenuItem onSelect={onEnsureRunner}>
                      {runnerEnsureActionLabel(status, ensureRunnerBusy)}
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem destructive onSelect={onDisconnect}>
                    {disconnectBusy ? "断开中..." : "断开连接"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>

        <div className="space-y-1 px-0 md:px-2">
           <Button
            asChild
            variant="ghost"
            className={cn(
              "h-8 w-full justify-center px-0 md:justify-start",
              workflowCatalogActive ? "bg-slate-200/90 text-slate-950" : "text-slate-700 hover:bg-slate-200/60"
            )}
          >
            <Link href="/workflows" aria-current={workflowCatalogActive ? "page" : undefined}>
              <span className="flex w-8 justify-center md:w-6">
                <Workflow
                  strokeWidth={1.5}
                  className={cn("size-4", workflowCatalogActive ? "text-zinc-900" : "text-zinc-500")}
                />
              </span>
              <span className="sr-only md:not-sr-only">流程和数据库</span>
            </Link>
          </Button>
          <Button
            asChild
            variant="ghost"
            className={cn(
              "h-8 w-full justify-center px-0 md:justify-start",
              resultsActive ? "bg-slate-200/90 text-slate-950" : "text-slate-700 hover:bg-slate-200/60"
            )}
          >
            <Link href="/workflows/results" aria-current={resultsActive ? "page" : undefined}>
              <span className="flex w-8 justify-center md:w-6">
                <Clock3
                  strokeWidth={1.5}
                  className={cn("size-4", resultsActive ? "text-zinc-900" : "text-zinc-500")}
                />
              </span>
              <span className="sr-only md:not-sr-only">运行记录</span>
            </Link>
          </Button>
        </div>

      </div>
    </aside>
  );
}

type SshTerminalPanelProps = {
  status: SSHStatus | null;
  terminalMessage: string;
  terminalHeight: number;
  terminalGridLabel: string;
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onClose: () => void;
  surfaceRef: RefObject<HTMLDivElement | null>;
  viewportRef: RefObject<HTMLDivElement | null>;
};

export function SshTerminalPanel({
  status,
  terminalMessage,
  terminalHeight,
  terminalGridLabel,
  onResizeStart,
  onClose,
  surfaceRef,
  viewportRef,
}: SshTerminalPanelProps) {
  return (
    <>
      <div className="relative h-px bg-slate-200">
        <Button
          type="button"
          variant="ghost"
          aria-label="调整终端高度"
          onPointerDown={onResizeStart}
          className="absolute inset-x-0 -top-2 h-4 w-full cursor-row-resize rounded-none bg-transparent p-0 text-slate-300 shadow-none hover:bg-transparent hover:text-slate-500"
        >
          <span className="bg-white px-2">
            <GripHorizontal />
          </span>
        </Button>
      </div>

      <section
        className="border-t border-slate-200 bg-white/95"
        style={{ height: `${terminalHeight}px` }}
        aria-label="远程终端 · 当前服务器"
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-slate-600">终端</p>
              <p className="truncate text-[11px] text-slate-400">
                {status?.connected ? `${status.user}@${status.host}:${status.port}` : terminalMessage || "SSH 已断开，终端会话已结束"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] font-mono text-slate-400">{terminalGridLabel}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="关闭终端"
                onClick={onClose}
                className="size-7 text-slate-400 hover:text-slate-700"
              >
                <X />
              </Button>
            </div>
          </div>

          <div ref={surfaceRef} className="relative flex-1 overflow-hidden bg-white">
            <div ref={viewportRef} className="ssh-terminal h-full w-full" />
          </div>
        </div>
      </section>
    </>
  );
}

type SshConnectDialogProps = {
  open: boolean;
  status: SSHStatus | null;
  form: SSHFormState;
  formError: string;
  connectBusy: boolean;
  connectDisabled: boolean;
  onOpenChange: (open: boolean) => void;
  onFieldChange: <K extends keyof SSHFormState>(key: K, value: SSHFormState[K]) => void;
  onSelectKeyFile: () => void;
  onCancel: () => void;
  onSubmit: () => void;
};

export function SshConnectDialog({
  open,
  status,
  form,
  formError,
  connectBusy,
  connectDisabled,
  onOpenChange,
  onFieldChange,
  onSelectKeyFile,
  onCancel,
  onSubmit,
}: SshConnectDialogProps) {
  const autoConnectAllowed = form.remember_auth;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen);
        if (!nextOpen && !status?.connected) {
          onCancel();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>SSH 连接</DialogTitle>
          <DialogDescription>先选择认证方式，再填写连接所需的最少信息。我们会记住本次成功的连接配置，是否在应用启动时自动连接由你明确控制。</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {formError ? (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="ssh-auth-mode">认证方式</Label>
            <Select
              value={form.auth_mode}
              onValueChange={(value) => onFieldChange("auth_mode", value as SSHFormState["auth_mode"])}
            >
              <SelectTrigger id="ssh-auth-mode">
                <SelectValue placeholder="选择认证方式" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="password_ref">密码</SelectItem>
                  <SelectItem value="key_file">私钥文件</SelectItem>
                  <SelectItem value="ssh_config">OpenSSH 配置</SelectItem>
                  <SelectItem value="agent">系统 SSH Agent</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          {form.auth_mode === "ssh_config" ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ssh-host-alias">Host Alias</Label>
                <Input
                  id="ssh-host-alias"
                  value={form.ssh_host_alias}
                  onChange={(event) => onFieldChange("ssh_host_alias", event.target.value)}
                  placeholder="例如：prod-box"
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <CircleHelp className="h-4 w-4" />
                <span>从 `~/.ssh/config` 读取 Host、用户、端口和 IdentityFile。适合已经在 OpenSSH 中维护好的连接。</span>
              </div>
            </>
          ) : form.auth_mode === "agent" ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ssh-host">主机地址</Label>
                <Input id="ssh-host" value={form.host} onChange={(event) => onFieldChange("host", event.target.value)} />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="ssh-port">端口</Label>
                  <Input id="ssh-port" value={form.port} onChange={(event) => onFieldChange("port", event.target.value)} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ssh-user">用户名</Label>
                  <Input id="ssh-user" value={form.user} onChange={(event) => onFieldChange("user", event.target.value)} />
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs text-slate-500">
                <CircleHelp className="h-4 w-4" />
                <span>使用本机 ssh-agent 或系统代理中的身份。连接前请先确认身份已经加载到 agent 中。</span>
              </div>
            </>
          ) : (
            <>
              <div className="grid gap-2">
                <Label htmlFor="ssh-host">主机地址</Label>
                <Input id="ssh-host" value={form.host} onChange={(event) => onFieldChange("host", event.target.value)} />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label htmlFor="ssh-port">端口</Label>
                  <Input id="ssh-port" value={form.port} onChange={(event) => onFieldChange("port", event.target.value)} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ssh-user">用户名</Label>
                  <Input id="ssh-user" value={form.user} onChange={(event) => onFieldChange("user", event.target.value)} />
                </div>
              </div>
            </>
          )}

          {form.auth_mode === "password_ref" ? (
            <div className="grid gap-2">
              <Label htmlFor="ssh-password">密码</Label>
              <Input
                id="ssh-password"
                type="password"
                value={form.password}
                onChange={(event) => onFieldChange("password", event.target.value)}
              />
            </div>
          ) : null}

          {form.auth_mode === "key_file" ? (
            <div className="grid gap-2">
              <Label htmlFor="ssh-key-file">密钥文件</Label>
              <div className="flex gap-2">
                <Input
                  id="ssh-key-file"
                  value={form.identity_ref}
                  readOnly
                  placeholder="请选择 SSH 密钥文件"
                  className="flex-1 cursor-default bg-slate-50"
                />
                <Button type="button" variant="outline" onClick={onSelectKeyFile}>
                  选择文件
                </Button>
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <CircleHelp className="h-4 w-4" />
                <span>直接指定本地私钥文件。适合未使用 ssh-agent 或 OpenSSH 配置的情况。</span>
              </div>
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <Checkbox
              checked={form.remember_auth}
              onCheckedChange={(checked) => onFieldChange("remember_auth", checked === true)}
            />
            <span>记住此认证方式</span>
          </label>

          <label className={autoConnectAllowed ? "flex items-center gap-2 text-sm text-slate-700" : "flex items-center gap-2 text-sm text-slate-400"}>
            <Checkbox
              checked={autoConnectAllowed && form.auto_connect_on_startup}
              disabled={!autoConnectAllowed}
              onCheckedChange={(checked) => onFieldChange("auto_connect_on_startup", checked === true)}
            />
            <span>应用启动时自动连接到此主机</span>
          </label>

          {!form.remember_auth ? (
            <p className="text-xs text-slate-500">未记住认证方式时，不会在下次启动时自动连接。</p>
          ) : null}
        </div>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button onClick={onSubmit} disabled={connectDisabled}>
            {connectBusy ? "连接中..." : "连接"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
