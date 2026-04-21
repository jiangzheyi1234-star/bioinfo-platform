"use client";

import Link from "next/link";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import { CircleHelp, Ellipsis, GripHorizontal, Link2, Server, Settings2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { SSHFormState, SSHStatus } from "./ssh-shell-model";

type SshSidebarProps = {
  pathname: string;
  status: SSHStatus | null;
  disconnectBusy: boolean;
  onOpenConnect: () => void;
  onDisconnect: () => void;
};

const NAV_ITEMS = [
  { href: "/servers", label: "Servers", icon: Server, match: (pathname: string) => pathname.startsWith("/servers") },
] as const;

export function SshSidebar({ pathname, status, disconnectBusy, onOpenConnect, onDisconnect }: SshSidebarProps) {
  const settingsActive = pathname.startsWith("/settings");

  return (
    <aside className="border-b border-slate-200 bg-[#f7f7f5] md:border-b-0 md:border-r md:border-slate-200">
      <div className="flex h-full flex-col gap-3 p-3">
        <div className="rounded-xl px-2 py-2">
          <div className="flex items-start gap-2">
            <button
              type="button"
              disabled={Boolean(status?.connected)}
              onClick={() => {
                if (!status?.connected) {
                  onOpenConnect();
                }
              }}
              className={cn(
                "flex min-w-0 flex-1 items-start gap-2 rounded-lg text-left transition",
                status?.connected ? "cursor-default" : "hover:bg-slate-100/90"
              )}
            >
              <Link2 className={cn("mt-0.5 h-4 w-4 shrink-0", status?.connected ? "text-blue-600" : "text-slate-400")} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-900">Connection</p>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {status?.connected ? `${status.user}@${status.host}:${status.port}` : "未连接远端服务器"}
                </p>
              </div>
            </button>
            {status?.connected ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="appearance-none rounded-lg border-0 bg-transparent p-1 text-slate-400 shadow-none outline-none transition hover:bg-slate-100 hover:text-slate-700"
                    aria-label="连接菜单"
                  >
                    <Ellipsis className="h-4 w-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem destructive onSelect={onDisconnect}>
                    {disconnectBusy ? "断开中..." : "断开连接"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        </div>

        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition",
                  active ? "bg-slate-200/90 text-slate-950" : "text-slate-700 hover:bg-slate-200/60"
                )}
              >
                <Icon className="h-4 w-4 shrink-0 text-slate-500" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto pt-3">
          <Link
            href="/settings"
            aria-current={settingsActive ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition",
              settingsActive ? "bg-slate-200/90 text-slate-950" : "text-slate-700 hover:bg-slate-200/60"
            )}
          >
            <Settings2 className="h-4 w-4 shrink-0 text-slate-500" />
            <span>Settings</span>
          </Link>
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
        <button
          type="button"
          aria-label="调整终端高度"
          onPointerDown={onResizeStart}
          className="absolute inset-x-0 -top-2 inline-flex h-4 w-full appearance-none cursor-row-resize items-center justify-center border-0 bg-transparent text-slate-300 shadow-none outline-none transition hover:text-slate-500"
        >
          <span className="bg-white px-2">
            <GripHorizontal className="h-4 w-4" />
          </span>
        </button>
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
              <button
                type="button"
                aria-label="关闭终端"
                onClick={onClose}
                className="appearance-none rounded-lg border-0 bg-transparent p-1 text-slate-400 shadow-none outline-none transition hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="h-4 w-4" />
              </button>
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
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{formError}</div>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="ssh-auth-mode">认证方式</Label>
            <select
              id="ssh-auth-mode"
              value={form.auth_mode}
              onChange={(event) => onFieldChange("auth_mode", event.target.value as SSHFormState["auth_mode"])}
              className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900"
            >
              <option value="password_ref">密码</option>
              <option value="key_file">私钥文件</option>
              <option value="ssh_config">OpenSSH 配置</option>
              <option value="agent">系统 SSH Agent</option>
            </select>
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
            <input
              type="checkbox"
              checked={form.remember_auth}
              onChange={(event) => onFieldChange("remember_auth", event.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span>记住此认证方式</span>
          </label>

          <label className={form.remember_auth ? "flex items-center gap-2 text-sm text-slate-700" : "flex items-center gap-2 text-sm text-slate-400"}>
            <input
              type="checkbox"
              checked={form.auto_connect_on_startup}
              disabled={!form.remember_auth}
              onChange={(event) => onFieldChange("auto_connect_on_startup", event.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
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
