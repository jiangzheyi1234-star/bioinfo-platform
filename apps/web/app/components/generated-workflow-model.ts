import type { AddedTool, ToolCapabilitySlot } from "./tools-page-model";
import type { WorkflowResourceBindings, WorkflowUpload } from "./workflows-page-model";

export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";

export type GeneratedWorkflowInputBinding =
  | { fromUpload: number }
  | { fromInput: string }
  | { fromStep: string; output: string }
  | string;

export type GeneratedWorkflowParamValue = string | number | boolean;
export type GeneratedWorkflowStepParams = Record<string, GeneratedWorkflowParamValue>;

export type GeneratedWorkflowStepDraft = {
  id: string;
  toolId: string;
  inputs: Record<string, GeneratedWorkflowInputBinding>;
  params: GeneratedWorkflowStepParams;
};

export type GeneratedWorkflowExposedOutput = {
  fromStep: string;
  output: string;
  as: string;
};

export type GeneratedWorkflowDraft = {
  steps: GeneratedWorkflowStepDraft[];
  exposeOutputs: GeneratedWorkflowExposedOutput[];
};

export type GeneratedWorkflowValidationIssue = {
  code: string;
  message: string;
  stepId?: string;
  inputName?: string;
};

export type GeneratedWorkflowValidation = {
  errors: GeneratedWorkflowValidationIssue[];
  warnings: GeneratedWorkflowValidationIssue[];
  orderedStepIds: string[];
};

export type BuildGeneratedWorkflowRunSpecInput = {
  projectId: string;
  uploads: WorkflowUpload[];
  draft: GeneratedWorkflowDraft;
  tools: AddedTool[];
  resourceBindings?: WorkflowResourceBindings;
};

export type ValidateGeneratedWorkflowDraftOptions = {
  inputCount?: number;
};

const COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format"] as const;

type RulePortCompatibilityField = (typeof COMPATIBILITY_FIELDS)[number];

export type RuleInputSpec = {
  name: string;
  required?: boolean;
  type?: string;
  kind?: string;
  mimeType?: string;
  data?: string;
  format?: string;
};

export type RuleOutputSpec = {
  name: string;
  type?: string;
  kind?: string;
  mimeType?: string;
  data?: string;
  format?: string;
};

export type RuleParamSpec = {
  name: string;
  type?: string;
  title?: string;
  description?: string;
  default?: GeneratedWorkflowParamValue;
  enum?: GeneratedWorkflowParamValue[];
  minimum?: number;
  maximum?: number;
};

export function normalizeStepId(value: string, fallback = "step") {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return normalized || fallback;
}

export function uniqueStepId(base: string, existingIds: string[]) {
  const existing = new Set(existingIds.map((id) => normalizeStepId(id)));
  const normalized = normalizeStepId(base);
  if (!existing.has(normalized)) return normalized;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${normalized}_${index}`;
    if (!existing.has(candidate)) return candidate;
  }
  return `${normalized}_${Date.now()}`;
}

export function readRuleInputs(tool: AddedTool | undefined): RuleInputSpec[] {
  const inputs = (tool?.ruleTemplate as { inputs?: unknown } | undefined)?.inputs;
  if (!Array.isArray(inputs)) return [];
  return inputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => normalizeRuleInputSpec(item, findCapabilitySlot(tool, "inputs", String(item.name || "").trim())))
    .filter((item) => item.name.length > 0);
}

export function readRuleOutputs(tool: AddedTool | undefined): RuleOutputSpec[] {
  const outputs = (tool?.ruleTemplate as { outputs?: unknown } | undefined)?.outputs;
  if (!Array.isArray(outputs)) return [];
  return outputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => normalizeRuleOutputSpec(item, findCapabilitySlot(tool, "outputs", String(item.name || "").trim())))
    .filter((item) => item.name.length > 0);
}

export function readRuleParams(tool: AddedTool | undefined): RuleParamSpec[] {
  const params = (tool?.ruleTemplate as { params?: unknown } | undefined)?.params;
  if (!params || typeof params !== "object" || Array.isArray(params)) return [];
  return Object.entries(params as Record<string, unknown>)
    .map(([name, raw]) => normalizeRuleParam(name, raw))
    .filter((item): item is RuleParamSpec => Boolean(item));
}

export function createStepParams(tool: AddedTool): GeneratedWorkflowStepParams {
  return Object.fromEntries(
    readRuleParams(tool)
      .filter((param) => param.default !== undefined)
      .map((param) => [param.name, param.default as GeneratedWorkflowParamValue])
  );
}

export function createGeneratedWorkflowDraft(tools: AddedTool[]): GeneratedWorkflowDraft {
  const first = tools[0];
  return {
    steps: first ? [createStepDraft(first, [])] : [],
    exposeOutputs: [],
  };
}

export function createStepDraft(
  tool: AddedTool,
  existingIds: string[],
  upstreamSteps: GeneratedWorkflowStepDraft[] = [],
  tools: AddedTool[] = []
): GeneratedWorkflowStepDraft {
  const stepId = uniqueStepId(tool.name || tool.id, existingIds);
  const inputs = Object.fromEntries(
    readRuleInputs(tool).map((input, index) => [
      input.name,
      findCompatibleOutputBinding(input, upstreamSteps, tools) || (index === 0 ? { fromUpload: 0 } : ""),
    ])
  );
  return {
    id: stepId,
    toolId: tool.id,
    inputs,
    params: createStepParams(tool),
  };
}

export function validateGeneratedWorkflowDraft(
  draft: GeneratedWorkflowDraft,
  tools: AddedTool[],
  options: ValidateGeneratedWorkflowDraftOptions = {}
): GeneratedWorkflowValidation {
  const errors: GeneratedWorkflowValidationIssue[] = [];
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const normalizedIds = new Map<string, string>();
  const outputsByStep = new Map<string, Set<string>>();
  const outgoing = new Map<string, string[]>();
  const incomingCount = new Map<string, number>();

  for (const step of draft.steps) {
    const normalized = normalizeStepId(step.id);
    if (normalizedIds.has(normalized)) {
      errors.push({ code: "WORKFLOW_STEP_DUPLICATE", message: `重复步骤 id: ${normalized}`, stepId: step.id });
    }
    normalizedIds.set(normalized, step.id);
    incomingCount.set(step.id, 0);
    outgoing.set(step.id, []);
    const tool = toolById.get(step.toolId);
    if (!tool) {
      errors.push({ code: "TOOL_UNKNOWN", message: `步骤 ${step.id} 未选择可用工具`, stepId: step.id });
      continue;
    }
    const outputs = readRuleOutputs(tool);
    outputsByStep.set(step.id, new Set(outputs.map((output) => output.name)));
    for (const input of readRuleInputs(tool)) {
      const binding = step.inputs[input.name];
      if (input.required && !binding) {
        errors.push({ code: "TOOL_INPUT_REQUIRED", message: `步骤 ${step.id} 缺少输入 ${input.name}`, stepId: step.id, inputName: input.name });
      }
    }
  }

  for (const step of draft.steps) {
    for (const [inputName, binding] of Object.entries(step.inputs)) {
      if (!isStepBinding(binding)) continue;
      const sourceStep = draft.steps.find((item) => item.id === binding.fromStep);
      if (!sourceStep) {
        errors.push({ code: "WORKFLOW_STEP_INPUT_STEP_UNKNOWN", message: `未知上游步骤 ${binding.fromStep}`, stepId: step.id, inputName });
        continue;
      }
      if (!outputsByStep.get(sourceStep.id)?.has(binding.output)) {
        errors.push({ code: "WORKFLOW_STEP_INPUT_OUTPUT_UNKNOWN", message: `未知输出 ${binding.fromStep}.${binding.output}`, stepId: step.id, inputName });
        continue;
      }
      if (!stepInputBindingIsCompatible(inputName, binding, step.toolId, sourceStep.toolId, toolById)) {
        errors.push({
          code: "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE",
          message: `输出 ${binding.fromStep}.${binding.output} 与输入 ${step.id}.${inputName} 类型不兼容`,
          stepId: step.id,
          inputName,
        });
      }
      outgoing.get(sourceStep.id)?.push(step.id);
      incomingCount.set(step.id, (incomingCount.get(step.id) || 0) + 1);
    }
    for (const [inputName, binding] of Object.entries(step.inputs)) {
      if (isUploadBinding(binding) && options.inputCount !== undefined && (binding.fromUpload < 0 || binding.fromUpload >= options.inputCount)) {
        errors.push({ code: "WORKFLOW_STEP_INPUT_UPLOAD_UNKNOWN", message: `步骤 ${step.id} 引用不存在的上传文件 ${binding.fromUpload + 1}`, stepId: step.id, inputName });
      }
      if (isInputRoleBinding(binding) && options.inputCount !== undefined && !inputRoleExists(binding.fromInput, options.inputCount)) {
        errors.push({ code: "WORKFLOW_STEP_INPUT_ROLE_UNKNOWN", message: `步骤 ${step.id} 引用不存在的输入 role ${binding.fromInput}`, stepId: step.id, inputName });
      }
    }
  }

  for (const exposed of draft.exposeOutputs) {
    if (!outputsByStep.get(exposed.fromStep)?.has(exposed.output) || !exposed.as.trim()) {
      errors.push({ code: "WORKFLOW_OUTPUT_BINDING_INVALID", message: `输出暴露无效: ${exposed.as || exposed.fromStep}` });
    }
  }

  const orderedStepIds = topologicalStepIds(draft.steps.map((step) => step.id), incomingCount, outgoing);
  if (orderedStepIds.length !== draft.steps.length) {
    errors.push({ code: "WORKFLOW_STEP_CYCLE", message: "步骤依赖存在环" });
  }

  return { errors, warnings: [], orderedStepIds };
}

export function findCompatibleOutputBinding(
  input: RuleInputSpec,
  upstreamSteps: GeneratedWorkflowStepDraft[],
  tools: AddedTool[],
  excludeStepId?: string
): { fromStep: string; output: string } | undefined {
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  for (let index = upstreamSteps.length - 1; index >= 0; index -= 1) {
    const step = upstreamSteps[index];
    if (!step || step.id === excludeStepId) continue;
    const tool = toolById.get(step.toolId);
    const output = readRuleOutputs(tool).find((candidate) => portsCompatible(input, candidate));
    if (output) return { fromStep: step.id, output: output.name };
  }
  return undefined;
}

export function portsCompatible(input: RuleInputSpec, output: RuleOutputSpec): boolean {
  return COMPATIBILITY_FIELDS.every((field) => {
    const inputValue = input[field];
    const outputValue = output[field];
    return !inputValue || !outputValue || inputValue === outputValue;
  });
}

export function describePortSpec(port: RuleInputSpec | RuleOutputSpec): string {
  const parts = [port.kind, port.mimeType, port.format, port.data, port.type].filter((value): value is string => Boolean(value));
  return parts.length > 0 ? parts.join(" · ") : "any file";
}

export function buildGeneratedWorkflowRunSpec({
  projectId,
  uploads,
  draft,
  tools,
  resourceBindings,
}: BuildGeneratedWorkflowRunSpecInput) {
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const normalizedStepIds = new Map(draft.steps.map((step) => [step.id, normalizeStepId(step.id)]));
  const runSpec: Record<string, unknown> = {
    projectId,
    pipelineId: GENERATED_TOOL_RUN_PIPELINE_ID,
    inputs: uploads.map((upload, index) => ({
      uploadId: upload.uploadId,
      filename: upload.filename,
      role: index === 0 ? "input" : `input_${index + 1}`,
    })),
  };
  if (resourceBindings && Object.keys(resourceBindings).length > 0) {
    runSpec.resourceBindings = resourceBindings;
  }
  runSpec.workflow = {
    steps: draft.steps.map((step) => {
      const tool = toolById.get(step.toolId);
      return {
        id: normalizeStepId(step.id),
        tool: {
          id: step.toolId,
          ...(tool?.ruleTemplate ? { ruleTemplate: tool.ruleTemplate } : {}),
        },
        inputs: normalizeStepInputBindings(step.inputs, normalizedStepIds),
        params: tool ? normalizeStepParams(step.params, readRuleParams(tool)) : {},
      };
    }),
    exposeOutputs: draft.exposeOutputs.map((output) => ({
      fromStep: normalizedStepIds.get(output.fromStep) || normalizeStepId(output.fromStep),
      output: output.output,
      as: output.as,
    })),
  };
  return runSpec;
}

function normalizeRuleInputSpec(item: Record<string, unknown>, capabilitySlot?: ToolCapabilitySlot): RuleInputSpec {
  const name = String(item.name || "").trim();
  return {
    name,
    required: item.required !== false && capabilitySlot?.required !== false,
    ...readPortCompatibility(item, capabilitySlot),
  };
}

function normalizeRuleOutputSpec(item: Record<string, unknown>, capabilitySlot?: ToolCapabilitySlot): RuleOutputSpec {
  return {
    name: String(item.name || "").trim(),
    ...readPortCompatibility(item, capabilitySlot),
  };
}

function readPortCompatibility(
  item: Record<string, unknown>,
  capabilitySlot?: ToolCapabilitySlot
): Partial<Record<RulePortCompatibilityField, string>> {
  const spec: Partial<Record<RulePortCompatibilityField, string>> = {};
  for (const field of COMPATIBILITY_FIELDS) {
    const value = stringValue(item[field]) || stringValue(capabilitySlot?.[field]);
    if (value) spec[field] = value;
  }
  if (!spec.format) {
    const value = stringValue(item.edamFormat) || stringValue(capabilitySlot?.edamFormat);
    if (value) spec.format = value;
  }
  if (!spec.data) {
    const value = stringValue(item.edamData) || stringValue(capabilitySlot?.edamData);
    if (value) spec.data = value;
  }
  return spec;
}

function findCapabilitySlot(
  tool: AddedTool | undefined,
  direction: "inputs" | "outputs",
  name: string
): ToolCapabilitySlot | undefined {
  const normalizedName = name.trim();
  if (!normalizedName) return undefined;
  for (const capability of tool?.capabilities || []) {
    for (const slot of capability[direction] || []) {
      if (slot.name === normalizedName) return slot;
    }
  }
  return undefined;
}

function stepInputBindingIsCompatible(
  inputName: string,
  binding: { fromStep: string; output: string },
  stepToolId: string,
  sourceToolId: string,
  toolById: Map<string, AddedTool>
): boolean {
  const input = readRuleInputs(toolById.get(stepToolId)).find((candidate) => candidate.name === inputName);
  const output = readRuleOutputs(toolById.get(sourceToolId)).find((candidate) => candidate.name === binding.output);
  return !input || !output || portsCompatible(input, output);
}

function normalizeRuleParam(name: string, raw: unknown): RuleParamSpec | null {
  const normalizedName = String(name || "").trim();
  if (!normalizedName) return null;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const item = raw as Record<string, unknown>;
    const defaultValue = normalizeParamValue(item.default);
    const enumValues = Array.isArray(item.enum)
      ? item.enum.map(normalizeParamValue).filter((value): value is GeneratedWorkflowParamValue => value !== undefined)
      : undefined;
    return {
      name: normalizedName,
      type: String(item.type || ""),
      title: String(item.title || ""),
      description: String(item.description || ""),
      ...(defaultValue !== undefined ? { default: defaultValue } : {}),
      ...(enumValues && enumValues.length > 0 ? { enum: enumValues } : {}),
      ...(typeof item.minimum === "number" ? { minimum: item.minimum } : {}),
      ...(typeof item.maximum === "number" ? { maximum: item.maximum } : {}),
    };
  }
  const value = normalizeParamValue(raw);
  return value === undefined ? { name: normalizedName } : { name: normalizedName, default: value };
}

function normalizeStepParams(params: GeneratedWorkflowStepParams, specs: RuleParamSpec[]) {
  const specNames = new Set(specs.map((spec) => spec.name));
  return Object.fromEntries(
    Object.entries(params)
      .filter(([name, value]) => specNames.has(name) && value !== "")
      .map(([name, value]) => [name, value])
  );
}

function normalizeParamValue(value: unknown): GeneratedWorkflowParamValue | undefined {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  return undefined;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function isStepBinding(binding: GeneratedWorkflowInputBinding | undefined): binding is { fromStep: string; output: string } {
  return Boolean(binding && typeof binding === "object" && "fromStep" in binding && "output" in binding);
}

function isUploadBinding(binding: GeneratedWorkflowInputBinding | undefined): binding is { fromUpload: number } {
  return Boolean(binding && typeof binding === "object" && "fromUpload" in binding);
}

function isInputRoleBinding(binding: GeneratedWorkflowInputBinding | undefined): binding is { fromInput: string } {
  return Boolean(binding && typeof binding === "object" && "fromInput" in binding);
}

function inputRoleExists(role: string, inputCount: number) {
  if (role === "input") return inputCount > 0;
  const match = /^input_(\d+)$/.exec(role);
  if (!match) return false;
  const index = Number(match[1]);
  return index >= 2 && index <= inputCount;
}

function normalizeStepInputBindings(
  inputs: Record<string, GeneratedWorkflowInputBinding>,
  normalizedStepIds: Map<string, string>
) {
  return Object.fromEntries(
    Object.entries(inputs).map(([name, binding]) => {
      if (isStepBinding(binding)) {
        return [name, { ...binding, fromStep: normalizedStepIds.get(binding.fromStep) || normalizeStepId(binding.fromStep) }];
      }
      return [name, binding];
    })
  );
}

function topologicalStepIds(stepIds: string[], incomingCount: Map<string, number>, outgoing: Map<string, string[]>) {
  const queue = stepIds.filter((id) => (incomingCount.get(id) || 0) === 0);
  const ordered: string[] = [];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    ordered.push(current);
    for (const next of outgoing.get(current) || []) {
      const count = (incomingCount.get(next) || 0) - 1;
      incomingCount.set(next, count);
      if (count === 0) queue.push(next);
    }
  }
  return ordered;
}
