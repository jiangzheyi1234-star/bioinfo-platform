import { MarkerType, type Connection, type Edge } from "@xyflow/react";

import type { AddedTool } from "./tools-page-model";
import type { GeneratedWorkflowGraphDraft } from "./generated-workflow-model";

type GraphNode = GeneratedWorkflowGraphDraft["nodes"][number];
type GraphEdge = GeneratedWorkflowGraphDraft["edges"][number];

export type WorkflowRuleFlowEdge = Edge<Record<string, unknown>>;
export type WorkflowGraphConnection = {
  from: { nodeId: string; port: string };
  to: { nodeId: string; port: string };
};
export type WorkflowGraphNodeSearchMatch = {
  label: string;
  matchedField: "node" | "tool" | "package";
  nodeId: string;
};

export function buildFlowEdges(edges: GraphEdge[]): WorkflowRuleFlowEdge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.from.nodeId,
    sourceHandle: edge.from.port,
    target: edge.to.nodeId,
    targetHandle: edge.to.port,
    data: edge.audit ? { auditSource: edge.audit.source, auditReason: edge.audit.reason } : {},
    markerEnd: { type: MarkerType.ArrowClosed, color: "rgb(37 99 235)" },
    style: { stroke: "rgb(37 99 235)", strokeWidth: 2 },
    type: "smoothstep",
  }));
}

export function reactFlowConnectionToGraphConnection(
  connection: Connection | WorkflowRuleFlowEdge
): WorkflowGraphConnection | null {
  if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) return null;
  return {
    from: { nodeId: connection.source, port: connection.sourceHandle },
    to: { nodeId: connection.target, port: connection.targetHandle },
  };
}

export function matchedGraphNodeIds({
  nodes,
  query,
  toolByRevisionId,
}: {
  nodes: GraphNode[];
  query: string;
  toolByRevisionId: Map<string, AddedTool>;
}) {
  return new Set(matchedGraphNodeSearchMatches({ nodes, query, toolByRevisionId }).map((match) => match.nodeId));
}

export function matchedGraphNodeSearchMatches({
  nodes,
  query,
  toolByRevisionId,
}: {
  nodes: GraphNode[];
  query: string;
  toolByRevisionId: Map<string, AddedTool>;
}): WorkflowGraphNodeSearchMatch[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return [];
  return nodes
    .map((node): WorkflowGraphNodeSearchMatch | null => {
      const tool = toolByRevisionId.get(node.toolRevisionId);
      const fields: Array<{ field: WorkflowGraphNodeSearchMatch["matchedField"]; value?: string }> = [
        { field: "node", value: node.id },
        { field: "node", value: node.toolRevisionId },
        { field: "tool", value: tool?.name },
        { field: "package", value: tool?.packageSpec },
      ];
      const matched = fields.find(({ value }) => value?.toLowerCase().includes(normalizedQuery));
      if (!matched) return null;
      return {
        label: tool?.name || node.id,
        matchedField: matched.field,
        nodeId: node.id,
      };
    })
    .filter((match): match is WorkflowGraphNodeSearchMatch => Boolean(match));
}
