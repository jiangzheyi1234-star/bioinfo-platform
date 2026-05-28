import type { AddedTool } from "./tools-page-model";
import type { WorkflowResourceBindings, WorkflowUpload } from "./workflows-page-model";

export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";

export type GeneratedWorkflowInputBinding =
  | { fromUpload: number }
  | { fromInput: string }
  | { fromStep: string; output: string }
  | string;

export type GeneratedWorkflowStepDraft = {
  id: string;
  toolId: string;
  inputs: Record<string, GeneratedWorkflowInputBinding>;
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

type RuleInputSpec = {
  name: string;
  required?: boolean;
};

type RuleOutputSpec = {
  name: string;
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
    .map((item) => ({
      name: String(item.name || "").trim(),
      required: item.required !== false,
    }))
    .filter((item) => item.name.length > 0);
}

export function readRuleOutputs(tool: AddedTool | undefined): RuleOutputSpec[] {
  const outputs = (tool?.ruleTemplate as { outputs?: unknown } | undefined)?.outputs;
  if (!Array.isArray(outputs)) return [];
  return outputs
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((item) => ({ name: String(item.name || "").trim() }))
    .filter((item) => item.name.length > 0);
}

export function createGeneratedWorkflowDraft(tools: AddedTool[]): GeneratedWorkflowDraft {
  const first = tools[0];
  return {
    steps: first ? [createStepDraft(first, [])] : [],
    exposeOutputs: [],
  };
}

export function createStepDraft(tool: AddedTool, existingIds: string[]): GeneratedWorkflowStepDraft {
  const stepId = uniqueStepId(tool.name || tool.id, existingIds);
  const inputs = Object.fromEntries(
    readRuleInputs(tool).map((input, index) => [input.name, index === 0 ? { fromUpload: 0 } : ""])
  );
  return {
    id: stepId,
    toolId: tool.id,
    inputs,
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
    outputsByStep.set(step.id, new Set(readRuleOutputs(tool).map((output) => output.name)));
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
