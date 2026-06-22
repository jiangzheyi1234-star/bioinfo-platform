import type { AddedTool } from "./tools-page-model";
import {
  portsCompatible,
  readRuleInputs,
  readRuleOutputs,
  workflowToolRevisionEntries,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowGraphPortRef,
  type GeneratedWorkflowInputBinding,
} from "./generated-workflow-model";
import {
  explainPortRecommendation,
  manualEdgeAudit,
  type RulePortEdgeAudit,
} from "./generated-workflow-recommendation-contract";

export type GeneratedWorkflowPortConnection = {
  from: GeneratedWorkflowGraphPortRef;
  to: GeneratedWorkflowGraphPortRef;
};

export type GeneratedWorkflowPortConnectionDecision =
  | {
      ok: true;
      binding: Extract<GeneratedWorkflowInputBinding, { fromStep: string; output: string }>;
      reason: string;
    }
  | {
      ok: false;
      code: string;
      reason: string;
    };

export function evaluateGeneratedWorkflowPortConnection({
  connection,
  graphDraft,
  tools,
}: {
  connection: GeneratedWorkflowPortConnection;
  graphDraft: GeneratedWorkflowGraphDraft;
  tools: AddedTool[];
}): GeneratedWorkflowPortConnectionDecision {
  const sourceNode = graphDraft.nodes.find((node) => node.id === connection.from.nodeId);
  const targetNode = graphDraft.nodes.find((node) => node.id === connection.to.nodeId);
  if (!sourceNode || !targetNode) {
    return blocked("WORKFLOW_GRAPH_CONNECTION_NODE_UNKNOWN", "连接引用了未知节点");
  }
  if (sourceNode.id === targetNode.id) {
    return blocked("WORKFLOW_GRAPH_CONNECTION_SELF", "同一节点不能连接到自身");
  }

  const toolByRevisionId = new Map(workflowToolRevisionEntries(tools));
  const sourceTool = toolByRevisionId.get(sourceNode.toolRevisionId);
  const targetTool = toolByRevisionId.get(targetNode.toolRevisionId);
  const output = readRuleOutputs(sourceTool).find((port) => port.name === connection.from.port);
  const input = readRuleInputs(targetTool).find((port) => port.name === connection.to.port);
  if (!output) {
    return blocked("WORKFLOW_GRAPH_CONNECTION_OUTPUT_UNKNOWN", `未知输出端口 ${connection.from.nodeId}.${connection.from.port}`);
  }
  if (!input) {
    return blocked("WORKFLOW_GRAPH_CONNECTION_INPUT_UNKNOWN", `未知输入端口 ${connection.to.nodeId}.${connection.to.port}`);
  }
  if (!portsCompatible(input, output)) {
    const recommendation = explainPortRecommendation(input, output);
    return blocked("WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE", recommendation.reason);
  }
  if (wouldCreateCycle({ connection, graphDraft })) {
    return blocked("WORKFLOW_GRAPH_CONNECTION_CYCLE", "此连接会形成 DAG 环路");
  }

  const recommendation = explainPortRecommendation(input, output);
  return {
    ok: true,
    binding: {
      fromStep: connection.from.nodeId,
      output: connection.from.port,
      audit: manualCanvasEdgeAudit(recommendation),
    },
    reason: recommendation.reason,
  };
}

function blocked(code: string, reason: string): GeneratedWorkflowPortConnectionDecision {
  return { ok: false, code, reason };
}

function manualCanvasEdgeAudit(
  recommendation: ReturnType<typeof explainPortRecommendation>
): RulePortEdgeAudit {
  const base = manualEdgeAudit();
  return {
    ...base,
    confidence: recommendation.confidence,
    evidence: ["画布手动连线", ...recommendation.evidence],
    hardChecks: recommendation.hardChecks,
    reason: recommendation.reason,
  };
}

function wouldCreateCycle({
  connection,
  graphDraft,
}: {
  connection: GeneratedWorkflowPortConnection;
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
