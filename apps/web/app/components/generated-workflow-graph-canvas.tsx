"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type IsValidConnection,
  type Node,
  type NodeChange,
  type NodeProps,
  type OnConnect,
  type OnConnectEnd,
  type OnEdgesChange,
  type OnNodesChange,
  type ReactFlowInstance,
} from "@xyflow/react";

import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import { layoutGeneratedWorkflowGraph } from "./generated-workflow-graph-layout";
import {
  evaluateGeneratedWorkflowPortConnection,
  type GeneratedWorkflowPortConnectionDecision,
} from "./generated-workflow-port-connection";
import {
  workflowToolRevisionEntries,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowInputBinding,
  type GeneratedWorkflowValidationIssue,
} from "./generated-workflow-model";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

type GraphNode = GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
type GraphEdge = GeneratedWorkflowBuilderController["graphDraft"]["edges"][number];
type StepBinding = Extract<GeneratedWorkflowInputBinding, { fromStep: string; output: string }>;

type RuleFlowNodeData = Record<string, unknown> & {
  dimmed: boolean;
  edges: GraphEdge[];
  graphNode: GraphNode;
  highlighted: boolean;
  tool: AddedTool | undefined;
  validationIssues: GeneratedWorkflowValidationIssue[];
  onSelect: (nodeId: string) => void;
};
type RuleFlowNode = Node<RuleFlowNodeData, "workflowRule">;
type RuleFlowEdge = Edge<Record<string, unknown>>;

const FLOW_NODE_WIDTH = 290;
const FLOW_NODE_COLUMN_GAP = 120;
const FLOW_NODE_ROW_GAP = 72;
const FLOW_NODE_MIN_HEIGHT = 170;
const FLOW_NODE_TYPES = { workflowRule: WorkflowRuleFlowNode };

export function GeneratedWorkflowGraphCanvas({
  edges,
  layoutRevision = 0,
  nodes,
  onBindInput,
  onSelectNode,
  searchQuery = "",
  selectedNodeId,
  tools,
  validationIssues,
}: {
  edges: GraphEdge[];
  layoutRevision?: number;
  nodes: GraphNode[];
  onBindInput: (stepId: string, inputName: string, binding: GeneratedWorkflowInputBinding) => void;
  onSelectNode: (nodeId: string) => void;
  searchQuery?: string;
  selectedNodeId: string;
  tools: AddedTool[];
  validationIssues: GeneratedWorkflowValidationIssue[];
}) {
  const graphDraft = useMemo<GeneratedWorkflowGraphDraft>(() => ({ edges, nodes, outputs: [] }), [edges, nodes]);
  const toolByRevisionId = useMemo(() => new Map(workflowToolRevisionEntries(tools)), [tools]);
  const layout = useMemo(() => layoutGeneratedWorkflowGraph({ edges, nodes }), [edges, nodes]);
  const matchedNodeIds = useMemo(
    () => matchedGraphNodeIds({ nodes, query: searchQuery, toolByRevisionId }),
    [nodes, searchQuery, toolByRevisionId]
  );
  const hasSearch = searchQuery.trim().length > 0;
  const [connectionNotice, setConnectionNotice] = useState("");
  const lastInvalidConnectionRef = useRef("");
  const flowInstanceRef = useRef<ReactFlowInstance<RuleFlowNode, RuleFlowEdge> | null>(null);
  const flowNodeDrafts = useMemo(
    () =>
      buildFlowNodes({
        edges,
        hasSearch,
        layout,
        matchedNodeIds,
        nodes,
        onSelectNode,
        selectedNodeId,
        toolByRevisionId,
        validationIssues,
      }),
    [edges, hasSearch, layout, matchedNodeIds, nodes, onSelectNode, selectedNodeId, toolByRevisionId, validationIssues]
  );
  const [flowNodes, setFlowNodes] = useState<RuleFlowNode[]>(flowNodeDrafts);
  const layoutRevisionRef = useRef(layoutRevision);

  useEffect(() => {
    setFlowNodes((current) => {
      const preservePositions = layoutRevisionRef.current === layoutRevision;
      layoutRevisionRef.current = layoutRevision;
      return mergeFlowNodes({ next: flowNodeDrafts, preservePositions, previous: current });
    });
  }, [flowNodeDrafts, layoutRevision]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      flowInstanceRef.current?.fitView({ padding: 0.18 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [layoutRevision, nodes.length]);

  const evaluateConnection = useCallback(
    (connection: Connection | RuleFlowEdge): GeneratedWorkflowPortConnectionDecision => {
      const graphConnection = reactFlowConnectionToGraphConnection(connection);
      if (!graphConnection) {
        return { ok: false, code: "WORKFLOW_GRAPH_CONNECTION_HANDLE_MISSING", reason: "连接缺少源端口或目标端口" };
      }
      return evaluateGeneratedWorkflowPortConnection({ connection: graphConnection, graphDraft, tools });
    },
    [graphDraft, tools]
  );
  const isValidConnection = useCallback<IsValidConnection<RuleFlowEdge>>(
    (connection) => {
      const decision = evaluateConnection(connection);
      if (!decision.ok) lastInvalidConnectionRef.current = decision.reason;
      return decision.ok;
    },
    [evaluateConnection]
  );
  const onConnect = useCallback<OnConnect>(
    (connection) => {
      const graphConnection = reactFlowConnectionToGraphConnection(connection);
      const decision = evaluateConnection(connection);
      if (!graphConnection || !decision.ok) {
        setConnectionNotice(decision.reason);
        return;
      }
      onBindInput(graphConnection.to.nodeId, graphConnection.to.port, decision.binding);
      setConnectionNotice(`已连接 ${graphConnection.from.nodeId}.${graphConnection.from.port} -> ${graphConnection.to.nodeId}.${graphConnection.to.port}`);
    },
    [evaluateConnection, onBindInput]
  );
  const onConnectEnd = useCallback<OnConnectEnd>((_event, connectionState) => {
    if (connectionState.isValid === false && lastInvalidConnectionRef.current) {
      setConnectionNotice(lastInvalidConnectionRef.current);
    }
  }, []);
  const onNodesChange = useCallback<OnNodesChange<RuleFlowNode>>((changes: NodeChange<RuleFlowNode>[]) => {
    setFlowNodes((current) => applyNodeChanges(changes, current));
  }, []);
  const onEdgesChange = useCallback<OnEdgesChange<RuleFlowEdge>>(
    (changes: EdgeChange<RuleFlowEdge>[]) => {
      for (const change of changes) {
        if (change.type !== "remove") continue;
        const edge = edges.find((item) => item.id === change.id);
        if (edge) onBindInput(edge.to.nodeId, edge.to.port, "");
      }
    },
    [edges, onBindInput]
  );
  const flowEdges = useMemo(() => buildFlowEdges(edges), [edges]);

  if (nodes.length === 0) {
    return <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">还没有规则节点。从工具库添加 RuleSpec 节点。</div>;
  }

  return (
    <div className="relative h-[430px] overflow-hidden rounded-md border border-slate-200 bg-white" data-workflow-react-flow-canvas>
      <GraphCanvasStyles />
      <ReactFlow<RuleFlowNode, RuleFlowEdge>
        className="workflow-react-flow"
        colorMode="light"
        connectionLineStyle={{ stroke: "rgb(37 99 235)", strokeWidth: 2 }}
        defaultEdgeOptions={{
          markerEnd: { type: MarkerType.ArrowClosed, color: "rgb(37 99 235)" },
          style: { stroke: "rgb(37 99 235)", strokeWidth: 2 },
          type: "smoothstep",
        }}
        deleteKeyCode={["Backspace", "Delete"]}
        edges={flowEdges}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        isValidConnection={isValidConnection}
        maxZoom={1.7}
        minZoom={0.35}
        nodeTypes={FLOW_NODE_TYPES}
        nodes={flowNodes.length > 0 ? flowNodes : flowNodeDrafts}
        nodesConnectable
        nodesDraggable
        onConnect={onConnect}
        onConnectEnd={onConnectEnd}
        onEdgesChange={onEdgesChange}
        onInit={(instance) => {
          flowInstanceRef.current = instance;
        }}
        onNodeClick={(_event, node) => onSelectNode(node.id)}
        onNodesChange={onNodesChange}
        panOnDrag
        panOnScroll
        zoomOnDoubleClick={false}
        zoomOnScroll
      >
        <Background color="#e2e8f0" gap={18} />
        <Controls showInteractive={false} />
        <MiniMap className="!bg-white/90" pannable zoomable />
      </ReactFlow>
      {connectionNotice ? (
        <div className="pointer-events-none absolute bottom-2 left-2 max-w-[70%] rounded border border-slate-200 bg-white/95 px-2 py-1 text-[11px] text-slate-600 shadow-sm">
          {connectionNotice}
        </div>
      ) : null}
    </div>
  );
}

function WorkflowRuleFlowNode({ data, selected }: NodeProps<RuleFlowNode>) {
  return (
    <div
      className={cn(
        "rounded-md transition",
        data.dimmed ? "opacity-35" : "",
        data.highlighted ? "ring-2 ring-amber-300 ring-offset-1" : ""
      )}
    >
      <RuleGraphNodeCard
        edges={data.edges}
        node={data.graphNode}
        onSelect={() => data.onSelect(data.graphNode.id)}
        selected={selected}
        tool={data.tool}
        validationIssues={data.validationIssues}
      />
    </div>
  );
}

function buildFlowNodes({
  edges,
  hasSearch,
  layout,
  matchedNodeIds,
  nodes,
  onSelectNode,
  selectedNodeId,
  toolByRevisionId,
  validationIssues,
}: {
  edges: GraphEdge[];
  hasSearch: boolean;
  layout: ReturnType<typeof layoutGeneratedWorkflowGraph>;
  matchedNodeIds: Set<string>;
  nodes: GraphNode[];
  onSelectNode: (nodeId: string) => void;
  selectedNodeId: string;
  toolByRevisionId: Map<string, AddedTool>;
  validationIssues: GeneratedWorkflowValidationIssue[];
}): RuleFlowNode[] {
  const layoutByNodeId = new Map(layout.items.map((item, index) => [item.node.id, { index, item }]));
  return nodes.map((node, index) => {
    const item = layoutByNodeId.get(node.id);
    const nodeIssues = validationIssues.filter((issue) => issue.stepId === node.id);
    const highlighted = matchedNodeIds.has(node.id);
    return {
      id: node.id,
      data: {
        dimmed: hasSearch && !highlighted && nodeIssues.length === 0,
        edges,
        graphNode: node,
        highlighted,
        onSelect: onSelectNode,
        tool: toolByRevisionId.get(node.toolRevisionId),
        validationIssues: nodeIssues,
      },
      position: flowPositionForLayout(item?.item, item?.index ?? index),
      selected: selectedNodeId === node.id,
      style: { width: FLOW_NODE_WIDTH },
      type: "workflowRule",
    };
  });
}

function buildFlowEdges(edges: GraphEdge[]): RuleFlowEdge[] {
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

function flowPositionForLayout(
  item: ReturnType<typeof layoutGeneratedWorkflowGraph>["items"][number] | undefined,
  index: number
) {
  if (!item) {
    return { x: 0, y: index * (FLOW_NODE_MIN_HEIGHT + FLOW_NODE_ROW_GAP) };
  }
  return {
    x: item.column * (FLOW_NODE_WIDTH + FLOW_NODE_COLUMN_GAP),
    y: item.row * (FLOW_NODE_MIN_HEIGHT + FLOW_NODE_ROW_GAP) + item.layer * 18,
  };
}

function mergeFlowNodes({
  next,
  preservePositions,
  previous,
}: {
  next: RuleFlowNode[];
  preservePositions: boolean;
  previous: RuleFlowNode[];
}) {
  const previousPositions = new Map(previous.map((node) => [node.id, node.position]));
  return next.map((node) => {
    const position = preservePositions ? previousPositions.get(node.id) : undefined;
    return position ? { ...node, position } : node;
  });
}

function reactFlowConnectionToGraphConnection(connection: Connection | RuleFlowEdge) {
  if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) return null;
  return {
    from: { nodeId: connection.source, port: connection.sourceHandle },
    to: { nodeId: connection.target, port: connection.targetHandle },
  };
}

function matchedGraphNodeIds({
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

function GraphCanvasStyles() {
  return (
    <style>{`
.workflow-react-flow .react-flow__node-workflowRule {
  border-radius: 0.375rem;
}

.workflow-react-flow .react-flow__handle {
  pointer-events: all;
}

.workflow-react-flow .react-flow__minimap {
  border: 1px solid rgb(226 232 240);
  border-radius: 0.375rem;
}
`}</style>
  );
}
