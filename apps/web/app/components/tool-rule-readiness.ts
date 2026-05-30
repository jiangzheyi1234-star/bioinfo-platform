import type { RuleSpecDraft, RuleSpecTemplate, ToolSearchItem } from "./tools-page-model";

const RULE_ACTION_FIELDS = ["commandTemplate", "wrapper", "script", "module"] as const;

type RuleActionField = (typeof RULE_ACTION_FIELDS)[number];

export type ToolRuleReadinessKind =
  | "workflow-ready"
  | "validation-pending"
  | "rule-draft"
  | "dependency-only"
  | "platform-unsupported";

export type ToolRuleReadiness = {
  actionLabel: string;
  envLabel: string;
  hasAction: boolean;
  hasEnv: boolean;
  hasRuntime: boolean;
  hasSmoke: boolean;
  inputs: number;
  kind: ToolRuleReadinessKind;
  label: "可加入流程" | "待验证" | "待确认 RuleSpec" | "仅依赖" | "平台不支持";
  outputs: number;
  outputsReady: boolean;
  params: number;
  paramsReady: boolean;
  requiresUserCompletion: boolean;
  runtimeLabel: string;
  smokeLabel: string;
  template: RuleSpecTemplate;
  workflowReady: boolean;
};

export function ruleSpecReadinessForTool(tool: ToolSearchItem): ToolRuleReadiness {
  const { draft, template } = displayRuleTemplateEntryForTool(tool);
  const rawActions = ruleActionFields(template, { requireWrapperLock: false });
  const actions = ruleActionFields(template);
  const wrapperNeedsLock = rawActions.includes("wrapper") && !actions.includes("wrapper");
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  const outputs = Array.isArray(template.outputs) ? template.outputs : [];
  const params = objectValue(template.params);
  const paramsReady = template.params !== undefined && isRecord(template.params);
  const hasRuntime = ruleRuntimeReady(template);
  const conda = template.environment?.conda;
  const dependencies = conda?.dependencies || [];
  const channels = conda?.channels || [];
  const hasEnv = channels.length > 0 && dependencies.length > 0 && dependencies.every(dependencyLocked) && channelPriorityStrict(channels);
  const hasSmoke = smokeTestReady(template);
  const requiresUserCompletion = draft?.requiresUserCompletion === true;
  const hasAction = rawActions.length === 1 && actions.length === 1;
  const inputsReady = inputs.length > 0 && inputs.every((input) => stringValue(input.name));
  const outputsReady = outputs.length > 0 && outputs.every(outputSpecReady);
  const platformReady = tool.targetPlatformSupported === true;
  const localWorkflowReady = platformReady && hasAction && inputsReady && outputsReady && paramsReady && hasRuntime && hasEnv && hasSmoke && !requiresUserCompletion;
  const contractWorkflowReady = tool.toolContract?.workflowReady;
  const workflowReady = Boolean(contractWorkflowReady && localWorkflowReady);
  const base = {
    actionLabel: hasAction ? actions[0] : rawActions.length > 1 ? "action 冲突" : wrapperNeedsLock ? "待锁 wrapper" : "待补 action",
    envLabel: environmentLabel(dependencies, channels),
    hasAction,
    hasEnv,
    hasRuntime,
    hasSmoke,
    inputs: inputs.length,
    outputs: outputs.length,
    outputsReady,
    params: Object.keys(params).length,
    paramsReady,
    requiresUserCompletion,
    runtimeLabel: hasRuntime ? "threads/resources/log" : "待补 runtime/log",
    smokeLabel: hasSmoke ? "fixtures ready" : "待补 smoke",
    template,
    workflowReady,
  };
  if (workflowReady) {
    return { ...base, kind: "workflow-ready", label: "可加入流程" };
  }
  if (tool.targetPlatformSupported === false) {
    return { ...base, kind: "platform-unsupported", label: "平台不支持" };
  }
  if (localWorkflowReady && contractWorkflowReady !== true) {
    return { ...base, kind: "validation-pending", label: "待验证" };
  }
  if (hasRuleTemplateShape(template) || draft) {
    return { ...base, kind: "rule-draft", label: "待确认 RuleSpec" };
  }
  return { ...base, kind: "dependency-only", label: "仅依赖" };
}

export function executableRuleTemplateForTool(tool: ToolSearchItem | undefined): Record<string, unknown> {
  if (!tool) return {};
  const readiness = ruleSpecReadinessForTool(tool);
  return readiness.workflowReady ? (readiness.template as Record<string, unknown>) : {};
}

export function displayRuleTemplateForTool(tool: ToolSearchItem | undefined): Record<string, unknown> {
  if (!tool) return {};
  return displayRuleTemplateEntryForTool(tool).template as Record<string, unknown>;
}

export function withCuratedRuleTemplate<T extends ToolSearchItem>(tool: T): T {
  const manifest = objectValue(tool.ruleTemplate);
  if (hasRuleAction(manifest)) return tool;
  const known = starterRuleTemplateForKnownTool(tool);
  return known ? { ...tool, ruleTemplate: known } : tool;
}

export function starterRuleTemplateForKnownTool(tool: ToolSearchItem): RuleSpecTemplate | null {
  const name = safeName(tool.name || "");
  const packageSpec = packageSpecForTool(tool);
  if (name !== "fastqc") return null;
  const template: RuleSpecTemplate = {
    commandTemplate: "mkdir -p {output.qc_dir:q} && fastqc {input.reads:q} --outdir {output.qc_dir:q}",
    inputs: [{ name: "reads", type: "file", kind: "sequence", required: true }],
    outputs: [
      {
        name: "qc_dir",
        path: "results/fastqc",
        kind: "report",
        mimeType: "application/vnd.h2ometa.directory",
        directory: true,
      },
    ],
    params: {},
    resources: { threads: { default: 1 }, mem_mb: { default: 512 } },
    log: "logs/fastqc.log",
    smokeTest: {
      inputs: {
        reads: {
          filename: "reads.fastq",
          content: "@smoke\nACGT\n+\nFFFF\n",
          mimeType: "text/plain",
        },
      },
    },
  };
  if (packageSpec) {
    template.environment = {
      conda: {
        channels: uniqueChannels(tool.source),
        dependencies: [packageSpec],
      },
    };
  }
  return template;
}

export function hasRuleAction(template: Record<string, unknown>) {
  return ruleActionFields(template).length > 0;
}

export function ruleActionFields(
  template: Record<string, unknown>,
  options: { requireWrapperLock?: boolean } = { requireWrapperLock: true }
): RuleActionField[] {
  return RULE_ACTION_FIELDS.filter((field) =>
    field === "module"
      ? moduleActionReady(template.module)
      : field === "wrapper"
        ? wrapperActionReady(template.wrapper, options)
        : typeof template[field] === "string" && template[field].trim().length > 0
  );
}

function moduleActionReady(raw: unknown) {
  const moduleSpec = objectValue(raw);
  return Boolean(stringValue(moduleSpec.snakefile) && stringValue(moduleSpec.rule));
}

function wrapperActionReady(raw: unknown, options: { requireWrapperLock?: boolean }) {
  const wrapper = stringValue(raw);
  if (!wrapper) return false;
  return options.requireWrapperLock === false || wrapperRefLocked(wrapper);
}

function wrapperRefLocked(raw: unknown) {
  const parts = stringValue(raw)
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 2) return false;
  const ref = parts[0];
  if (["bio", "master", "main", "latest", "head", "dev"].includes(ref.toLowerCase())) return false;
  return /^v?\d+(?:\.\d+){1,}(?:[-+._A-Za-z0-9]*)?$/.test(ref) || /^[0-9a-fA-F]{7,40}$/.test(ref);
}

function displayRuleTemplateEntryForTool(tool: ToolSearchItem): { draft?: RuleSpecDraft; template: RuleSpecTemplate } {
  const manifest = objectValue(tool.ruleTemplate) as RuleSpecTemplate;
  const draft = tool.ruleSpecDraft;
  const draftTemplate = objectValue(draft?.ruleTemplate) as RuleSpecTemplate;
  if (hasRuleTemplateShape(manifest)) return { template: manifest };
  if (hasRuleTemplateShape(draftTemplate)) return { draft, template: draftTemplate };
  return { draft, template: Object.keys(manifest).length > 0 ? manifest : draftTemplate };
}

function hasRuleTemplateShape(template: Record<string, unknown>) {
  return Boolean(
    ruleActionFields(template, { requireWrapperLock: false }).length > 0 ||
    Array.isArray(template.inputs) ||
    Array.isArray(template.outputs) ||
    (template.params && typeof template.params === "object" && !Array.isArray(template.params))
  );
}

function ruleRuntimeReady(template: RuleSpecTemplate) {
  return ruleThreadsReady(template) && schedulerResourcesReady(template) && logReady(template.log);
}

function ruleThreadsReady(template: RuleSpecTemplate) {
  return positiveInt(template.threads) || positiveInt(resourceDefault(template.resources, "threads"));
}

function schedulerResourcesReady(template: RuleSpecTemplate) {
  return (
    schedulerResourceCount(template.schedulerResources) +
      schedulerResourceCount(template.runtimeResources) +
      schedulerResourceCount(template.resources, { skipThreads: true }) >
    0
  );
}

function schedulerResourceCount(raw: unknown, options: { skipThreads?: boolean } = {}) {
  const resources = objectValue(raw);
  return Object.entries(resources).filter(([name, value]) => {
    if (options.skipThreads && name === "threads") return false;
    return schedulerValueReady(value) && !workflowResourceValue(value);
  }).length;
}

function schedulerValueReady(raw: unknown): boolean {
  if (typeof raw === "number") return Number.isFinite(raw);
  if (typeof raw === "string") return raw.trim().length > 0;
  if (!isRecord(raw)) return false;
  const value = objectValue(raw);
  return schedulerValueReady(value.default) || schedulerValueReady(value.value);
}

function workflowResourceValue(raw: unknown) {
  const value = objectValue(raw);
  return Boolean(value.acceptedTemplates || value.acceptedCapabilities || value.configKey || value.type === "database");
}

function resourceDefault(resources: unknown, key: string) {
  const value = objectValue(resources)[key];
  const record = objectValue(value);
  return record.default ?? record.value ?? value;
}

function positiveInt(raw: unknown) {
  return typeof raw === "number" && Number.isInteger(raw) && raw >= 1;
}

function logReady(raw: unknown) {
  if (typeof raw === "string") return raw.trim().length > 0;
  const record = objectValue(raw);
  return Object.keys(record).length > 0 && Object.entries(record).every(([name, path]) => name.trim() && stringValue(path));
}

function smokeTestReady(template: RuleSpecTemplate) {
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  const requiredInputs = inputs.filter((input) => input.required !== false);
  const smokeInputs = objectValue(template.smokeTest?.inputs);
  return requiredInputs.length > 0 && requiredInputs.every((input) => smokeInputReady(smokeInputs[stringValue(input.name)]));
}

function smokeInputReady(raw: unknown) {
  const input = objectValue(raw);
  return typeof input.content === "string" || stringValue(input.contentBase64).length > 0;
}

function outputSpecReady(raw: unknown) {
  const output = objectValue(raw);
  return Boolean(
    stringValue(output.name) &&
    stringValue(output.path) &&
    stringValue(output.kind) &&
    stringValue(output.mimeType)
  );
}

function environmentLabel(dependencies: string[], channels: string[]) {
  if (dependencies.length > 0 && channels.length === 0) return "待补 channels";
  if (channels.length > 0 && !channelPriorityStrict(channels)) return "待调 channel priority";
  if (dependencies.some((dependency) => !dependencyLocked(dependency))) return "待锁 env";
  if (dependencies.length > 1) return `${dependencies.length} deps`;
  if (dependencies.length === 1) return dependencies[0];
  return "待补 env";
}

function packageSpecForTool(tool: ToolSearchItem) {
  const selected = "selectedPackageSpec" in tool ? stringValue(tool.selectedPackageSpec) : "";
  return selected || stringValue(tool.packageSpec);
}

function uniqueChannels(source: string) {
  return Array.from(new Set(["conda-forge", source === "conda-forge" ? "bioconda" : source].filter(Boolean)));
}

function dependencyLocked(value: string) {
  const spec = value.trim();
  if (!spec || /[<>*]/.test(spec)) return false;
  const packageSpec = spec.split("::").at(-1) || "";
  const separator = packageSpec.includes("==") ? "==" : packageSpec.includes("=") ? "=" : "";
  if (!separator) return false;
  const [name, version] = packageSpec.split(separator);
  return Boolean(name.trim() && version.trim());
}

function channelPriorityStrict(channels: string[]) {
  const condaForgeIndex = channels.indexOf("conda-forge");
  if (condaForgeIndex < 0) return false;
  const biocondaIndex = channels.indexOf("bioconda");
  return biocondaIndex < 0 || condaForgeIndex < biocondaIndex;
}

function objectValue(raw: unknown): Record<string, unknown> {
  return isRecord(raw) ? raw : {};
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return Boolean(raw && typeof raw === "object" && !Array.isArray(raw));
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

function safeName(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "tool";
}
