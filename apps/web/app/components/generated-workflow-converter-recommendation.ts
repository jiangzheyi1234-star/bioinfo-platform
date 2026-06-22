import type { AddedTool } from "./tools-page-model";
import { matchedPortCompatibilityFields } from "./generated-workflow-port-contract";
import {
  portCompatibilityScore,
  readRuleInputs,
  readRuleOutputs,
  workflowToolRevisionId,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";
import { displayRuleTemplateForTool, ruleSpecReadinessForTool } from "./tool-rule-readiness";

export type RulePortConverterCandidate = {
  converterToolRevisionId: string;
  converterToolName: string;
  inputName: string;
  outputName: string;
  inputScore: number;
  outputScore: number;
  totalScore: number;
  operation?: string;
  workflowStage?: string;
  reason: string;
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

  const metadata = converterToolMetadata(tool);
  const candidates: RulePortConverterCandidate[] = [];
  for (const converterInput of converterInputs) {
    const inputScore = portCompatibilityScore(converterInput, output);
    if (inputScore === null) continue;
    if (matchedPortCompatibilityFields(converterInput, output).length === 0) continue;
    for (const converterOutput of converterOutputs) {
      const outputScore = portCompatibilityScore(input, converterOutput);
      if (outputScore === null) continue;
      if (matchedPortCompatibilityFields(input, converterOutput).length === 0) continue;
      candidates.push({
        converterToolRevisionId: revisionId,
        converterToolName: tool.name || revisionId,
        inputName: converterInput.name,
        outputName: converterOutput.name,
        inputScore,
        outputScore,
        totalScore: inputScore + outputScore + converterSpecificityScore(metadata),
        operation: metadata.operation,
        workflowStage: metadata.workflowStage,
        reason: converterReason({ converterInput, converterOutput, inputScore, metadata, outputScore }),
      });
    }
  }
  return candidates;
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

function converterReason({
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
  ].join("；");
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
