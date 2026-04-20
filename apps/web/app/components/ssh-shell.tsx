"use client";

import { createContext, useContext, useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Terminal as TerminalIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { type SshShellContextValue, toForm } from "./ssh-shell-model";
import { useSshConnection } from "./ssh-shell-connection";
import { useSshTerminal } from "./ssh-shell-terminal";
import { SshConnectDialog, SshSidebar, SshTerminalPanel } from "./ssh-shell-ui";

const SshShellContext = createContext<SshShellContextValue | null>(null);

export function SshShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const terminalSurfaceRef = useRef<HTMLDivElement | null>(null);
  const terminalViewportRef = useRef<HTMLDivElement | null>(null);

  const connection = useSshConnection(router);
  const terminal = useSshTerminal({
    status: connection.status,
    refreshStatus: connection.refreshStatus,
    surfaceRef: terminalSurfaceRef,
    viewportRef: terminalViewportRef,
  });

  return (
    <SshShellContext.Provider value={connection.contextValue}>
      <div className="min-h-screen bg-[#fbfbfa] text-slate-900">
        <div className="grid min-h-screen grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)]">
          <SshSidebar
            pathname={pathname}
            status={connection.status}
            disconnectBusy={connection.disconnectBusy}
            onOpenConnect={() => {
              router.push("/connect");
              if (!connection.status?.connected) {
                connection.contextValue.clearFormError();
                connection.contextValue.setForm(toForm(connection.status));
                connection.contextValue.setDialogOpen(true);
              }
            }}
            onDisconnect={() => void connection.contextValue.submitDisconnect()}
          />

          <main className="min-h-screen min-w-0 bg-white p-0">
            <div className="flex h-full min-h-screen min-w-0 flex-col overflow-hidden bg-white">
              <div className="flex items-center justify-end gap-2 px-6 py-4">
                <button
                  type="button"
                  aria-label="远程终端"
                  title={connection.status?.connected ? "远程终端" : "请先连接远端服务器"}
                  disabled={!connection.status?.connected}
                  onClick={() => void (terminal.terminalOpen ? terminal.closeTerminal() : terminal.openTerminal())}
                  className={cn(
                    "inline-flex h-10 w-10 appearance-none items-center justify-center rounded-xl border text-slate-500 shadow-none outline-none transition",
                    connection.status?.connected
                      ? terminal.terminalOpen
                        ? "border-slate-200 bg-slate-100/90 text-slate-900 shadow-sm"
                        : "border-transparent bg-transparent shadow-none hover:bg-slate-100/80 hover:text-slate-900"
                      : "cursor-not-allowed border-transparent bg-transparent opacity-40"
                  )}
                >
                  <TerminalIcon className="h-4 w-4" />
                </button>
              </div>

              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-auto">
                  <div className="flex min-h-full w-full flex-col px-8 py-8">
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
                    onResizeStart={(event: ReactPointerEvent<HTMLButtonElement>) => terminal.beginTerminalResize(event.clientY)}
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
          router.push("/");
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
