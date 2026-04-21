"use client";

import { useState } from "react";

import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { runServerAction, useServerDetailData } from "./workspace-live-data";

function resolveNextAction(ready: boolean | undefined, connected: boolean | undefined) {
  if (ready) {
    return {
      title: "Service is ready",
      description: "当前远端服务已经可达，控制面链路是通的；后续执行能力会在下一阶段补齐。",
      primary: "Run health check",
    };
  }
  if (!connected) {
    return {
      title: "Connect first",
      description: "最佳实践是先确认连接链路稳定，再暴露 bootstrap / repair 之类动作。",
      primary: "Connect server",
    };
  }
  return {
    title: "Bootstrap runner",
    description: "当 startup/live 已通过但 ready 不满足时，只保留一个主动作：完成 runner/bootstrap。",
    primary: "Run bootstrap",
  };
}

export function ServerDetailPage({ serverId }: { serverId: string }) {
  const { server, readiness, error, reload } = useServerDetailData(serverId);
  const nextAction = resolveNextAction(server?.ready, server?.connected);
  const [actionError, setActionError] = useState("");
  const [busyAction, setBusyAction] = useState<string>("");

  async function handleAction(action: Parameters<typeof runServerAction>[1]) {
    setBusyAction(action);
    setActionError("");
    try {
      await runServerAction(serverId, action);
      reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Server action failed.");
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        eyebrow="Server"
        breadcrumbs={[{ label: "Servers", href: "/servers" }, { label: server?.label ?? serverId }]}
        title={server?.label ?? `Server ${serverId}`}
        description={server ? `${server.user}@${server.host}:${server.port}` : "Server detail"}
        actions={
          <>
            <WorkspaceActionButton>Refresh health</WorkspaceActionButton>
            <WorkspaceActionButton leadingIcon="terminal">Open terminal</WorkspaceActionButton>
          </>
        }
      />

      <SummaryStrip
        items={[
          { label: "Connected", value: server?.connected ? "Yes" : "No" },
          { label: "Ready", value: server?.ready ? "Ready" : "Not ready" },
          { label: "reasonCode", value: server?.reasonCode || "—" },
          { label: "Server ID", value: server?.serverId ?? serverId },
        ]}
      />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live server data · {error}</div>
      ) : null}
      {actionError ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Server action failed · {actionError}</div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <div className="space-y-5">
          <WorkspaceSection title="Service lifecycle" description="这里关注的是控制面链路是否成立，而不是远端 shell 细节。">
            <div className="rounded-2xl bg-slate-50 px-4 py-4">
              <p className="text-sm font-medium text-slate-900">{nextAction.title}</p>
              <p className="mt-2 text-sm leading-6 text-slate-600">{nextAction.description}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <WorkspaceActionButton
                  variant="primary"
                  onClick={() => void handleAction(server?.ready ? "refresh" : server?.connected ? "bootstrap" : "refresh")}
                  disabled={Boolean(busyAction)}
                >
                  {busyAction === "bootstrap" || busyAction === "refresh" ? "Working..." : nextAction.primary}
                </WorkspaceActionButton>
                <WorkspaceActionButton onClick={() => void handleAction("accept-host-key")} disabled={Boolean(busyAction)}>
                  {busyAction === "accept-host-key" ? "Working..." : "Inspect host key"}
                </WorkspaceActionButton>
              </div>
            </div>
          </WorkspaceSection>

          <WorkspaceSection title="Readiness checks" description="把 startup → live → ready 视为连续链路，用来判断远端服务是否可用。">
            <div className="space-y-3">
              {readiness.map((item, index) => (
                <div key={item.key} className="rounded-2xl bg-slate-50 px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-slate-900">{index + 1}. {item.label}</p>
                      <p className="mt-1 text-[12px] text-slate-500">{item.value}</p>
                    </div>
                    <span className={item.status === "ok" ? "h-2.5 w-2.5 rounded-full bg-emerald-500" : item.status === "warning" ? "h-2.5 w-2.5 rounded-full bg-amber-500" : "h-2.5 w-2.5 rounded-full bg-rose-500"} />
                  </div>
                  {item.reasonCode ? <p className="mt-2 text-[12px] text-slate-500">reasonCode · {item.reasonCode}</p> : null}
                </div>
              ))}
            </div>
          </WorkspaceSection>
        </div>

        <div className="space-y-5">
          <WorkspaceSection title="Management" description="动作区收敛成少数明确操作，不把 detail 页做成运维面板。">
            <div className="grid gap-2">
              <WorkspaceActionButton onClick={() => void handleAction("rotate-token")} disabled={Boolean(busyAction)}>
                {busyAction === "rotate-token" ? "Working..." : "Rotate token"}
              </WorkspaceActionButton>
              <WorkspaceActionButton onClick={() => void handleAction("accept-host-key")} disabled={Boolean(busyAction)}>
                {busyAction === "accept-host-key" ? "Working..." : "Accept host key"}
              </WorkspaceActionButton>
            </div>
          </WorkspaceSection>

          <WorkspaceSection title="Connection context" description="连接信息保持低噪音，但要足够明确。">
            <dl className="space-y-2 text-sm text-slate-700">
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Host</dt><dd>{server?.host ?? "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Port</dt><dd>{server?.port ?? "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">User</dt><dd>{server?.user ?? "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-slate-500">Message</dt><dd>{server?.message ?? "—"}</dd></div>
            </dl>
          </WorkspaceSection>
        </div>
      </div>
    </div>
  );
}
