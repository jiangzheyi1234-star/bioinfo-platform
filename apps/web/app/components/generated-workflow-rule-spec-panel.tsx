import type { AddedTool } from "./tools-page-model";

type CondaEnvironmentSummary = {
  channels: string[];
  dependencies: string[];
};

type RuleSpecProvenanceSummary = {
  source: string;
  lockType: string;
  wrapperRepository: string;
  wrapperRef: string;
  wrapperPath: string;
  wrapperIdentifier: string;
  packageSpec: string;
  version: string;
  sourceUrl: string;
  environmentUrl: string;
};

type RulePortSummary = Record<string, unknown> & {
  name: string;
};

export function GeneratedWorkflowRuleSpecPanel({ tool }: { tool: AddedTool | undefined }) {
  const template = ruleTemplateForTool(tool);
  const commandTemplate = stringValue(template.commandTemplate);
  const wrapperIdentifier = stringValue(template.wrapper);
  const script = stringValue(template.script);
  const moduleAction = moduleActionDisplay(template);
  const commandDisplay = commandTemplate || (wrapperIdentifier ? `wrapper: ${wrapperIdentifier}` : script ? `script: ${script}` : moduleAction);
  const environment = readCondaEnvironment(template.environment);
  const provenance = readRuleSpecProvenance(tool, template);
  return (
    <div className="rounded-md bg-white px-3 py-2">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">RuleSpec</div>
      <div className="grid gap-2">
        <RuleSpecProvenance provenance={provenance} />
        <RuleSpecContractSummary template={template} />
        <div className="rounded border border-slate-100 bg-slate-50 px-2 py-2">
          <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">commandTemplate / wrapper / script / module</div>
          <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-slate-700">
            {commandDisplay || "未声明 rule action"}
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

function RuleSpecContractSummary({ template }: { template: Record<string, unknown> }) {
  const inputs = rulePortItems(template.inputs);
  const outputs = rulePortItems(template.outputs);
  const params = ruleParamItems(template.params);
  const runtime = ruleRuntimeItems(template);
  return (
    <div className="grid gap-2 rounded border border-slate-100 bg-slate-50 px-2 py-2">
      <div className="grid gap-2 md:grid-cols-2">
        <RuleSpecContractSection label="输入端口" emptyLabel="未声明 inputs">
          {inputs.map((item) => (
            <RuleSpecContractRow key={item.name} name={item.name} value={formatRulePortItem(item)} />
          ))}
        </RuleSpecContractSection>
        <RuleSpecContractSection label="输出端口" emptyLabel="未声明 outputs">
          {outputs.map((item) => (
            <RuleSpecContractRow
              key={item.name}
              name={item.name}
              value={[formatRulePortItem(item), formatRuleOutputSemantics(item)].filter(Boolean).join(" · ")}
            />
          ))}
        </RuleSpecContractSection>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <RuleSpecContractSection label="参数默认值" emptyLabel="未声明 params">
          {params.map((item) => (
            <RuleSpecContractRow key={item.name} name={item.name} value={item.value} />
          ))}
        </RuleSpecContractSection>
        <RuleSpecContractSection label="调度资源 / log" emptyLabel="未声明 resources/log">
          {runtime.map((item) => (
            <RuleSpecContractRow key={item.name} name={item.name} value={item.value} />
          ))}
        </RuleSpecContractSection>
      </div>
    </div>
  );
}

function RuleSpecContractSection({
  children,
  emptyLabel,
  label,
}: {
  children: React.ReactNode[];
  emptyLabel: string;
  label: string;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">{label}</div>
      {children.length > 0 ? <div className="grid gap-1">{children}</div> : <div className="text-[11px] text-slate-400">{emptyLabel}</div>}
    </div>
  );
}

function RuleSpecContractRow({ name, value }: { name: string; value: string }) {
  return (
    <div className="grid min-w-0 grid-cols-[72px_minmax(0,1fr)] gap-2 text-[11px]">
      <div className="truncate font-mono text-slate-500">{name}</div>
      <div className="truncate text-slate-600">{value || "declared"}</div>
    </div>
  );
}

function RuleSpecProvenance({ provenance }: { provenance: RuleSpecProvenanceSummary | null }) {
  if (!provenance) {
    return (
      <div className="rounded border border-dashed border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px] text-slate-400">
        未声明 RuleSpec provenance
      </div>
    );
  }
  const isWrapper = provenance.lockType === "snakemake-wrapper" || provenance.source === "snakemake-wrapper";
  return (
    <div className="rounded border border-slate-100 bg-slate-50 px-2 py-2">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-1">
        <div className="text-[10px] font-semibold uppercase text-slate-400">provenance</div>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-slate-500">
          {isWrapper ? "官方 wrapper 已锁定" : provenance.lockType || provenance.source || "rule"}
        </span>
      </div>
      <div className="grid gap-1">
        <RuleSpecKeyValue label="source" value={provenance.source} />
        <RuleSpecKeyValue label="wrapperRef" value={provenance.wrapperRef} />
        <RuleSpecKeyValue label="wrapperPath" value={provenance.wrapperPath} />
        <RuleSpecKeyValue label="wrapperIdentifier" value={provenance.wrapperIdentifier} />
        <RuleSpecKeyValue label="packageSpec" value={provenance.packageSpec} />
        <RuleSpecKeyValue label="version" value={provenance.version} />
        <RuleSpecLink label="sourceUrl" href={provenance.sourceUrl} />
        <RuleSpecLink label="environmentUrl" href={provenance.environmentUrl} />
      </div>
    </div>
  );
}

function RuleSpecKeyValue({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-2 text-[11px]">
      <div className="text-slate-400">{label}</div>
      <div className="truncate font-mono text-slate-700">{value}</div>
    </div>
  );
}

function RuleSpecLink({ label, href }: { label: string; href: string }) {
  if (!href) return null;
  return (
    <div className="grid min-w-0 grid-cols-[88px_minmax(0,1fr)] gap-2 text-[11px]">
      <div className="text-slate-400">{label}</div>
      <a className="truncate font-mono text-blue-600 hover:underline" href={href} target="_blank" rel="noreferrer">
        {href}
      </a>
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

function rulePortItems(raw: unknown): RulePortSummary[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .map((item, index) => ({ ...item, name: stringValue(item.name) || `port_${index + 1}` }));
}

function ruleParamItems(raw: unknown): { name: string; value: string }[] {
  const params = objectValue(raw);
  return Object.entries(params).map(([name, spec]) => ({
    name,
    value: formatRuleDefaultValue(spec),
  }));
}

function ruleRuntimeItems(template: Record<string, unknown>): { name: string; value: string }[] {
  const items: { name: string; value: string }[] = [];
  const threads = defaultRuntimeValue(template.threads) ?? defaultRuntimeValue(objectValue(template.resources).threads);
  if (threads !== "") items.push({ name: "threads", value: threads });
  for (const [name, spec] of Object.entries(objectValue(template.resources))) {
    if (name !== "threads" && !hasWorkflowResourceMarkers(spec)) {
      const value = defaultRuntimeValue(spec);
      if (value !== "") items.push({ name, value });
    }
  }
  for (const [name, spec] of Object.entries(objectValue(template.schedulerResources || template.runtimeResources))) {
    const value = defaultRuntimeValue(spec);
    if (value !== "") items.push({ name, value });
  }
  const log = template.log;
  if (typeof log === "string" && log.trim()) {
    items.push({ name: "log", value: log.trim() });
  } else if (log && typeof log === "object" && !Array.isArray(log)) {
    for (const [name, path] of Object.entries(log as Record<string, unknown>)) {
      const value = stringValue(path);
      if (value) items.push({ name, value });
    }
  }
  return items;
}

function formatRulePortItem(item: Record<string, unknown>): string {
  return [stringValue(item.type), stringValue(item.kind), stringValue(item.mimeType), item.required === false ? "optional" : ""]
    .filter(Boolean)
    .join(" · ");
}

function formatRuleOutputSemantics(item: Record<string, unknown>): string {
  return [
    item.directory === true ? "directory" : "",
    item.protected === true ? "protected" : "",
    item.temp === true ? "temp" : "",
    stringValue(item.path),
  ]
    .filter(Boolean)
    .join(" · ");
}

function formatRuleDefaultValue(raw: unknown): string {
  if (typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean") return String(raw);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "declared";
  const item = raw as Record<string, unknown>;
  const value = item.default ?? item.value;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return [stringValue(item.type), stringValue(item.description)].filter(Boolean).join(" · ") || "declared";
}

function defaultRuntimeValue(raw: unknown): string {
  if (typeof raw === "string" || typeof raw === "number") return String(raw);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "";
  const value = (raw as Record<string, unknown>).default ?? (raw as Record<string, unknown>).value;
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function hasWorkflowResourceMarkers(raw: unknown): boolean {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const item = raw as Record<string, unknown>;
  return Boolean(item.acceptedTemplates || item.acceptedCapabilities || item.configKey);
}

function ruleTemplateForTool(tool: AddedTool | undefined): Record<string, unknown> {
  const manifest = (tool?.ruleTemplate || {}) as Record<string, unknown>;
  const draft = (tool?.ruleSpecDraft?.ruleTemplate || {}) as Record<string, unknown>;
  if (hasRuleAction(manifest)) return manifest;
  if (hasRuleAction(draft)) return draft;
  return Object.keys(manifest).length > 0 ? manifest : draft;
}

function hasRuleAction(template: Record<string, unknown>) {
  return Boolean(
    stringValue(template.commandTemplate) ||
    stringValue(template.wrapper) ||
    stringValue(template.script) ||
    Object.keys(objectValue(template.module)).length > 0
  );
}

function moduleActionDisplay(template: Record<string, unknown>) {
  const moduleSpec = objectValue(template.module);
  const rule = stringValue(moduleSpec.rule);
  const snakefile = stringValue(moduleSpec.snakefile);
  if (!rule && !snakefile) return "";
  return `module: ${[rule, snakefile].filter(Boolean).join(" from ")}`;
}

function readRuleSpecProvenance(
  tool: AddedTool | undefined,
  template: Record<string, unknown>
): RuleSpecProvenanceSummary | null {
  if (!tool) return null;
  const draft = tool.ruleSpecDraft;
  const lock = objectValue(draft?.lock);
  const wrapperIdentifier = stringValue(lock.wrapperIdentifier) || stringValue(template.wrapper);
  const parsedWrapper = parseWrapperIdentifier(wrapperIdentifier);
  const wrapperPath = stringValue(lock.wrapperPath) || parsedWrapper.wrapperPath;
  const wrapperMatch = tool.snakemakeWrappers?.find((wrapper) => {
    return (
      (wrapperIdentifier && wrapper.wrapperIdentifier === wrapperIdentifier) ||
      (wrapperPath && wrapper.wrapperPath === wrapperPath)
    );
  });
  const provenance = {
    source: stringValue(draft?.source) || (wrapperIdentifier ? "snakemake-wrapper" : stringValue(template.source)),
    lockType: stringValue(lock.type) || (wrapperIdentifier ? "snakemake-wrapper" : ""),
    wrapperRepository: stringValue(lock.wrapperRepository) || stringValue(wrapperMatch?.wrapperRepository),
    wrapperRef: stringValue(lock.wrapperRef) || stringValue(wrapperMatch?.wrapperRef) || parsedWrapper.wrapperRef,
    wrapperPath: wrapperPath || stringValue(wrapperMatch?.wrapperPath),
    wrapperIdentifier,
    packageSpec: stringValue(lock.packageSpec) || stringValue(tool.selectedPackageSpec || tool.packageSpec),
    version: stringValue(lock.version) || stringValue(tool.selectedVersion || tool.latestVersion || tool.version),
    sourceUrl: stringValue(wrapperMatch?.wrapperUrl) || stringValue(tool.sourceUrl),
    environmentUrl: stringValue(wrapperMatch?.environmentUrl),
  };
  return Object.values(provenance).some(Boolean) ? provenance : null;
}

function parseWrapperIdentifier(identifier: string): { wrapperRef: string; wrapperPath: string } {
  const parts = identifier.split("/").map((part) => part.trim()).filter(Boolean);
  if (parts.length < 4) {
    return { wrapperRef: "", wrapperPath: parts.join("/") };
  }
  return { wrapperRef: parts[0], wrapperPath: parts.slice(1).join("/") };
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

function objectValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}
