import type { AddedTool } from "./tools-page-model";

type CondaEnvironmentSummary = {
  channels: string[];
  dependencies: string[];
};

export function GeneratedWorkflowRuleSpecPanel({ tool }: { tool: AddedTool | undefined }) {
  const template = (tool?.ruleTemplate || {}) as Record<string, unknown>;
  const commandTemplate = stringValue(template.commandTemplate);
  const environment = readCondaEnvironment(template.environment);
  return (
    <div className="rounded-md bg-white px-3 py-2">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">RuleSpec</div>
      <div className="grid gap-2">
        <div className="rounded border border-slate-100 bg-slate-50 px-2 py-2">
          <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">commandTemplate</div>
          <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-700">
            {commandTemplate || "未声明 commandTemplate"}
          </pre>
        </div>
        <div className="rounded border border-slate-100 bg-slate-50 px-2 py-2">
          <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">environment</div>
          {environment ? (
            <div className="grid gap-1">
              <RuleSpecList label="channels" values={environment.channels} />
              <RuleSpecList label="dependencies" values={environment.dependencies} />
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-200 px-2 py-1.5 text-[11px] text-slate-400">
              未声明 conda environment
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RuleSpecList({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div>
      {values.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {values.map((value) => (
            <span key={value} className="max-w-full truncate rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
              {value}
            </span>
          ))}
        </div>
      ) : (
        <div className="mt-1 text-[11px] text-slate-400">none</div>
      )}
    </div>
  );
}

function readCondaEnvironment(raw: unknown): CondaEnvironmentSummary | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const environment = raw as Record<string, unknown>;
  const conda = environment.conda;
  if (!conda || typeof conda !== "object" || Array.isArray(conda)) return null;
  const spec = conda as Record<string, unknown>;
  const channels = stringArray(spec.channels);
  const dependencies = stringArray(spec.dependencies);
  return channels.length > 0 || dependencies.length > 0 ? { channels, dependencies } : null;
}

function stringArray(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.map(stringValue).filter(Boolean) : [];
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}
