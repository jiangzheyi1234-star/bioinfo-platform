import type { GeneratedWorkflowValidationIssue } from "./generated-workflow-model";

const RULE_ACTION_FIELDS = ["commandTemplate", "wrapper", "script", "module"] as const;

export type RuleActionField = (typeof RULE_ACTION_FIELDS)[number];

export function ruleActionFields(ruleTemplate: Record<string, unknown>): RuleActionField[] {
  return RULE_ACTION_FIELDS.filter((field) =>
    field === "module"
      ? Boolean(ruleTemplate.module && typeof ruleTemplate.module === "object" && !Array.isArray(ruleTemplate.module))
      : typeof ruleTemplate[field] === "string" && ruleTemplate[field].trim().length > 0
  );
}

export function validateRuleActionContract({
  ruleTemplate,
  stepId,
}: {
  ruleTemplate: Record<string, unknown>;
  stepId: string;
}): GeneratedWorkflowValidationIssue[] {
  const actions = ruleActionFields(ruleTemplate);
  if (actions.length === 0) {
    return [{ code: "WORKFLOW_RULE_ACTION_REQUIRED", message: `步骤 ${stepId} 未声明 rule action`, stepId }];
  }
  if (actions.length > 1) {
    return [{ code: "WORKFLOW_RULE_ACTION_CONFLICT", message: `步骤 ${stepId} 同时声明多个 rule action: ${actions.join(", ")}`, stepId }];
  }
  return [];
}
