import type { RuleOutputSpec } from "./generated-workflow-model";
import { portCompatibilityDecision } from "./generated-workflow-port-contract";
import type { CapabilityBundleSummary, CapabilityGraphSemanticNode } from "./tools-page-model";
import type { WorkflowToolRecommendationItem, WorkflowToolRecommendations } from "./workflows-page-api";

export function workflowRecommendationsFromCapabilityGraph({
  graphEdges,
  outputPort,
  page,
  pageSize,
  profileNodes,
  query,
}: {
  graphEdges: Array<{ from: string; to: string; kind: string }>;
  outputPort: RuleOutputSpec;
  page: number;
  pageSize: number;
  profileNodes: CapabilityGraphSemanticNode[];
  query: string;
}): WorkflowToolRecommendations {
  const normalizedQuery = query.trim().toLowerCase();
  const boundedPage = Math.max(1, page || 1);
  const boundedPageSize = Math.max(1, Math.min(pageSize || 5, 100));
  const inputPortsByProfileNode = capabilityInputPortsByProfileNode(profileNodes, graphEdges);
  const items = profileNodes
    .filter(
      (node) =>
        node.kind === "ToolProfile" &&
        node.agentSelectable === true &&
        node.toolRevisionId &&
        node.capabilityBundle?.capabilityId
    )
    .filter((node) => !normalizedQuery || capabilityNodeText(node).includes(normalizedQuery))
    .flatMap((node) =>
      (inputPortsByProfileNode.get(node.id) || []).flatMap((inputPort) => {
        const decision = portCompatibilityDecision(capabilityPortSpec(inputPort), outputPort);
        if (!decision.compatible) return [];
        const matchedFields = decision.matchedFields.filter((field) => field !== "type");
        if (matchedFields.length === 0) return [];
        return [
          capabilityGraphRecommendation({
            advisoryChecks: decision.advisoryChecks,
            advisoryFields: decision.advisoryFields,
            capabilityBundle: node.capabilityBundle,
            hardChecks: decision.hardChecks,
            inputPort,
            matchedFields,
            profileNode: node,
          }),
        ];
      })
    )
    .sort((left, right) => right.confidence - left.confidence || recommendationName(left).localeCompare(recommendationName(right)));
  const offset = (boundedPage - 1) * boundedPageSize;
  return {
    items: items.slice(offset, offset + boundedPageSize),
    query: normalizedQuery,
    total: items.length,
    page: boundedPage,
    pageSize: boundedPageSize,
    hasMore: offset + boundedPageSize < items.length,
  };
}

function capabilityInputPortsByProfileNode(
  nodes: CapabilityGraphSemanticNode[],
  edges: Array<{ from: string; to: string; kind: string }>
) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const result = new Map<string, CapabilityGraphSemanticNode[]>();
  edges
    .filter((edge) => edge.kind === "consumes")
    .forEach((edge) => {
      const port = byId.get(edge.to);
      if (!port || port.kind !== "InputPort") return;
      result.set(edge.from, [...(result.get(edge.from) || []), port]);
    });
  return result;
}

function capabilityPortSpec(inputPort: CapabilityGraphSemanticNode) {
  return {
    type: String(inputPort.type || ""),
    kind: String(inputPort.kindLabel || ""),
    mimeType: String(inputPort.mimeType || ""),
    data: String(inputPort.data || ""),
    format: String(inputPort.format || ""),
    operation: String(inputPort.operation || ""),
    resource: String(inputPort.resource || ""),
  };
}

function capabilityGraphRecommendation({
  advisoryChecks,
  advisoryFields,
  capabilityBundle,
  hardChecks,
  inputPort,
  matchedFields,
  profileNode,
}: {
  advisoryChecks: string[];
  advisoryFields: string[];
  capabilityBundle?: CapabilityBundleSummary;
  hardChecks: string[];
  inputPort: CapabilityGraphSemanticNode;
  matchedFields: string[];
  profileNode: CapabilityGraphSemanticNode;
}): WorkflowToolRecommendationItem {
  const profileId = String(profileNode.profileId || "").trim();
  const toolRevisionId = String(capabilityBundle?.toolRevisionId || profileNode.toolRevisionId || "").trim();
  const capabilityId = String(capabilityBundle?.capabilityId || profileNode.capabilityId || "").trim();
  return {
    decision: "recommended",
    candidate: {
      candidateId: profileNode.id,
      candidateKind: "capability-bundle",
      profileId,
      capabilityId,
      capabilityBundleVersion: capabilityBundle?.capabilityBundleVersion,
      toolNames: [profileId].filter(Boolean),
    },
    executionGate: {
      currentState: "WorkflowReady",
      requiredState: "WorkflowReady",
      canAddStep: true,
      nextAction: "add-step",
      reason: "WORKFLOW_TOOL_READY",
      sourceOfTruth: "capability-bundle-v1",
      toolRevisionId,
      capabilityId,
    },
    capabilityBundle,
    inputPort: {
      name: String(inputPort.name || ""),
      required: inputPort.required,
      type: String(inputPort.type || ""),
      kind: String(inputPort.kindLabel || inputPort.kind || ""),
      mimeType: String(inputPort.mimeType || ""),
      data: String(inputPort.data || ""),
      format: String(inputPort.format || ""),
      operation: String(inputPort.operation || ""),
      resource: String(inputPort.resource || ""),
    },
    matchedFields,
    advisoryFields,
    confidence: recommendationConfidence(matchedFields, advisoryFields),
    hardChecks: ["capability-bundle-v1 agentSelectable=true", ...hardChecks],
    advisoryChecks,
    evidence: [
      `capabilityId ${capabilityId}`,
      `toolRevisionId ${toolRevisionId}`,
      `validation ${capabilityBundle?.validationEvidence?.status || "unknown"}`,
      ...advisoryChecks.map((check) => `advisory ${check}`),
    ],
  };
}

function recommendationConfidence(matchedFields: string[], advisoryFields: string[]): number {
  return Math.min(1, 0.45 + matchedFields.length * 0.15 + advisoryFields.length * 0.07);
}

function capabilityNodeText(node: CapabilityGraphSemanticNode): string {
  return [node.profileId, node.packId, node.operation, node.workflowStage, node.toolRevisionId].join(" ").toLowerCase();
}

function recommendationName(item: WorkflowToolRecommendationItem): string {
  return item.candidate.profileId || item.candidate.candidateId || "";
}
