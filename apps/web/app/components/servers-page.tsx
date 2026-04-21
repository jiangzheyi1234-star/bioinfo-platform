"use client";

import { DataRow, ExternalAffordance, SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useServerListData } from "./workspace-live-data";

function lifecycleLabel(connected: boolean, ready: boolean) {
  if (!connected) return "Connect";
  if (!ready) return "Bootstrap";
  return "Ready";
}

export function ServersPage() {
  const { servers, error } = useServerListData();
  const summary = [
    { label: "Connected", value: String(servers.filter((server) => server.connected).length).padStart(2, "0") },
    { label: "Ready", value: String(servers.filter((server) => server.ready).length).padStart(2, "0") },
    { label: "Needs attention", value: String(servers.filter((server) => !server.ready).length).padStart(2, "0") },
    { label: "Primary", value: servers[0]?.label ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title="Servers"
        description="服务器列表只回答三个问题：连上了吗、能跑了吗、下一步是什么。"
        breadcrumbs={[{ label: "Servers" }]}
      />

      <SummaryStrip items={summary} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">Failed to load live server data · {error}</div>
      ) : null}

      <WorkspaceSection title="Server inventory" description="列表直接暴露下一步，不用额外做一整块解释性面板。">
        <div className="space-y-1">
          {servers.map((server) => (
            <DataRow key={server.serverId} href={`/servers/${server.serverId}`}>
              <div className="grid min-w-0 flex-1 gap-3 md:grid-cols-[minmax(0,1.4fr)_120px_140px_160px_32px] md:items-center">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900">{server.label}</p>
                  <p className="truncate text-[12px] text-slate-500">{server.user}@{server.host}:{server.port}</p>
                </div>
                <p className="text-sm text-slate-700">{server.connected ? "Connected" : "Disconnected"}</p>
                <p className="text-sm text-slate-700">{lifecycleLabel(server.connected, server.ready)}</p>
                <p className="truncate text-sm text-slate-500">{server.reasonCode || server.message || "—"}</p>
                <div className="flex justify-end">
                  <ExternalAffordance />
                </div>
              </div>
            </DataRow>
          ))}
        </div>
      </WorkspaceSection>
    </div>
  );
}
