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
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return new Set<string>();
  return new Set(
    nodes
      .filter((node) => {
        const tool = toolByRevisionId.get(node.toolRevisionId);
        return [node.id, node.toolRevisionId, tool?.name, tool?.packageSpec]
          .filter((value): value is string => typeof value === "string")
          .some((value) => value.toLowerCase().includes(normalizedQuery));
      })
      .map((node) => node.id)
  );
}
