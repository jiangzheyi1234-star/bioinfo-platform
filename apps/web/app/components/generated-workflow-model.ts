import type { AddedTool } from "./tools-page-model";
import { validateStepCommandPortBindings } from "./generated-workflow-command-contract";
import { validateStepParamBindings } from "./generated-workflow-param-contract";
import {
  COMPATIBILITY_FIELDS,
  readPortCompatibility,
} from "./generated-workflow-port-contract";
import {
  autoEdgeAudit,
  explainPortRecommendation,
  isAutoBindablePortRecommendation,
  manualEdgeAudit,
  type RulePortEdgeAudit,
} from "./generated-workflow-recommendation-contract";
import { validateRuleActionContract } from "./generated-workflow-rule-action-contract";
import { normalizeStepRuntime, validateStepRuntime } from "./generated-workflow-runtime-contract";
import type { WorkflowResourceBindings, WorkflowUpload } from "./workflows-page-model";
import {
  executableRuleTemplateForTool,
  ruleSpecReadinessForTool,
} from "./tool-rule-readiness";

export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";
export const GENERATED_WORKFLOW_RULE_CONTRACT_VERSION = "rule-contract-v1";

export type GeneratedWorkflowInputBinding =
  | { fromUpload: number }
  | { fromStep: string; output: string; audit?: RulePortEdgeAudit }
  | "";
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
  outputs: GeneratedWorkflowExposedOutput[];
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
  audit?: RulePortEdgeAudit;
};

export type GeneratedWorkflowGraphDraft = {
  nodes: GeneratedWorkflowGraphNode[];
  edges: GeneratedWorkflowGraphEdge[];
  outputs: GeneratedWorkflowExposedOutput[];
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
  path?: string;
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
  const inputs = (readToolRuleTemplate(tool) as { inputs?: unknown }).inputs;
  const ports = !Array.isArray(inputs) ? [] : inputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => normalizeRuleInputSpec(item))
    .filter((item) => item.name.length > 0);
  return ports;
}

export function readRuleOutputs(tool: AddedTool | undefined): RuleOutputSpec[] {
  const outputs = (readToolRuleTemplate(tool) as { outputs?: unknown }).outputs;
  const ports = !Array.isArray(outputs) ? [] : outputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => normalizeRuleOutputSpec(item))
    .filter((item) => item.name.length > 0);
  return ports;
}

export function readRuleParams(tool: AddedTool | undefined): RuleParamSpec[] {
  const params = (readToolRuleTemplate(tool) as { params?: unknown }).params;
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

export function createGeneratedWorkflowDraft(_tools: AddedTool[]): GeneratedWorkflowDraft {
  return {
    steps: [],
    outputs: [],
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
  const inputs: Record<string, GeneratedWorkflowInputBinding> = Object.fromEntries(
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
        edges.push({ id: graphEdgeId(edge.from, edge.to, edges.length), ...edge, audit: binding.audit || manualEdgeAudit() });
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
    outputs: draft.outputs.map((output) => ({ ...output })),
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
    target.inputs[edge.to.port] = { fromStep: edge.from.nodeId, output: edge.from.port, audit: edge.audit };
  }
  return {
    steps,
    outputs: graphDraft.outputs.map((output) => ({ ...output })),
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
  const outputSpecsByStep = new Map<string, Map<string, RuleOutputSpec>>();
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
    const readiness = ruleSpecReadinessForTool(tool);
    if (!readiness.workflowReady) {
      errors.push({ code: "WORKFLOW_TOOL_NOT_READY", message: `步骤 ${step.id} 的工具还不能加入流程`, stepId: step.id });
    }
    const inputs = readRuleInputs(tool);
    const outputs = readRuleOutputs(tool);
    const ruleTemplate = readToolRuleTemplate(tool);
    const declaredInputNames = new Set(inputs.map((input) => input.name));
    errors.push(...validateRuleActionContract({ stepId: step.id, ruleTemplate }));
    for (const inputName of Object.keys(step.inputs)) {
      if (!declaredInputNames.has(inputName)) {
        errors.push({
          code: "WORKFLOW_STEP_INPUT_PORT_UNKNOWN",
          message: `步骤 ${step.id} 绑定了未声明输入端口 ${inputName}`,
          stepId: step.id,
          inputName,
        });
      }
    }
    for (const output of outputs) {
      if (!output.path) {
        errors.push({
          code: "WORKFLOW_STEP_OUTPUT_PATH_REQUIRED",
          message: `步骤 ${step.id} 输出 ${output.name} 缺少 path`,
          stepId: step.id,
        });
      }
    }
    outputsByStep.set(step.id, new Set(outputs.map((output) => output.name)));
    outputSpecsByStep.set(step.id, new Map(outputs.map((output) => [output.name, output])));
    for (const input of inputs) {
      const binding = step.inputs[input.name];
      if (input.required && !binding) {
        errors.push({ code: "TOOL_INPUT_REQUIRED", message: `步骤 ${step.id} 缺少输入 ${input.name}`, stepId: step.id, inputName: input.name });
      }
    }
    errors.push(...validateStepCommandPortBindings({
      stepId: step.id,
      inputSpecs: inputs,
      inputBindings: step.inputs,
      outputSpecs: outputs,
      runtime: step.runtime,
      ruleTemplate,
    }));
    errors.push(...validateStepParamBindings({
      stepId: step.id,
      params: step.params || {},
      paramSpecs: readRuleParams(tool),
      ruleTemplate,
    }));
    errors.push(...validateStepRuntime(step.id, step.runtime));
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
    }
  }

  const orderedStepIds = topologicalStepIds(stepDraft.steps.map((step) => step.id), incomingCount, outgoing);
  const exposedAliases = new Set<string>();
  if (stepDraft.outputs.length === 0) {
    validateDefaultExposedOutputs(stepDraft, outputSpecsByStep, orderedStepIds, errors);
  } else {
    for (const exposed of stepDraft.outputs) {
      const alias = exposed.as.trim();
      if (alias && exposedAliases.has(alias)) {
        errors.push({ code: "WORKFLOW_OUTPUT_ALIAS_DUPLICATE", message: `暴露输出名称重复: ${alias}` });
      }
      if (alias) exposedAliases.add(alias);
      const outputSpec = outputSpecsByStep.get(exposed.fromStep)?.get(exposed.output);
      if (!outputSpec || !exposed.as.trim()) {
        errors.push({ code: "WORKFLOW_OUTPUT_BINDING_INVALID", message: `输出暴露无效: ${exposed.as || exposed.fromStep}` });
      } else if (!outputIsExposable(outputSpec)) {
        errors.push({
          code: "WORKFLOW_OUTPUT_TEMP_EXPOSED",
          message: `临时输出不能暴露为最终产物: ${exposed.fromStep}.${exposed.output}`,
          stepId: exposed.fromStep,
        });
      }
    }
  }

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
): { fromStep: string; output: string; audit?: RulePortEdgeAudit } | undefined {
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  let best: { fromStep: string; output: string; score: number; audit?: RulePortEdgeAudit } | undefined;
  for (let index = upstreamSteps.length - 1; index >= 0; index -= 1) {
    const step = upstreamSteps[index];
    if (!step || step.id === excludeStepId) continue;
    const tool = toolById.get(step.toolId);
    for (const output of readRuleOutputs(tool)) {
      const score = portCompatibilityScore(input, output);
      const recommendation = explainPortRecommendation(input, output);
      if (score !== null && isAutoBindablePortRecommendation(recommendation) && (!best || score > best.score)) {
        best = { fromStep: step.id, output: output.name, score, audit: autoEdgeAudit(recommendation) };
      }
    }
  }
  return best ? { fromStep: best.fromStep, output: best.output, audit: best.audit } : undefined;
}

export function portsCompatible(input: RuleInputSpec, output: RuleOutputSpec): boolean {
  return portCompatibilityScore(input, output) !== null;
}

export function portCompatibilityScore(input: RuleInputSpec, output: RuleOutputSpec): number | null {
  let score = 0;
  for (const field of COMPATIBILITY_FIELDS) {
    const inputValue = input[field];
    const outputValue = output[field];
    if (inputValue && outputValue && inputValue !== outputValue) return null;
    if (inputValue && outputValue) score += 4;
    else if (inputValue || outputValue) score += 1;
  }
  return score;
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
      contractVersion: GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
      nodes: draft.nodes.map((node) => {
        const tool = toolById.get(node.toolId);
        return {
          id: normalizedNodeIds.get(node.id) || normalizeStepId(node.id),
          tool: {
            id: node.toolId,
            ...(tool ? { ruleTemplate: readToolRuleTemplate(tool) } : {}),
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
        audit: edge.audit,
      })),
      outputs: draft.outputs.map((output) => ({
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
          ...(tool ? { ruleTemplate: readToolRuleTemplate(tool) } : {}),
        },
        inputs: normalizeStepInputBindings(step.inputs, normalizedStepIds),
        params: tool ? normalizeStepParams(step.params, readRuleParams(tool)) : {},
        runtime: normalizeStepRuntime(step.runtime),
      };
    }),
    outputs: draft.outputs.map((output) => ({
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

export function readToolRuleTemplate(tool: AddedTool | undefined): Record<string, unknown> {
  return executableRuleTemplateForTool(tool);
}

function normalizeRuleInputSpec(item: Record<string, unknown>): RuleInputSpec {
  const name = String(item.name || "").trim();
  return {
    name,
    required: item.required !== false,
    ...readPortCompatibility(item),
  };
}

function normalizeRuleOutputSpec(item: Record<string, unknown>): RuleOutputSpec {
  return {
    name: String(item.name || "").trim(),
    ...(stringValue(item.path) ? { path: stringValue(item.path) } : {}),
    ...readPortCompatibility(item),
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

function outputIsExposable(output: RuleOutputSpec): boolean {
  return output.temp !== true;
}

function validateDefaultExposedOutputs(
  stepDraft: GeneratedWorkflowDraft,
  outputSpecsByStep: Map<string, Map<string, RuleOutputSpec>>,
  orderedStepIds: string[],
  errors: GeneratedWorkflowValidationIssue[]
) {
  const lastStepId = orderedStepIds[orderedStepIds.length - 1];
  const lastStep = stepDraft.steps.find((step) => step.id === lastStepId) || stepDraft.steps[stepDraft.steps.length - 1];
  if (!lastStep) return;
  for (const [outputName, outputSpec] of outputSpecsByStep.get(lastStep.id) || new Map()) {
    if (!outputIsExposable(outputSpec)) {
      errors.push({
        code: "WORKFLOW_OUTPUT_TEMP_EXPOSED",
        message: `临时输出不能暴露为最终产物: ${lastStep.id}.${outputName}`,
        stepId: lastStep.id,
      });
    }
  }
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
