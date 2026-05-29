import type { RuleSpecDraft, RuleSpecTemplate, ToolSearchItem } from "./tools-page-model";

const RULE_ACTION_FIELDS = ["commandTemplate", "wrapper", "script", "module"] as const;

type RuleActionField = (typeof RULE_ACTION_FIELDS)[number];

export type ToolRuleReadinessKind =
  | "workflow-ready"
  | "rule-draft"
  | "dependency-only"
  | "platform-unsupported";

export type ToolRuleReadiness = {
  actionLabel: string;
  envLabel: string;
  hasAction: boolean;
  hasEnv: boolean;
  inputs: number;
  kind: ToolRuleReadinessKind;
  label: "可加入流程" | "待确认 RuleSpec" | "仅依赖" | "平台不支持";
  outputs: number;
  outputsReady: boolean;
  params: number;
  requiresUserCompletion: boolean;
  template: RuleSpecTemplate;
  workflowReady: boolean;
};

export function ruleSpecReadinessForTool(tool: ToolSearchItem): ToolRuleReadiness {
  const { draft, template } = displayRuleTemplateEntryForTool(tool);
  const actions = ruleActionFields(template);
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  const outputs = Array.isArray(template.outputs) ? template.outputs : [];
  const params = objectValue(template.params);
  const dependencies = template.environment?.conda?.dependencies || [];
  const hasEnv = dependencies.length > 0 || Boolean(packageSpecForTool(tool));
  const requiresUserCompletion = draft?.requiresUserCompletion === true;
  const hasAction = actions.length === 1;
  const inputsReady = inputs.length > 0 && inputs.every((input) => stringValue(input.name));
  const outputsReady = outputs.length > 0 && outputs.every(outputSpecReady);
  const platformReady = tool.targetPlatformSupported === true;
  const workflowReady = platformReady && hasAction && inputsReady && outputsReady && hasEnv && !requiresUserCompletion;
  const base = {
    actionLabel: hasAction ? actions[0] : actions.length > 1 ? "action 冲突" : "待补 action",
    envLabel: environmentLabel(tool, dependencies),
    hasAction,
    hasEnv,
    inputs: inputs.length,
    outputs: outputs.length,
    outputsReady,
    params: Object.keys(params).length,
    requiresUserCompletion,
    template,
    workflowReady,
  };
  if (workflowReady) {
    return { ...base, kind: "workflow-ready", label: "可加入流程" };
  }
  if (tool.targetPlatformSupported === false) {
    return { ...base, kind: "platform-unsupported", label: "平台不支持" };
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
    resources: { threads: { default: 1 } },
    log: "logs/fastqc.log",
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

export function ruleActionFields(template: Record<string, unknown>): RuleActionField[] {
  return RULE_ACTION_FIELDS.filter((field) =>
    field === "module" ? moduleActionReady(template.module) : typeof template[field] === "string" && template[field].trim().length > 0
  );
}

function moduleActionReady(raw: unknown) {
  const module = objectValue(raw);
  return Boolean(stringValue(module.snakefile) && stringValue(module.rule));
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
    hasRuleAction(template) ||
    Array.isArray(template.inputs) ||
    Array.isArray(template.outputs) ||
    (template.params && typeof template.params === "object" && !Array.isArray(template.params))
  );
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

function environmentLabel(tool: ToolSearchItem, dependencies: string[]) {
  if (dependencies.length > 1) return `${dependencies.length} deps`;
  if (dependencies.length === 1) return dependencies[0];
  return packageSpecForTool(tool) || "待补 env";
}

function packageSpecForTool(tool: ToolSearchItem) {
  const selected = "selectedPackageSpec" in tool ? stringValue(tool.selectedPackageSpec) : "";
  return selected || stringValue(tool.packageSpec);
}

function uniqueChannels(source: string) {
  return Array.from(new Set(["conda-forge", source === "conda-forge" ? "bioconda" : source].filter(Boolean)));
}

function objectValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

function safeName(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "tool";
}
