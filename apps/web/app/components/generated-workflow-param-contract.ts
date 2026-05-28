import type {
  GeneratedWorkflowParamValue,
  GeneratedWorkflowStepParams,
  GeneratedWorkflowValidationIssue,
  RuleParamSpec,
} from "./generated-workflow-model";

const PARAM_TOKEN_RE = /\{params\.([A-Za-z_][A-Za-z0-9_]*)(?::q)?\}/g;

export function commandParamNames(ruleTemplate: Record<string, unknown>): string[] {
  const commandTemplate = typeof ruleTemplate.commandTemplate === "string" ? ruleTemplate.commandTemplate : "";
  return Array.from(new Set(Array.from(commandTemplate.matchAll(PARAM_TOKEN_RE)).map((match) => match[1])));
}

export function validateStepParamBindings({
  stepId,
  params,
  paramSpecs,
  ruleTemplate,
}: {
  stepId: string;
  params: GeneratedWorkflowStepParams;
  paramSpecs: RuleParamSpec[];
  ruleTemplate: Record<string, unknown>;
}): GeneratedWorkflowValidationIssue[] {
  const specByName = new Map(paramSpecs.map((spec) => [spec.name, spec]));
  const issues: GeneratedWorkflowValidationIssue[] = [];
  for (const name of commandParamNames(ruleTemplate)) {
    const spec = specByName.get(name);
    if (!spec) {
      issues.push({
        code: "WORKFLOW_STEP_PARAM_UNKNOWN",
        message: `参数 ${stepId}.${name} 未在 RuleSpec params 中声明`,
        stepId,
      });
      continue;
    }
    if (paramIsMissing(params[name], spec)) {
      issues.push({
        code: "WORKFLOW_STEP_PARAM_REQUIRED",
        message: `步骤 ${stepId} 缺少参数 ${name}`,
        stepId,
      });
    }
  }
  return issues;
}

function paramIsMissing(value: GeneratedWorkflowParamValue | undefined, spec: RuleParamSpec): boolean {
  return (value === undefined || value === "") && spec.default === undefined;
}
