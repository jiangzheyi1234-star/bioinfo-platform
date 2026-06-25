import type { AddedTool } from "./tools-page-model";
import {
  findOneHopPortConverters,
  type RulePortConverterCandidate,
} from "./generated-workflow-converter-recommendation";
import {
  describePortSpec,
  portsCompatible,
  readRuleInputs,
  readRuleOutputs,
  workflowToolRevisionEntries,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowGraphPortRef,
  type RuleInputSpec,
  type RuleOutputSpec,
} from "./generated-workflow-model";

export type GeneratedWorkflowOutputPortCandidate = {
  value: string;
  label: string;
  stepId: string;
  output: string;
  port: RuleOutputSpec;
};

export type OutputConverterSuggestion = RulePortConverterCandidate & {
  sourceLabel: string;
  sourceOutput: string;
  sourceStepId: string;
  sourceValue: string;
};

export function converterSuggestionsForInput({
  candidates,
  input,
  nodeToolRevisionId,
  tools,
}: {
  candidates: GeneratedWorkflowOutputPortCandidate[];
  input: RuleInputSpec;
  nodeToolRevisionId: string;
  tools: AddedTool[];
}): OutputConverterSuggestion[] {
  return candidates
    .flatMap((candidate) =>
      findOneHopPortConverters({
        input,
        output: candidate.port,
        tools,
        excludeToolRevisionIds: [nodeToolRevisionId],
      }).map((converter) => ({
        ...converter,
        sourceLabel: candidate.label,
        sourceOutput: candidate.output,
        sourceStepId: candidate.stepId,
        sourceValue: candidate.value,
      }))
    )
    .sort((left, right) => right.totalScore - left.totalScore || left.sourceValue.localeCompare(right.sourceValue));
}

export function converterSuggestionsForConnection({
  connection,
  graphDraft,
  tools,
}: {
  connection: { from: GeneratedWorkflowGraphPortRef; to: GeneratedWorkflowGraphPortRef };
  graphDraft: GeneratedWorkflowGraphDraft;
  tools: AddedTool[];
}): OutputConverterSuggestion[] {
  const sourceNode = graphDraft.nodes.find((node) => node.id === connection.from.nodeId);
  const targetNode = graphDraft.nodes.find((node) => node.id === connection.to.nodeId);
  if (!sourceNode || !targetNode || sourceNode.id === targetNode.id) return [];
  if (wouldCreateCycle({ connection, graphDraft })) return [];

  const toolByRevisionId = new Map(workflowToolRevisionEntries(tools));
  const sourceTool = toolByRevisionId.get(sourceNode.toolRevisionId);
  const targetTool = toolByRevisionId.get(targetNode.toolRevisionId);
  const output = readRuleOutputs(sourceTool).find((port) => port.name === connection.from.port);
  const input = readRuleInputs(targetTool).find((port) => port.name === connection.to.port);
  if (!output || !input || portsCompatible(input, output)) return [];

  return converterSuggestionsForInput({
    candidates: [
      {
        value: `${sourceNode.id}.${output.name}`,
        label: `${sourceNode.id}.${output.name} · ${describePortSpec(output)}`,
        stepId: sourceNode.id,
        output: output.name,
        port: output,
      },
    ],
    input,
    nodeToolRevisionId: targetNode.toolRevisionId,
    tools,
  });
}

function wouldCreateCycle({
  connection,
  graphDraft,
}: {
  connection: { from: GeneratedWorkflowGraphPortRef; to: GeneratedWorkflowGraphPortRef };
  graphDraft: GeneratedWorkflowGraphDraft;
}) {
  const outgoing = new Map<string, Set<string>>();
  for (const node of graphDraft.nodes) {
    outgoing.set(node.id, new Set());
  }
  for (const edge of graphDraft.edges) {
    if (edge.to.nodeId === connection.to.nodeId && edge.to.port === connection.to.port) continue;
    outgoing.get(edge.from.nodeId)?.add(edge.to.nodeId);
  }
  outgoing.get(connection.from.nodeId)?.add(connection.to.nodeId);
  const stack = [connection.to.nodeId];
  const visited = new Set<string>();
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || visited.has(current)) continue;
    if (current === connection.from.nodeId) return true;
    visited.add(current);
    for (const next of outgoing.get(current) || []) {
      stack.push(next);
    }
  }
  return false;
}
