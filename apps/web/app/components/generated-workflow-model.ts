import type { AddedTool, ToolCapabilitySlot } from "./tools-page-model";
import type { WorkflowResourceBindings, WorkflowUpload } from "./workflows-page-model";

export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";

export type GeneratedWorkflowInputBinding =
  | { fromUpload: number }
  | { fromInput: string }
  | { fromStep: string; output: string }
  | string;
export type GeneratedWorkflowGraphInputBinding = Exclude<GeneratedWorkflowInputBinding, { fromStep: string; output: string }>;

export type GeneratedWorkflowParamValue = string | number | boolean;
export type GeneratedWorkflowStepParams = Record<string, GeneratedWorkflowParamValue>;
export type GeneratedWorkflowStepRuntime = {
  threads?: number;
  resources?: Record<string, string | number>;
  schedulerResources?: Record<string, string | number>;
  log?: string | Record<string, string>;
};

export type GeneratedWorkflowStepDraft = {
  id: string;
  toolId: string;
  inputs: Record<string, GeneratedWorkflowInputBinding>;
  params: GeneratedWorkflowStepParams;
  runtime: GeneratedWorkflowStepRuntime;
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

export type GeneratedWorkflowGraphPortRef = {
  nodeId: string;
  port: string;
};

export type GeneratedWorkflowGraphNode = {
  id: string;
  toolId: string;
  inputs: Record<string, GeneratedWorkflowGraphInputBinding>;
  params: GeneratedWorkflowStepParams;
  runtime: GeneratedWorkflowStepRuntime;
};

export type GeneratedWorkflowGraphEdge = {
  id: string;
  from: GeneratedWorkflowGraphPortRef;
  to: GeneratedWorkflowGraphPortRef;
};

export type GeneratedWorkflowGraphDraft = {
  nodes: GeneratedWorkflowGraphNode[];
  edges: GeneratedWorkflowGraphEdge[];
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
  draft: GeneratedWorkflowDraft | GeneratedWorkflowGraphDraft;
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
  temp?: boolean;
  protected?: boolean;
  directory?: boolean;
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
    .map((item, index) =>
      normalizeRuleInputSpec(item, capabilitySlotForRulePort(tool, "inputs", String(item.name || "").trim(), index))
    )
    .filter((item) => item.name.length > 0);
}

export function readRuleOutputs(tool: AddedTool | undefined): RuleOutputSpec[] {
  const outputs = (tool?.ruleTemplate as { outputs?: unknown } | undefined)?.outputs;
  if (!Array.isArray(outputs)) return [];
  return outputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item, index) =>
      normalizeRuleOutputSpec(item, capabilitySlotForRulePort(tool, "outputs", String(item.name || "").trim(), index))
    )
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

export function createGeneratedWorkflowGraphDraft(tools: AddedTool[]): GeneratedWorkflowGraphDraft {
  return generatedWorkflowDraftToGraphDraft(createGeneratedWorkflowDraft(tools));
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
    runtime: {},
  };
}

export function generatedWorkflowDraftToGraphDraft(draft: GeneratedWorkflowDraft): GeneratedWorkflowGraphDraft {
  const edges: GeneratedWorkflowGraphEdge[] = [];
  const nodes = draft.steps.map((step) => {
    const inputs: Record<string, GeneratedWorkflowGraphInputBinding> = {};
    for (const [inputName, binding] of Object.entries(step.inputs)) {
      if (isStepBinding(binding)) {
        const edge = {
          from: { nodeId: binding.fromStep, port: binding.output },
          to: { nodeId: step.id, port: inputName },
        };
        edges.push({ id: graphEdgeId(edge.from, edge.to, edges.length), ...edge });
      } else {
        inputs[inputName] = binding;
      }
    }
    return {
      id: step.id,
      toolId: step.toolId,
      inputs,
      params: { ...step.params },
      runtime: { ...step.runtime },
    };
  });
  return {
    nodes,
    edges,
    exposeOutputs: draft.exposeOutputs.map((output) => ({ ...output })),
  };
}

export function graphDraftToGeneratedWorkflowDraft(graphDraft: GeneratedWorkflowGraphDraft): GeneratedWorkflowDraft {
  const steps = graphDraft.nodes.map((node) => ({
    id: node.id,
    toolId: node.toolId,
    inputs: { ...node.inputs } as Record<string, GeneratedWorkflowInputBinding>,
    params: { ...node.params },
    runtime: { ...node.runtime },
  }));
  const stepById = new Map(steps.map((step) => [step.id, step]));
  for (const edge of graphDraft.edges) {
    const target = stepById.get(edge.to.nodeId);
    if (!target) continue;
    target.inputs[edge.to.port] = { fromStep: edge.from.nodeId, output: edge.from.port };
  }
  return {
    steps,
    exposeOutputs: graphDraft.exposeOutputs.map((output) => ({ ...output })),
  };
}

export function validateGeneratedWorkflowGraphDraft(
  graphDraft: GeneratedWorkflowGraphDraft,
  tools: AddedTool[],
  options: ValidateGeneratedWorkflowDraftOptions = {}
): GeneratedWorkflowValidation {
  return validateGeneratedWorkflowDraft(graphDraft, tools, options);
}

export function validateGeneratedWorkflowDraft(
  draft: GeneratedWorkflowDraft | GeneratedWorkflowGraphDraft,
  tools: AddedTool[],
  options: ValidateGeneratedWorkflowDraftOptions = {}
): GeneratedWorkflowValidation {
  const stepDraft = isGeneratedWorkflowGraphDraft(draft) ? graphDraftToGeneratedWorkflowDraft(draft) : draft;
  const errors: GeneratedWorkflowValidationIssue[] = [];
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const normalizedIds = new Map<string, string>();
  const outputsByStep = new Map<string, Set<string>>();
  const outgoing = new Map<string, string[]>();
  const incomingCount = new Map<string, number>();

  for (const step of stepDraft.steps) {
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

  for (const step of stepDraft.steps) {
    for (const [inputName, binding] of Object.entries(step.inputs)) {
      if (!isStepBinding(binding)) continue;
      const sourceStep = stepDraft.steps.find((item) => item.id === binding.fromStep);
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

  const exposedAliases = new Set<string>();
  for (const exposed of stepDraft.exposeOutputs) {
    const alias = exposed.as.trim();
    if (alias && exposedAliases.has(alias)) {
      errors.push({ code: "WORKFLOW_OUTPUT_ALIAS_DUPLICATE", message: `暴露输出名称重复: ${alias}` });
    }
    if (alias) exposedAliases.add(alias);
    if (!outputsByStep.get(exposed.fromStep)?.has(exposed.output) || !exposed.as.trim()) {
      errors.push({ code: "WORKFLOW_OUTPUT_BINDING_INVALID", message: `输出暴露无效: ${exposed.as || exposed.fromStep}` });
    }
  }

  const orderedStepIds = topologicalStepIds(stepDraft.steps.map((step) => step.id), incomingCount, outgoing);
  if (orderedStepIds.length !== stepDraft.steps.length) {
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
  const parts = [
    port.kind,
    port.mimeType,
    port.format,
    port.data,
    port.type,
    ...outputSemanticTags(port),
  ].filter((value): value is string => Boolean(value));
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
  if (isGeneratedWorkflowGraphDraft(draft)) {
    const normalizedNodeIds = new Map(draft.nodes.map((node) => [node.id, normalizeStepId(node.id)]));
    runSpec.workflow = {
      nodes: draft.nodes.map((node) => {
        const tool = toolById.get(node.toolId);
        return {
          id: normalizedNodeIds.get(node.id) || normalizeStepId(node.id),
          toolId: node.toolId,
          tool: {
            id: node.toolId,
            ...(tool?.ruleTemplate ? { ruleTemplate: tool.ruleTemplate } : {}),
          },
          inputs: normalizeStepInputBindings(node.inputs, normalizedNodeIds),
          params: tool ? normalizeStepParams(node.params, readRuleParams(tool)) : {},
          runtime: normalizeStepRuntime(node.runtime),
        };
      }),
      edges: draft.edges.map((edge) => ({
        from: {
          nodeId: normalizedNodeIds.get(edge.from.nodeId) || normalizeStepId(edge.from.nodeId),
          port: edge.from.port,
        },
        to: {
          nodeId: normalizedNodeIds.get(edge.to.nodeId) || normalizeStepId(edge.to.nodeId),
          port: edge.to.port,
        },
      })),
      outputs: draft.exposeOutputs.map((output) => ({
        from: {
          nodeId: normalizedNodeIds.get(output.fromStep) || normalizeStepId(output.fromStep),
          port: output.output,
        },
        as: output.as,
      })),
    };
    return runSpec;
  }
  const stepDraft = draft;
  const normalizedStepIds = new Map(stepDraft.steps.map((step) => [step.id, normalizeStepId(step.id)]));
  runSpec.workflow = {
    steps: stepDraft.steps.map((step) => {
      const tool = toolById.get(step.toolId);
      return {
        id: normalizeStepId(step.id),
        tool: {
          id: step.toolId,
          ...(tool?.ruleTemplate ? { ruleTemplate: tool.ruleTemplate } : {}),
        },
        inputs: normalizeStepInputBindings(step.inputs, normalizedStepIds),
        params: tool ? normalizeStepParams(step.params, readRuleParams(tool)) : {},
        runtime: normalizeStepRuntime(step.runtime),
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

export function isGeneratedWorkflowGraphDraft(
  draft: GeneratedWorkflowDraft | GeneratedWorkflowGraphDraft
): draft is GeneratedWorkflowGraphDraft {
  return "nodes" in draft && "edges" in draft;
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
    ...readOutputSemantics(item),
  };
}

function readOutputSemantics(item: Record<string, unknown>): Pick<RuleOutputSpec, "temp" | "protected" | "directory"> {
  return {
    ...(item.temp === true ? { temp: true } : {}),
    ...(item.protected === true ? { protected: true } : {}),
    ...(item.directory === true ? { directory: true } : {}),
  };
}

function outputSemanticTags(port: RuleInputSpec | RuleOutputSpec): string[] {
  const output = port as RuleOutputSpec;
  return [
    output.directory ? "directory" : "",
    output.protected ? "protected" : "",
    output.temp ? "temp" : "",
  ].filter(Boolean);
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

function capabilitySlotForRulePort(
  tool: AddedTool | undefined,
  direction: "inputs" | "outputs",
  name: string,
  fallbackIndex: number
): ToolCapabilitySlot | undefined {
  const normalizedName = name.trim();
  const slots = (tool?.capabilities || []).flatMap((capability) => capability[direction] || []);
  if (normalizedName) {
    const exact = slots.find((slot) => slot.name === normalizedName);
    if (exact) return exact;
  }
  const genericPrimaryName = ["primary", "tool_output", "output"].includes(normalizedName);
  const primary = slots.find((slot) => slot.primary === true);
  if (primary && (fallbackIndex === 0 || genericPrimaryName)) return primary;
  return slots[fallbackIndex];
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

function normalizeStepRuntime(runtime: GeneratedWorkflowStepRuntime | undefined) {
  const normalized: GeneratedWorkflowStepRuntime = {};
  if (runtime?.threads && Number.isInteger(runtime.threads) && runtime.threads > 0) {
    normalized.threads = runtime.threads;
  }
  const resources = normalizeRuntimeResources(runtime?.resources || runtime?.schedulerResources);
  if (Object.keys(resources).length > 0) {
    normalized.resources = resources;
  }
  const log = normalizeRuntimeLog(runtime?.log);
  if (log) {
    normalized.log = log;
  }
  return normalized;
}

function normalizeRuntimeResources(resources: GeneratedWorkflowStepRuntime["resources"] | undefined) {
  if (!resources) return {};
  return Object.fromEntries(
    Object.entries(resources)
      .map(([name, value]) => [name.trim(), value] as const)
      .filter(([name, value]) => Boolean(name) && (typeof value === "string" || typeof value === "number") && value !== "")
  );
}

function normalizeRuntimeLog(log: GeneratedWorkflowStepRuntime["log"] | undefined) {
  if (typeof log === "string") return log.trim();
  if (!log) return "";
  const entries = Object.entries(log)
    .map(([name, path]) => [name.trim(), path.trim()] as const)
    .filter(([name, path]) => Boolean(name) && Boolean(path));
  return entries.length > 0 ? Object.fromEntries(entries) : "";
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

function graphEdgeId(from: GeneratedWorkflowGraphPortRef, to: GeneratedWorkflowGraphPortRef, index: number) {
  return `${from.nodeId}.${from.port}->${to.nodeId}.${to.port}:${index}`;
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
