import { MarkerType, type Connection, type Edge } from "@xyflow/react";

import type { AddedTool } from "./tools-page-model";
import type { GeneratedWorkflowGraphDraft } from "./generated-workflow-model";
import type { WorkflowDesignSemanticPortEdgePlan, WorkflowDesignSemanticPortPlan } from "./workflow-design-draft-model";

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
export type WorkflowGraphSemanticEdgeStatus = "compatible" | "converter-needed" | "blocked" | "unknown";

export function buildFlowEdges(
  edges: GraphEdge[],
  semanticPortPlan?: WorkflowDesignSemanticPortPlan | null
): WorkflowRuleFlowEdge[] {
  const semanticIndex = semanticEdgePlanIndex(semanticPortPlan);
  return edges.map((edge) => {
    const semanticEdge = semanticEdgePlanForGraphEdge(semanticIndex, edge);
    const semanticProjection = semanticEdgeProjection(semanticEdge);
    return {
      id: edge.id,
      source: edge.from.nodeId,
      sourceHandle: edge.from.port,
      target: edge.to.nodeId,
      targetHandle: edge.to.port,
      data: {
        ...(edge.audit ? { auditSource: edge.audit.source, auditReason: edge.audit.reason } : {}),
        semanticReasonCode: semanticEdge?.recommendation.reasonCode || "",
        semanticStatus: semanticProjection.status,
      },
      label: semanticProjection.label,
      labelBgPadding: [6, 3],
      labelBgStyle: { fill: semanticProjection.labelBackground, fillOpacity: 0.92 },
      labelShowBg: true,
      labelStyle: { fill: semanticProjection.labelColor, fontSize: 11, fontWeight: 600 },
      markerEnd: { type: MarkerType.ArrowClosed, color: semanticProjection.stroke },
      style: {
        stroke: semanticProjection.stroke,
        strokeDasharray: semanticProjection.dashed ? "6 4" : undefined,
        strokeWidth: semanticProjection.strokeWidth,
      },
      type: "smoothstep",
    };
  });
}

export function semanticEdgeStatusForGraphEdge(
  edge: GraphEdge,
  semanticPortPlan?: WorkflowDesignSemanticPortPlan | null
): WorkflowGraphSemanticEdgeStatus {
  return semanticEdgeProjection(semanticEdgePlanForGraphEdge(semanticEdgePlanIndex(semanticPortPlan), edge)).status;
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

function semanticEdgePlanIndex(semanticPortPlan?: WorkflowDesignSemanticPortPlan | null) {
  const index = new Map<string, WorkflowDesignSemanticPortEdgePlan>();
  for (const edge of semanticPortPlan?.edges || []) {
    for (const key of semanticEdgePlanKeys(edge)) {
      index.set(key, edge);
    }
  }
  return index;
}

function semanticEdgePlanKeys(edge: WorkflowDesignSemanticPortEdgePlan) {
  const endpointKey = semanticEndpointKey(edge.from, edge.to);
  return edge.edgeId ? [edge.edgeId, endpointKey] : [endpointKey];
}

function semanticEdgeKey(edge: GraphEdge) {
  return edge.id;
}

function semanticEdgePlanForGraphEdge(
  index: Map<string, WorkflowDesignSemanticPortEdgePlan>,
  edge: GraphEdge
) {
  return index.get(semanticEdgeKey(edge)) || index.get(semanticEndpointKey(edge.from, edge.to)) || null;
}

function semanticEndpointKey(
  from: { nodeId: string; port: string },
  to: { nodeId: string; port: string }
) {
  return `${from.nodeId}.${from.port}->${to.nodeId}.${to.port}`;
}

function semanticEdgeProjection(edge: WorkflowDesignSemanticPortEdgePlan | null) {
  const status = semanticEdgeStatus(edge);
  if (status === "compatible") {
    return {
      dashed: false,
      label: "compatible",
      labelBackground: "rgb(236 253 245)",
      labelColor: "rgb(4 120 87)",
      status,
      stroke: "rgb(5 150 105)",
      strokeWidth: 2,
    };
  }
  if (status === "converter-needed") {
    return {
      dashed: true,
      label: "converter needed",
      labelBackground: "rgb(255 251 235)",
      labelColor: "rgb(180 83 9)",
      status,
      stroke: "rgb(217 119 6)",
      strokeWidth: 2.25,
    };
  }
  if (status === "blocked") {
    return {
      dashed: true,
      label: "blocked",
      labelBackground: "rgb(254 242 242)",
      labelColor: "rgb(185 28 28)",
      status,
      stroke: "rgb(220 38 38)",
      strokeWidth: 2.5,
    };
  }
  return {
    dashed: false,
    label: "semantic pending",
    labelBackground: "rgb(239 246 255)",
    labelColor: "rgb(29 78 216)",
    status,
    stroke: "rgb(37 99 235)",
    strokeWidth: 2,
  };
}

function semanticEdgeStatus(edge: WorkflowDesignSemanticPortEdgePlan | null): WorkflowGraphSemanticEdgeStatus {
  if (!edge) return "unknown";
  if (edge.decision.compatible || edge.recommendation.action === "connect") return "compatible";
  if (edge.converterCandidates.length > 0 || edge.recommendation.action === "insert-converter") return "converter-needed";
  return "blocked";
}
