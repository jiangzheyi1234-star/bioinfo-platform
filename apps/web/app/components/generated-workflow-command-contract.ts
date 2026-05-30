import type {
  GeneratedWorkflowInputBinding,
  GeneratedWorkflowStepRuntime,
  GeneratedWorkflowValidationIssue,
  RuleInputSpec,
  RuleOutputSpec,
} from "./generated-workflow-model";

const COMMAND_PORT_TOKEN_RE = /\{(input|output)\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}/g;
const COMMAND_RESOURCE_TOKEN_RE = /\{resources\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}/g;
const COMMAND_LOG_TOKEN_RE = /\{log\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}/g;

export type CommandPortReferences = {
  inputs: string[];
  outputs: string[];
};

export type CommandRuntimeReferences = {
  threads: boolean;
  resources: string[];
  log: boolean;
  logs: string[];
};

export function commandPortReferences(ruleTemplate: Record<string, unknown>): CommandPortReferences {
  const commandTemplate = typeof ruleTemplate.commandTemplate === "string" ? ruleTemplate.commandTemplate : "";
  const inputs = new Set<string>();
  const outputs = new Set<string>();
  for (const match of commandTemplate.matchAll(COMMAND_PORT_TOKEN_RE)) {
    const [, direction, name] = match;
    if (direction === "input") inputs.add(name);
    if (direction === "output") outputs.add(name);
  }
  return { inputs: Array.from(inputs), outputs: Array.from(outputs) };
}

export function commandRuntimeReferences(ruleTemplate: Record<string, unknown>): CommandRuntimeReferences {
  const commandTemplate = typeof ruleTemplate.commandTemplate === "string" ? ruleTemplate.commandTemplate : "";
  return {
    threads: /\{threads(?::q)?\}/.test(commandTemplate),
    resources: Array.from(new Set(Array.from(commandTemplate.matchAll(COMMAND_RESOURCE_TOKEN_RE)).map((match) => match[1]))),
    log: /\{log(?::q)?\}/.test(commandTemplate),
    logs: Array.from(new Set(Array.from(commandTemplate.matchAll(COMMAND_LOG_TOKEN_RE)).map((match) => match[1]))),
  };
}

export function validateStepCommandPortBindings({
  inputSpecs,
  inputBindings,
  outputSpecs,
  runtime,
  ruleTemplate,
  stepId,
}: {
  inputSpecs: RuleInputSpec[];
  inputBindings?: Record<string, GeneratedWorkflowInputBinding>;
  outputSpecs: RuleOutputSpec[];
  runtime?: GeneratedWorkflowStepRuntime;
  ruleTemplate: Record<string, unknown>;
  stepId: string;
}): GeneratedWorkflowValidationIssue[] {
  const references = commandPortReferences(ruleTemplate);
  const inputNames = new Set(inputSpecs.map((spec) => spec.name));
  const outputNames = new Set(outputSpecs.map((spec) => spec.name));
  const issues: GeneratedWorkflowValidationIssue[] = [];
  for (const name of references.inputs) {
    if (!inputNames.has(name)) {
      issues.push({
        code: "WORKFLOW_STEP_INPUT_TOKEN_UNKNOWN",
        message: `commandTemplate 引用了未声明输入 ${stepId}.${name}`,
        stepId,
        inputName: name,
      });
      continue;
    }
    if (inputBindings && !commandInputBindingIsBound(inputBindings[name])) {
      issues.push({
        code: "WORKFLOW_STEP_INPUT_TOKEN_UNBOUND",
        message: `commandTemplate 引用了未绑定输入 ${stepId}.${name}`,
        stepId,
        inputName: name,
      });
    }
  }
  for (const name of references.outputs) {
    if (!outputNames.has(name)) {
      issues.push({
        code: "WORKFLOW_STEP_OUTPUT_TOKEN_UNKNOWN",
        message: `commandTemplate 引用了未声明输出 ${stepId}.${name}`,
        stepId,
      });
    }
  }
  issues.push(...validateCommandRuntimeBindings({ ruleTemplate, runtime, stepId }));
  return issues;
}

function validateCommandRuntimeBindings({
  ruleTemplate,
  runtime,
  stepId,
}: {
  ruleTemplate: Record<string, unknown>;
  runtime?: GeneratedWorkflowStepRuntime;
  stepId: string;
}): GeneratedWorkflowValidationIssue[] {
  const references = commandRuntimeReferences(ruleTemplate);
  const defaults = runtimeDefaultsForRuleTemplate(ruleTemplate);
  const runtimeResources = runtime?.resources || runtime?.schedulerResources || {};
  const logNames = new Set([...Object.keys(defaults.logs), ...runtimeLogNames(runtime?.log)]);
  const hasLog =
    defaults.hasLog ||
    runtimeLogNames(runtime?.log).length > 0 ||
    (typeof runtime?.log === "string" && runtime.log.trim().length > 0);
  const issues: GeneratedWorkflowValidationIssue[] = [];
  if (references.threads && !runtime?.threads && defaults.threads === undefined) {
    issues.push({ code: "WORKFLOW_STEP_THREADS_TOKEN_UNBOUND", message: `commandTemplate 引用了未绑定 threads ${stepId}`, stepId });
  }
  for (const name of references.resources) {
    if (runtimeResources[name] === undefined && defaults.resources[name] === undefined) {
      issues.push({
        code: "WORKFLOW_STEP_RESOURCE_TOKEN_UNKNOWN",
        message: `commandTemplate 引用了未声明调度资源 ${stepId}.${name}`,
        stepId,
      });
    }
  }
  if (references.log && !hasLog) {
    issues.push({ code: "WORKFLOW_STEP_LOG_TOKEN_UNBOUND", message: `commandTemplate 引用了未绑定 log ${stepId}`, stepId });
  }
  for (const name of references.logs) {
    if (!logNames.has(name)) {
      issues.push({ code: "WORKFLOW_STEP_LOG_TOKEN_UNKNOWN", message: `commandTemplate 引用了未声明日志 ${stepId}.${name}`, stepId });
    }
  }
  return issues;
}

function commandInputBindingIsBound(binding: GeneratedWorkflowInputBinding | undefined): boolean {
  if (!binding) return false;
  if (typeof binding === "string") return false;
  if ("fromUpload" in binding) return Number.isInteger(binding.fromUpload) && binding.fromUpload >= 0;
  return binding.fromStep.trim().length > 0 && binding.output.trim().length > 0;
}

function runtimeDefaultsForRuleTemplate(ruleTemplate: Record<string, unknown>) {
  const resources = ruleSpecResources(ruleTemplate.resources);
  const logs = logDefaults(ruleTemplate.log);
  return {
    threads: defaultRuntimeValue(ruleTemplate.threads) ?? defaultRuntimeValue(resources.threads),
    resources: {
      ...ruleSpecResourceDefaults(resources),
      ...runtimeResourceDefaults(ruleTemplate.schedulerResources || ruleTemplate.runtimeResources),
    },
    logs,
    hasLog: typeof ruleTemplate.log === "string" ? Boolean(ruleTemplate.log.trim()) : Object.keys(logs).length > 0,
  };
}

function runtimeResourceDefaults(raw: unknown): Record<string, string | number> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .map(([key, value]) => [key, defaultRuntimeValue(value)] as const)
      .filter((entry): entry is [string, string | number] => entry[1] !== undefined)
  );
}

function ruleSpecResourceDefaults(resources: Record<string, unknown>): Record<string, string | number> {
  return Object.fromEntries(
    Object.entries(resources)
      .filter(([key, value]) => key !== "threads" && !hasWorkflowResourceMarkers(value))
      .map(([key, value]) => [key, defaultRuntimeValue(value)] as const)
      .filter((entry): entry is [string, string | number] => entry[1] !== undefined)
  );
}

function ruleSpecResources(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function hasWorkflowResourceMarkers(raw: unknown): boolean {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const item = raw as Record<string, unknown>;
  return Boolean(item.acceptedTemplates || item.acceptedCapabilities || item.configKey);
}

function defaultRuntimeValue(raw: unknown): string | number | undefined {
  if (typeof raw === "string" || typeof raw === "number") return raw;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const value = (raw as Record<string, unknown>).default ?? (raw as Record<string, unknown>).value;
  return typeof value === "string" || typeof value === "number" ? value : undefined;
}

function logDefaults(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .map(([key, value]) => [key.trim(), typeof value === "string" ? value.trim() : ""] as const)
      .filter(([key, value]) => Boolean(key && value))
  );
}

function runtimeLogNames(log: GeneratedWorkflowStepRuntime["log"] | undefined): string[] {
  return log && typeof log === "object" && !Array.isArray(log) ? Object.keys(log).filter(Boolean) : [];
}
