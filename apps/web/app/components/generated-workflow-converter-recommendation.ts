import type { AddedTool } from "./tools-page-model";
import { matchedPortCompatibilityFields } from "./generated-workflow-port-contract";
import {
  createStepParams,
  generatedWorkflowDraftToGraphDraft,
  graphDraftToGeneratedWorkflowDraft,
  portCompatibilityScore,
  readRuleInputs,
  readRuleOutputs,
  uniqueStepId,
  workflowToolRevisionId,
  type GeneratedWorkflowGraphDraft,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";
import type { RulePortEdgeAudit } from "./generated-workflow-recommendation-contract";
import { displayRuleTemplateForTool, ruleSpecReadinessForTool } from "./tool-rule-readiness";

export type RulePortConverterCandidate = {
  converterToolRevisionId: string;
  converterToolName: string;
  confirmationRequired: boolean;
  insertionMode: "explicit-user-confirmed";
  autoInsertionBlockedReasons: string[];
  hardChecks: string[];
  evidence: string[];
  inputName: string;
  outputName: string;
  inputScore: number;
  outputScore: number;
  totalScore: number;
  operation?: string;
  workflowStage?: string;
  reason: string;
};

export const CONVERTER_CONFIRMATION_REQUIRED_REASON = "confirmation-required";
export const CONVERTER_GRAPH_MUTATION_REQUIRES_USER_ACTION_REASON = "graph-mutation-requires-user-action";
export const CONVERTER_TOOL_NOT_WORKFLOW_READY_REASON = "converter-tool-not-workflow-ready";
export const CONVERTER_DATABASE_RESOURCE_REQUIRED_REASON = "database-resource-required";
export const CONVERTER_PORT_CONTRACT_NOT_SATISFIED_REASON = "converter-port-contract-not-satisfied";

export type RulePortConverterInsertionRequest = {
  sourceStepId: string;
  sourceOutput: string;
  targetStepId: string;
  targetInput: string;
  converter: RulePortConverterCandidate;
};

export function findOneHopPortConverters({
  input,
  output,
  tools,
  excludeToolRevisionIds = [],
}: {
  input: RuleInputSpec;
  output: RuleOutputSpec;
  tools: AddedTool[];
  excludeToolRevisionIds?: string[];
}): RulePortConverterCandidate[] {
  const excluded = new Set(excludeToolRevisionIds.filter(Boolean));
  return tools
    .filter((tool) => ruleSpecReadinessForTool(tool).workflowReady)
    .filter((tool) => !excluded.has(workflowToolRevisionId(tool)))
    .flatMap((tool) => converterCandidatesForTool({ input, output, tool }))
    .sort((left, right) => right.totalScore - left.totalScore || left.converterToolName.localeCompare(right.converterToolName));
}

export function blockedOneHopPortConverterReasons({
  input,
  output,
  tool,
}: {
  input: RuleInputSpec;
  output: RuleOutputSpec;
  tool: AddedTool;
}): string[] {
  const toolBlockers = converterToolBlockedReasons(tool);
  if (toolBlockers.length > 0) return toolBlockers;
  return converterCandidatesForTool({ input, output, tool }).length > 0
    ? []
    : [CONVERTER_PORT_CONTRACT_NOT_SATISFIED_REASON];
}

function converterCandidatesForTool({
  input,
  output,
  tool,
}: {
  input: RuleInputSpec;
  output: RuleOutputSpec;
  tool: AddedTool;
}): RulePortConverterCandidate[] {
  const converterInputs = readRuleInputs(tool);
  const converterOutputs = readRuleOutputs(tool);
  const revisionId = workflowToolRevisionId(tool);
  if (!revisionId || converterInputs.length === 0 || converterOutputs.length === 0) return [];
  if (converterToolBlockedReasons(tool).length > 0) return [];

  const metadata = converterToolMetadata(tool);
  const requiredInputs = converterInputs.filter((candidate) => candidate.required !== false);
  const candidates: RulePortConverterCandidate[] = [];
  for (const converterInput of converterInputs) {
    if (requiredInputs.some((candidate) => candidate.name !== converterInput.name)) continue;
    const inputScore = portCompatibilityScore(converterInput, output);
    if (inputScore === null) continue;
    if (!hasStrongPortEvidence(converterInput, output)) continue;
    for (const converterOutput of converterOutputs) {
      const outputScore = portCompatibilityScore(input, converterOutput);
      if (outputScore === null) continue;
      if (!hasStrongPortEvidence(input, converterOutput)) continue;
      const evidence = converterEvidence({ converterInput, converterOutput, inputScore, metadata, outputScore });
      candidates.push({
        converterToolRevisionId: revisionId,
        converterToolName: tool.name || revisionId,
        confirmationRequired: true,
        insertionMode: "explicit-user-confirmed",
        autoInsertionBlockedReasons: [
          CONVERTER_CONFIRMATION_REQUIRED_REASON,
          CONVERTER_GRAPH_MUTATION_REQUIRES_USER_ACTION_REASON,
        ],
        hardChecks: [
          "workflow-ready-converter",
          "single-required-input",
          "converter-has-no-database-resource",
          "source-output-to-converter-input-strong-evidence",
          "converter-output-to-target-input-strong-evidence",
        ],
        evidence,
        inputName: converterInput.name,
        outputName: converterOutput.name,
        inputScore,
        outputScore,
        totalScore: inputScore + outputScore + converterSpecificityScore(metadata),
        operation: metadata.operation,
        workflowStage: metadata.workflowStage,
        reason: evidence.join("；"),
      });
    }
  }
  return candidates;
}

function hasStrongPortEvidence(input: RuleInputSpec, output: RuleOutputSpec): boolean {
  return matchedPortCompatibilityFields(input, output).some((field) => field !== "type");
}

function requiresDatabaseResource(tool: AddedTool): boolean {
  const template = displayRuleTemplateForTool(tool) as Record<string, unknown>;
  const resources = objectValue(template.resources);
  return Object.values(resources).some((resource) => objectValue(resource).type === "database");
}

function converterToolBlockedReasons(tool: AddedTool): string[] {
  if (!ruleSpecReadinessForTool(tool).workflowReady) return [CONVERTER_TOOL_NOT_WORKFLOW_READY_REASON];
  if (requiresDatabaseResource(tool)) return [CONVERTER_DATABASE_RESOURCE_REQUIRED_REASON];
  return [];
}

export function buildConverterInsertionPatch({
  converterTool,
  graphDraft,
  request,
}: {
  converterTool: AddedTool;
  graphDraft: GeneratedWorkflowGraphDraft;
  request: RulePortConverterInsertionRequest;
}): GeneratedWorkflowGraphDraft {
  const draft = graphDraftToGeneratedWorkflowDraft(graphDraft);
  const sourceStep = draft.steps.find((step) => step.id === request.sourceStepId);
  const targetStep = draft.steps.find((step) => step.id === request.targetStepId);
  if (!sourceStep || !targetStep) {
    throw new Error("WORKFLOW_CONVERTER_INSERTION_STEP_UNKNOWN");
  }
  const converterToolRevisionId = workflowToolRevisionId(converterTool);
  if (!converterToolRevisionId || converterToolRevisionId !== request.converter.converterToolRevisionId) {
    throw new Error("WORKFLOW_CONVERTER_INSERTION_TOOL_MISMATCH");
  }
  const targetBinding = targetStep.inputs?.[request.targetInput];
  if (targetBinding && typeof targetBinding === "object" && "fromStep" in targetBinding) {
    const existingConverterStep = draft.steps.find((step) => step.id === targetBinding.fromStep);
    const existingConverterInput = existingConverterStep?.inputs?.[request.converter.inputName];
    if (
      existingConverterStep?.toolRevisionId === converterToolRevisionId
      && targetBinding.output === request.converter.outputName
      && existingConverterInput
      && typeof existingConverterInput === "object"
      && "fromStep" in existingConverterInput
      && existingConverterInput.fromStep === request.sourceStepId
      && existingConverterInput.output === request.sourceOutput
    ) {
      throw new Error("WORKFLOW_CONVERTER_INSERTION_ALREADY_APPLIED");
    }
  }
  const converterStepId = uniqueStepId(
    `${request.converter.converterToolName || converterTool.name || "converter"}_converter`,
    draft.steps.map((step) => step.id)
  );
  const converterStep = {
    id: converterStepId,
    toolRevisionId: converterToolRevisionId,
    inputs: {
      [request.converter.inputName]: {
        fromStep: request.sourceStepId,
        output: request.sourceOutput,
        audit: converterEdgeAudit(request.converter, "source-output-to-converter-input"),
      },
    },
    metadata: {},
    params: createStepParams(converterTool),
    runtime: {},
  };
  const targetIndex = draft.steps.findIndex((step) => step.id === targetStep.id);
  const updatedSteps = draft.steps.map((step) =>
    step.id === targetStep.id
      ? {
          ...step,
          inputs: {
            ...step.inputs,
            [request.targetInput]: {
              fromStep: converterStepId,
              output: request.converter.outputName,
              audit: converterEdgeAudit(request.converter, "converter-output-to-target-input"),
            },
          },
        }
      : step
  );
  updatedSteps.splice(targetIndex, 0, converterStep);
  return generatedWorkflowDraftToGraphDraft({ ...draft, steps: updatedSteps });
}

function converterToolMetadata(tool: AddedTool): { operation?: string; workflowStage?: string } {
  const bundleSummary = tool.capabilityBundle?.selectionSummary;
  const template = displayRuleTemplateForTool(tool) as Record<string, unknown>;
  const templateMetadata = template.metadata && typeof template.metadata === "object" ? template.metadata as Record<string, unknown> : {};
  return {
    operation: stringValue(bundleSummary?.operation) || stringValue(tool.capabilities?.[0]?.operation) || stringValue(templateMetadata.operation),
    workflowStage: stringValue(bundleSummary?.workflowStage) || stringValue(templateMetadata.workflowStage),
  };
}

function converterSpecificityScore(metadata: { operation?: string; workflowStage?: string }) {
  const text = `${metadata.operation || ""} ${metadata.workflowStage || ""}`.toLowerCase();
  if (/(convert|conversion|format|transform|normalize|sort|index)/.test(text)) return 3;
  return 0;
}

function converterEvidence({
  converterInput,
  converterOutput,
  inputScore,
  metadata,
  outputScore,
}: {
  converterInput: RuleInputSpec;
  converterOutput: RuleOutputSpec;
  inputScore: number;
  metadata: { operation?: string; workflowStage?: string };
  outputScore: number;
}) {
  const labels = [
    metadata.operation ? `operation ${metadata.operation}` : "",
    metadata.workflowStage ? `stage ${metadata.workflowStage}` : "",
  ].filter(Boolean);
  return [
    `上游输出可进入 ${converterInput.name}`,
    `${converterOutput.name} 可满足目标输入`,
    `score ${inputScore}+${outputScore}`,
    ...labels,
  ];
}

function converterEdgeAudit(converter: RulePortConverterCandidate, edge: string): RulePortEdgeAudit {
  const confidence = Math.min(0.95, Number((0.45 + Math.min(converter.totalScore, 20) * 0.02).toFixed(2)));
  return {
    source: "auto",
    decision: "recommended",
    hardChecks: ["one-hop-converter", edge, ...converter.hardChecks],
    evidence: [
      ...converter.evidence,
      `converterToolRevisionId ${converter.converterToolRevisionId}`,
      `converterInput ${converter.inputName}`,
      `converterOutput ${converter.outputName}`,
    ],
    confidence,
    reason: `一跳转换: ${converter.converterToolName}`,
  };
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
