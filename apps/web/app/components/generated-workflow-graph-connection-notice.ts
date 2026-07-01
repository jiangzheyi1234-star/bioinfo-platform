import type { AddedTool } from "./tools-page-model";
import type { RulePortConverterInsertionRequest } from "./generated-workflow-converter-recommendation";
import {
  backendPlanConverterInsertionForSuggestion,
  converterSuggestionsForConnection,
  type OutputConverterSuggestion,
} from "./generated-workflow-port-advice";
import {
  evaluateGeneratedWorkflowPortConnection,
  type GeneratedWorkflowPortConnectionDecision,
} from "./generated-workflow-port-connection";
import {
  workflowToolRevisionEntries,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowGraphPortRef,
} from "./generated-workflow-model";
import type { WorkflowDesignDraft, WorkflowDesignSemanticPortPlan } from "./workflow-design-draft-model";

type GraphConnection = {
  from: GeneratedWorkflowGraphPortRef;
  to: GeneratedWorkflowGraphPortRef;
};

export type ConnectionNotice = {
  code?: string;
  graphSignature?: string;
  message: string;
  planning?: boolean;
  proposedEdge?: WorkflowDesignDraft["edges"][number];
  proposedKey?: string;
  request?: RulePortConverterInsertionRequest;
  suggestion?: OutputConverterSuggestion;
};

export function connectionNoticeState(notice: ConnectionNotice) {
  if (notice.planning) return "backend-plan-pending";
  if (notice.request) return "backend-plan-confirmable";
  if (notice.suggestion) return "advisory-only";
  return "message";
}

export function connectionNoticeForDecision({
  decision,
  graphSignature,
  graphConnection,
  graphDraft,
  requireProposedBackendPlan = false,
  semanticPortPlan,
  tools,
}: {
  decision: GeneratedWorkflowPortConnectionDecision;
  graphSignature?: string;
  graphConnection: GraphConnection | null;
  graphDraft: GeneratedWorkflowGraphDraft;
  requireProposedBackendPlan?: boolean;
  semanticPortPlan?: WorkflowDesignSemanticPortPlan | null;
  tools: AddedTool[];
}): ConnectionNotice {
  if (!decision.ok && decision.code === "WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE" && graphConnection) {
    const suggestion = converterSuggestionsForConnection({ connection: graphConnection, graphDraft, tools })[0];
    if (suggestion) {
      const replacementNote = graphDraft.edges.some(
        (edge) => edge.to.nodeId === graphConnection.to.nodeId && edge.to.port === graphConnection.to.port
      )
        ? " 将替换当前目标输入绑定。"
        : "";
      const backendInsertion = backendPlanConverterInsertionForSuggestion({
        plan: semanticPortPlan,
        requireProposed: requireProposedBackendPlan,
        sourceOutput: suggestion.sourceOutput,
        sourceStepId: suggestion.sourceStepId,
        suggestion,
        targetInput: graphConnection.to.port,
        targetStepId: graphConnection.to.nodeId,
      });
      const proposedEdge = proposedEdgeForGraphConnection(graphConnection);
      return {
        code: decision.code,
        graphSignature,
        message: `${decision.reason}。本地发现转换 ${suggestion.converterToolName}；后端 semanticPortPlan 背书后才可插入，且需确认，不会自动插入。${replacementNote}`,
        proposedEdge,
        proposedKey: proposedConnectionKey(proposedEdge),
        request: backendInsertion?.request,
        suggestion,
      };
    }
  }
  return { code: decision.ok ? undefined : decision.code, message: decision.reason };
}

export function proposedConnectionStaleMessage({
  graphDraft,
  graphSignature,
  notice,
  tools,
}: {
  graphDraft: GeneratedWorkflowGraphDraft;
  graphSignature: string;
  notice: ConnectionNotice;
  tools: AddedTool[];
}) {
  if (!notice.proposedEdge) return "";
  if (notice.graphSignature !== graphSignature) {
    return "连接上下文已变化，请重新拖拽端口以获取新的后端建议。";
  }
  const connection = { from: notice.proposedEdge.from, to: notice.proposedEdge.to };
  const decision = evaluateGeneratedWorkflowPortConnection({ connection, graphDraft, tools });
  if (decision.ok || decision.code !== "WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE") {
    return `连接上下文已变化：${decision.reason}`;
  }
  const suggestion = converterSuggestionsForConnection({ connection, graphDraft, tools })[0];
  if (!notice.request || !suggestion || !sameConverterSuggestion(suggestion, notice.request)) {
    return "后端转换建议已过期，请重新拖拽端口以获取新的建议。";
  }
  return "";
}

export function connectionContextSignature(graphDraft: GeneratedWorkflowGraphDraft, tools: AddedTool[]) {
  const nodes = graphDraft.nodes
    .map((node) => ({
      id: node.id,
      inputs: sortedObject(node.inputs),
      toolRevisionId: node.toolRevisionId,
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
  const edges = graphDraft.edges
    .map((edge) => ({
      from: edge.from,
      to: edge.to,
    }))
    .sort((left, right) =>
      `${left.from.nodeId}.${left.from.port}->${left.to.nodeId}.${left.to.port}`.localeCompare(
        `${right.from.nodeId}.${right.from.port}->${right.to.nodeId}.${right.to.port}`
      )
    );
  const toolRevisionIds = workflowToolRevisionEntries(tools)
    .map(([revisionId]) => revisionId)
    .sort();
  return JSON.stringify({ edges, nodes, toolRevisionIds });
}

function sameConverterSuggestion(suggestion: OutputConverterSuggestion, request: RulePortConverterInsertionRequest) {
  return (
    suggestion.converterToolRevisionId === request.converter.converterToolRevisionId
    && suggestion.inputName === request.converter.inputName
    && suggestion.outputName === request.converter.outputName
    && suggestion.sourceStepId === request.sourceStepId
    && suggestion.sourceOutput === request.sourceOutput
  );
}

function sortedObject<T>(value: Record<string, T>) {
  return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)));
}

function proposedEdgeForGraphConnection(graphConnection: GraphConnection): WorkflowDesignDraft["edges"][number] {
  return {
    from: {
      nodeId: graphConnection.from.nodeId,
      port: graphConnection.from.port,
    },
    to: {
      nodeId: graphConnection.to.nodeId,
      port: graphConnection.to.port,
    },
  };
}

function proposedConnectionKey(edge: WorkflowDesignDraft["edges"][number]) {
  return `${edge.from.nodeId}.${edge.from.port}->${edge.to.nodeId}.${edge.to.port}`;
}
