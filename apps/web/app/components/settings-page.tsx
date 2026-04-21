import { SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";

export function SettingsPage() {
  return (
    <div className="space-y-6 text-slate-900">
      <WorkspacePageHeader
        title="Settings"
        description="全局设置继续保持克制：只保留真正影响本地后端、SSH 与运行体验的配置。"
        breadcrumbs={[{ label: "Settings" }]}
        actions={<WorkspaceActionButton>Review defaults</WorkspaceActionButton>}
      />

      <SummaryStrip
        items={[
          { label: "API base", value: "127.0.0.1:8765" },
          { label: "SSH state", value: "Managed by local backend" },
          { label: "Terminal", value: "Docked" },
        ]}
      />

      <WorkspaceSection title="Configuration staging" description="后续这里会接入本地后端 settings contract，而不是堆积大量一次性选项。">
        <div className="grid gap-3 md:grid-cols-3">
          {[
            "Connection persistence",
            "Auto-connect policy",
            "Terminal and polling defaults",
          ].map((item) => (
            <div key={item} className="rounded-xl bg-slate-50 px-4 py-4 text-sm text-slate-600">
              {item}
            </div>
          ))}
        </div>
      </WorkspaceSection>
    </div>
  );
}
