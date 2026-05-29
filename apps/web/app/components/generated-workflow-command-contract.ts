import type {
  GeneratedWorkflowInputBinding,
  GeneratedWorkflowValidationIssue,
  RuleInputSpec,
  RuleOutputSpec,
} from "./generated-workflow-model";

const COMMAND_PORT_TOKEN_RE = /\{(input|output)\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}/g;

export type CommandPortReferences = {
  inputs: string[];
  outputs: string[];
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

export function validateStepCommandPortBindings({
  inputSpecs,
  inputBindings,
  outputSpecs,
  ruleTemplate,
  stepId,
}: {
  inputSpecs: RuleInputSpec[];
  inputBindings?: Record<string, GeneratedWorkflowInputBinding>;
  outputSpecs: RuleOutputSpec[];
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
  return issues;
}

function commandInputBindingIsBound(binding: GeneratedWorkflowInputBinding | undefined): boolean {
  if (!binding) return false;
  if (typeof binding === "string") return binding.trim().length > 0;
  if ("fromUpload" in binding) return Number.isInteger(binding.fromUpload) && binding.fromUpload >= 0;
  if ("fromInput" in binding) return binding.fromInput.trim().length > 0;
  return binding.fromStep.trim().length > 0 && binding.output.trim().length > 0;
}
