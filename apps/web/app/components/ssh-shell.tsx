"use client";

import { createContext, useContext, useRef, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Terminal as TerminalIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { type SshShellContextValue, toForm } from "./ssh-shell-model";
import { useSshConnection } from "./ssh-shell-connection";
import { useSshTerminal } from "./ssh-shell-terminal";
import { SshConnectDialog, SshSidebar, SshTerminalPanel } from "./ssh-shell-ui";

const SshShellContext = createContext<SshShellContextValue | null>(null);

type WorkspaceTab = {
  id: string;
  href: string;
  title: string;
  active?: boolean;
};

const ROUTE_TABS = {
  "/servers": { href: "/servers", title: "Servers" },
  "/settings": { href: "/settings", title: "Settings" },
} satisfies Record<string, { href: string; title: string }>;

function resolveWorkspaceTabs(pathname: string): WorkspaceTab[] {
  const segments = pathname.split("/").filter(Boolean);
  const topLevel = `/${segments[0] ?? ""}`;
  const config = ROUTE_TABS[topLevel as keyof typeof ROUTE_TABS] ?? ROUTE_TABS["/servers"];
  return [{ id: config.href, ...config, active: pathname === config.href || (config.href === "/servers" && pathname.startsWith("/servers/")) }];
}

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const terminalSurfaceRef = useRef<HTMLDivElement | null>(null);
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);
  const activeTabs = resolveWorkspaceTabs(pathname);

  const connection = useSshConnection();
  const terminal = useSshTerminal({
    status: connection.status,
    refreshStatus: connection.refreshStatus,
    surfaceRef: terminalSurfaceRef,
    viewportRef: terminalViewportRef,
  });

  const openConnectDialog = () => {
    connection.contextValue.clearFormError();
    connection.contextValue.setForm(toForm(connection.status));
    connection.contextValue.setDialogOpen(true);
  };
  const toggleTerminal = () =>
    void (terminal.terminalOpen ? terminal.closeTerminal() : terminal.openTerminal());

  return (
    <SshShellContext.Provider value={connection.contextValue}>
      <div className="min-h-screen bg-[#fbfbfa] text-slate-900">
        <div className="grid min-h-screen grid-cols-1 md:grid-cols-[228px_minmax(0,1fr)]">
          <SshSidebar
            pathname={pathname}
            status={connection.status}
            disconnectBusy={connection.disconnectBusy}
            onOpenConnect={openConnectDialog}
            onDisconnect={() => void connection.contextValue.submitDisconnect()}
          />

          <main className="min-h-screen min-w-0 bg-white p-0">
            <div className="relative flex h-full min-h-screen min-w-0 flex-col overflow-hidden bg-white">
              <div className="flex min-h-11 items-end border-b border-slate-200 bg-[#f7f7f5]/80 px-4">
                <div className="no-scrollbar flex min-w-0 flex-1 items-end overflow-x-auto pt-2">
                  {activeTabs.map((tab) => (
                    <Link
                      key={tab.id}
                      href={tab.href}
                      className={cn(
                        "relative -mb-px flex h-9 shrink-0 items-center rounded-t-xl border border-b-0 px-4 text-[13px] transition",
                        tab.active
                          ? "border-slate-300 bg-white text-slate-900"
                          : "border-transparent bg-transparent text-slate-500 hover:bg-white/60 hover:text-slate-700"
                      )}
                    >
                      <span>{tab.title}</span>
                    </Link>
                  ))}
                </div>
                <div className="flex items-center pb-1">
                  <button
                    type="button"
                    aria-label="远程终端"
                    title={connection.status?.connected ? "远程终端" : "请先连接远端服务器"}
                    disabled={!connection.status?.connected}
                    onClick={toggleTerminal}
                    className={cn(
                      "inline-flex h-9 w-9 appearance-none items-center justify-center rounded-lg border border-transparent text-slate-500 shadow-none outline-none transition",
                      connection.status?.connected
                        ? terminal.terminalOpen
                          ? "bg-slate-100 text-slate-900"
                          : "bg-transparent hover:bg-slate-100 hover:text-slate-900"
                        : "cursor-not-allowed bg-transparent opacity-40"
                    )}
                  >
                    <TerminalIcon className="h-4 w-4" />
                  </button>
                </div>
              </div>

              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-auto">
                  <div className="flex min-h-full w-full flex-col px-6 py-6">
                    {connection.successNotice ? (
                      <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                        {connection.successNotice}
                      </div>
                    ) : null}
                    {children}
                  </div>
                </div>

                {terminal.terminalOpen ? (
                  <SshTerminalPanel
                    status={connection.status}
                    terminalMessage={terminal.terminalMessage}
                    terminalHeight={terminal.terminalHeight}
                    terminalGridLabel={terminal.terminalGridLabel}
                    onResizeStart={(event) => terminal.beginTerminalResize(event.clientY)}
                    onClose={() => void terminal.closeTerminal()}
                    surfaceRef={terminalSurfaceRef}
                    viewportRef={terminalViewportRef}
                  />
                ) : null}
              </div>
            </div>
          </main>
        </div>
      </div>

      <SshConnectDialog
        open={connection.contextValue.dialogOpen}
        status={connection.status}
        form={connection.form}
        formError={connection.formError}
        connectBusy={connection.connectBusy}
        connectDisabled={connection.connectDisabled}
        onOpenChange={connection.contextValue.setDialogOpen}
        onFieldChange={connection.updateField}
        onSelectKeyFile={() => void connection.selectKeyFile()}
        onCancel={() => {
          connection.contextValue.setDialogOpen(false);
        }}
        onSubmit={() => void connection.contextValue.submitConnect()}
      />
    </SshShellContext.Provider>
  );
}

export function useSshShell() {
  const context = useContext(SshShellContext);
  if (!context) {
    throw new Error("useSshShell must be used within SshShellProvider");
  }
  return context;
}
