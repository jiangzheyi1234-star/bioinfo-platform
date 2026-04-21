import { EmptyState, SummaryStrip, WorkspaceActionButton, WorkspacePageHeader, WorkspaceSection } from "./workspace-primitives";

type WorkspacePlaceholderPageProps = {
  section: string;
  description: string;
  bullets?: string[];
  summary?: { label: string; value: string }[];
  primaryActionLabel?: string;
};

export function WorkspacePlaceholderPage({
  section,
  description,
  bullets = [],
  summary = [],
  primaryActionLabel,
}: WorkspacePlaceholderPageProps) {
  return (
    <div className="space-y-6">
      <WorkspacePageHeader
        title={section}
        description={description}
        breadcrumbs={[{ label: section }]}
        actions={
          primaryActionLabel ? <WorkspaceActionButton variant="primary">{primaryActionLabel}</WorkspaceActionButton> : undefined
        }
      />

      {summary.length ? <SummaryStrip items={summary.map((item) => ({ label: item.label, value: item.value }))} /> : null}

      <WorkspaceSection title={`${section} roadmap`} description="页面结构已按 v1 工作台信息架构留位，后续会接入真实本地后端数据。">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(280px,0.75fr)]">
          <ul className="space-y-3 text-sm leading-6 text-slate-600">
            {bullets.map((bullet) => (
              <li key={bullet} className="rounded-xl bg-slate-50 px-4 py-3">
                {bullet}
              </li>
            ))}
          </ul>
          <EmptyState
            title={`${section} is staged`}
            description="这一页先统一到科研克制风的基础样式，再逐步接入列表、对象页和结构化错误视图。"
            action={primaryActionLabel ? <WorkspaceActionButton variant="primary">{primaryActionLabel}</WorkspaceActionButton> : undefined}
          />
        </div>
      </WorkspaceSection>
    </div>
  );
}
