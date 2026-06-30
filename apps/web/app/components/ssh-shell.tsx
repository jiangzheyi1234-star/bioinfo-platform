"use client";

import { createContext, useContext, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Terminal as TerminalIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { isSshChannelReady, type SshShellContextValue, toForm } from "./ssh-shell-model";
import { useSshConnection } from "./ssh-shell-connection";
import { useSshTerminal } from "./ssh-shell-terminal";
import { RemoteStatusBar, SshConnectDialog, SshSidebar, SshTerminalPanel } from "./ssh-shell-ui";

const SshShellContext = createContext<SshShellContextValue | null>(null);

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const terminalSurfaceRef = useRef<HTMLDivElement | null>(null);
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);

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
  const sshChannelReady = isSshChannelReady(connection.status);

  return (
    <SshShellContext.Provider value={connection.contextValue}>
      <div className="flex h-screen flex-col bg-[#fbfbfa] text-slate-900">
        <div className="grid min-h-0 flex-1 grid-cols-[56px_minmax(0,1fr)] md:grid-cols-[208px_minmax(0,1fr)]">
          <SshSidebar
            pathname={pathname}
            status={connection.status}
            connectBusy={connection.connectBusy}
            disconnectBusy={connection.disconnectBusy}
            ensureRunnerBusy={connection.ensureRunnerBusy}
            onOpenConnect={openConnectDialog}
            onDisconnect={() => void connection.contextValue.submitDisconnect()}
            onEnsureRunner={() => void connection.ensureRunner()}
          />

          <main className="min-h-0 min-w-0 bg-white p-0">
            <div className="relative flex h-full min-h-0 min-w-0 flex-col bg-white">
              <div className="flex min-h-0 flex-1 flex-col bg-white">
                <div className="min-h-0 flex-1 relative flex flex-col pt-0 pb-0">
                  <button
                    type="button"
                    aria-label="远程终端"
                    title={sshChannelReady ? "远程终端" : "请先连接远端服务器"}
                    disabled={!sshChannelReady}
                    onClick={toggleTerminal}
                    className={cn(
                      "absolute right-3 top-2 z-20 inline-flex h-8 w-8 appearance-none items-center justify-center",
                      "rounded-lg border border-transparent text-slate-400 shadow-none outline-none transition",
                      sshChannelReady
                        ? terminal.terminalOpen
                          ? "bg-slate-100 text-slate-900"
                          : "bg-white/80 hover:bg-slate-100 hover:text-slate-900"
                        : "cursor-not-allowed bg-white/80 opacity-40"
                    )}
                  >
                    <TerminalIcon strokeWidth={1.5} className="h-4 w-4" />
                  </button>
                  {connection.successNotice ? (
                    <div className="m-4 shrink-0 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                      {connection.successNotice}
                    </div>
                  ) : null}
                  <div className="flex-1 min-h-0 w-full h-full relative">
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
        <RemoteStatusBar
          status={connection.status}
          connectBusy={connection.connectBusy}
          ensureRunnerBusy={connection.ensureRunnerBusy}
          onRefreshStatus={() => connection.refreshStatus({ silent: true })}
          onEnsureRunner={() => void connection.ensureRunner()}
        />
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
