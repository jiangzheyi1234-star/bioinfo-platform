"use client";

import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";
import { useHomeData } from "./workspace-live-data";

export function HomePage() {
  const { runs, readiness, error } = useHomeData();
  const runnerReady = readiness.find((item) => item.key === "ready");
  const summaryItems = [
    { label: "Connected Server", value: runs[0]?.serverLabel ?? "Not connected" },
    { label: "Runner Ready", value: runnerReady?.status === "ok" ? "Ready" : "Needs attention" },
    { label: "Connection State", value: readiness.find((item) => item.key === "live")?.status === "ok" ? "Connected" : "Disconnected" },
    { label: "Terminal", value: "Available on demand" },
  ];

  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title="Connection"
        description="当前阶段先收缩为远端连接与服务可用性视图，只保留最真实、最稳定、最有确定性的部分。"
        actions={
          <>
            <WorkspaceActionButton href="/servers">Open server</WorkspaceActionButton>
          </>
        }
      />

      <SummaryStrip items={summaryItems} />

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 text-sm text-rose-800">
          Failed to load live connection data · {error}
        </div>
      ) : null}

      <WorkspaceSection
        title="Server readiness"
        description="当前阶段只回答三件事：连上了吗、服务起来了吗、现在下一步该做什么。"
        actions={<WorkspaceActionButton href="/servers">Inspect lifecycle</WorkspaceActionButton>}
      >
        <div className="space-y-2">
          {readiness.map((item) => (
            <div key={item.key} className="rounded-xl bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-900">{item.label}</p>
                  <p className="mt-1 text-[12px] text-slate-500">{item.value}</p>
                </div>
                <span
                  className={
                    item.status === "ok"
                      ? "h-2.5 w-2.5 rounded-full bg-emerald-500"
                      : item.status === "warning"
                        ? "h-2.5 w-2.5 rounded-full bg-amber-500"
                        : "h-2.5 w-2.5 rounded-full bg-rose-500"
                  }
                />
              </div>
              {item.reasonCode ? <p className="mt-2 text-[12px] text-slate-500">reasonCode · {item.reasonCode}</p> : null}
            </div>
          ))}
        </div>
      </WorkspaceSection>
    </div>
  );
}
