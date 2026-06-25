"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Plus } from "lucide-react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  applyNodeChanges,
  type Connection,
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

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import type { RulePortConverterInsertionRequest } from "./generated-workflow-converter-recommendation";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import { readWorkflowToolDrop } from "./generated-workflow-graph-drag-drop";
import { layoutGeneratedWorkflowGraph } from "./generated-workflow-graph-layout";
import {
  buildFlowEdges,
  matchedGraphNodeIds,
  reactFlowConnectionToGraphConnection,
  type WorkflowRuleFlowEdge,
} from "./generated-workflow-react-flow-adapter";
import { converterSuggestionsForConnection, type OutputConverterSuggestion } from "./generated-workflow-port-advice";
import {
  evaluateGeneratedWorkflowPortConnection,
  type GeneratedWorkflowPortConnectionDecision,
} from "./generated-workflow-port-connection";
import {
  graphNodePosition,
  graphNodeSubflowId,
  graphNodeSubflowLabel,
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
  activeSearchResult: boolean;
  dimmed: boolean;
  edges: GraphEdge[];
  graphNode: GraphNode;
  highlighted: boolean;
  tool: AddedTool | undefined;
  validationIssues: GeneratedWorkflowValidationIssue[];
  onSelect: (nodeId: string) => void;
};
type RuleFlowNode = Node<RuleFlowNodeData, "workflowRule">;
type RuleFlowSubflowGroupData = Record<string, unknown> & {
  label: string;
  nodeCount: number;
};
type RuleFlowSubflowGroupNode = Node<RuleFlowSubflowGroupData, "subflowGroup">;
type RuleFlowAnyNode = RuleFlowNode | RuleFlowSubflowGroupNode;
type RuleFlowEdge = WorkflowRuleFlowEdge;
type ConnectionNotice = {
  message: string;
  request?: RulePortConverterInsertionRequest;
  suggestion?: OutputConverterSuggestion;
};

const FLOW_NODE_WIDTH = 290;
const FLOW_NODE_COLUMN_GAP = 120;
const FLOW_NODE_ROW_GAP = 72;
const FLOW_NODE_MIN_HEIGHT = 170;
const SUBFLOW_GROUP_PADDING_X = 30;
const SUBFLOW_GROUP_PADDING_Y = 34;
const SUBFLOW_GROUP_NODE_PREFIX = "subflow:";
const FLOW_NODE_TYPES = { workflowRule: WorkflowRuleFlowNode, subflowGroup: WorkflowSubflowGroupNode };

export function GeneratedWorkflowGraphCanvas({
  activeSearchNodeId = "",
  edges,
  layoutRevision = 0,
  nodes,
  onBindInput,
  onDropTool,
  onInsertConverter,
  onNodePositionChange,
  onNodePositionsChange,
  onSelectNode,
  searchQuery = "",
  selectedNodeId,
  tools,
  validationIssues,
}: {
  activeSearchNodeId?: string;
  edges: GraphEdge[];
  layoutRevision?: number;
  nodes: GraphNode[];
  onBindInput: (stepId: string, inputName: string, binding: GeneratedWorkflowInputBinding) => void;
  onDropTool: (toolRevisionId: string, position: { x: number; y: number }) => void;
  onInsertConverter: (request: RulePortConverterInsertionRequest) => void;
  onNodePositionChange: (nodeId: string, position: { x: number; y: number }) => void;
  onNodePositionsChange: (positions: Record<string, { x: number; y: number }>) => void;
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
  const [connectionNotice, setConnectionNotice] = useState<ConnectionNotice | null>(null);
  const lastInvalidConnectionRef = useRef<ConnectionNotice | null>(null);
  const flowInstanceRef = useRef<ReactFlowInstance<RuleFlowAnyNode, RuleFlowEdge> | null>(null);
  const layoutRevisionRef = useRef(layoutRevision);
  const layoutRequested = layoutRevisionRef.current !== layoutRevision;
  const flowNodeDrafts = useMemo(
    () =>
      buildFlowNodes({
        activeSearchNodeId,
        edges,
        forceLayout: layoutRequested,
        hasSearch,
        layout,
        matchedNodeIds,
        nodes,
        onSelectNode,
        selectedNodeId,
        toolByRevisionId,
        validationIssues,
      }),
    [activeSearchNodeId, edges, hasSearch, layout, layoutRequested, matchedNodeIds, nodes, onSelectNode, selectedNodeId, toolByRevisionId, validationIssues]
  );
  const [flowNodes, setFlowNodes] = useState<RuleFlowNode[]>(flowNodeDrafts);
  const visibleFlowNodes = flowNodes.length > 0 ? flowNodes : flowNodeDrafts;
  const subflowGroupNodes = useMemo(() => buildSubflowGroupNodes(visibleFlowNodes), [visibleFlowNodes]);

  useEffect(() => {
    const preservePositions = layoutRevisionRef.current === layoutRevision;
    if (!preservePositions && flowNodeDrafts.length > 0) {
      onNodePositionsChange(flowNodePositions(flowNodeDrafts));
    }
    layoutRevisionRef.current = layoutRevision;
    setFlowNodes((current) => {
      return mergeFlowNodes({ next: flowNodeDrafts, preservePositions, previous: current });
    });
  }, [flowNodeDrafts, layoutRevision, onNodePositionsChange]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      flowInstanceRef.current?.fitView({ padding: 0.18 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [layoutRevision, nodes.length]);

  useEffect(() => {
    if (!activeSearchNodeId) return;
    const frame = window.requestAnimationFrame(() => {
      flowInstanceRef.current?.fitView({
        duration: 180,
        maxZoom: 1.15,
        nodes: [{ id: activeSearchNodeId }],
        padding: 0.38,
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeSearchNodeId, visibleFlowNodes.length]);

  useEffect(() => {
    lastInvalidConnectionRef.current = null;
    setConnectionNotice((current) => (current?.request ? null : current));
  }, [graphDraft, tools]);

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
      const graphConnection = reactFlowConnectionToGraphConnection(connection);
      const decision = evaluateConnection(connection);
      if (!decision.ok) {
        lastInvalidConnectionRef.current = connectionNoticeForDecision({ decision, graphConnection, graphDraft, tools });
      }
      return decision.ok;
    },
    [evaluateConnection, graphDraft, tools]
  );
  const onConnect = useCallback<OnConnect>(
    (connection) => {
      const graphConnection = reactFlowConnectionToGraphConnection(connection);
      const decision = evaluateConnection(connection);
      if (!graphConnection || !decision.ok) {
        setConnectionNotice(connectionNoticeForDecision({ decision, graphConnection, graphDraft, tools }));
        return;
      }
      onBindInput(graphConnection.to.nodeId, graphConnection.to.port, decision.binding);
      setConnectionNotice({
        message: `已连接 ${graphConnection.from.nodeId}.${graphConnection.from.port} -> ${graphConnection.to.nodeId}.${graphConnection.to.port}`,
      });
    },
    [evaluateConnection, graphDraft, onBindInput, tools]
  );
  const onConnectEnd = useCallback<OnConnectEnd>(
    (_event, connectionState) => {
      if (connectionState.isValid === false && lastInvalidConnectionRef.current) {
        const notice = lastInvalidConnectionRef.current;
        lastInvalidConnectionRef.current = null;
        setConnectionNotice(notice);
      }
    },
    []
  );
  const onNodesChange = useCallback<OnNodesChange<RuleFlowAnyNode>>((changes: NodeChange<RuleFlowAnyNode>[]) => {
    const workflowNodeChanges = changes.filter((change) => {
      const nodeId = change.type === "add" ? change.item.id : change.id;
      return !isSubflowGroupNodeId(nodeId);
    }) as NodeChange<RuleFlowNode>[];
    setFlowNodes((current) => applyNodeChanges(workflowNodeChanges, current));
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
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);
  const onDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const toolRevisionId = readWorkflowToolDrop(event.dataTransfer);
    const flow = flowInstanceRef.current;
    if (!toolRevisionId) {
      setConnectionNotice({ message: "无法添加工具：拖拽数据缺少工具修订 ID。" });
      return;
    }
    if (!flow) {
      setConnectionNotice({ message: "无法添加工具：画布尚未初始化。" });
      return;
    }
    onDropTool(
      toolRevisionId,
      flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })
    );
  }, [onDropTool]);
  const flowEdges = useMemo(() => buildFlowEdges(edges), [edges]);

  return (
    <div
      className="relative h-[430px] overflow-hidden rounded-md border border-slate-200 bg-white"
      data-workflow-react-flow-canvas
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <GraphCanvasStyles />
      <ReactFlow<RuleFlowAnyNode, RuleFlowEdge>
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
        nodes={[...subflowGroupNodes, ...visibleFlowNodes]}
        nodesConnectable
        nodesDraggable
        onConnect={onConnect}
        onConnectEnd={onConnectEnd}
        onEdgesChange={onEdgesChange}
        onInit={(instance) => {
          flowInstanceRef.current = instance;
        }}
        onNodeClick={(_event, node) => {
          if (!isSubflowGroupNodeId(node.id)) onSelectNode(node.id);
        }}
        onNodeDragStop={(_event, node) => {
          if (!isSubflowGroupNodeId(node.id)) onNodePositionChange(node.id, node.position);
        }}
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
      {nodes.length === 0 ? (
        <div className="pointer-events-none absolute inset-x-3 top-3 rounded-md border border-dashed border-slate-200 bg-white/90 px-3 py-2 text-xs text-slate-500">
          还没有规则节点。从工具库添加 RuleSpec 节点。
        </div>
      ) : null}
      {connectionNotice ? (
        <div className="absolute bottom-2 left-2 grid max-w-[76%] gap-1 rounded border border-slate-200 bg-white/95 px-2 py-1.5 text-[11px] text-slate-600 shadow-sm">
          <div className="min-w-0 break-words">{connectionNotice.message}</div>
          {connectionNotice.suggestion ? (
            <Button
              type="button"
              variant="outline"
              className="h-7 justify-self-start bg-white px-2 text-[11px]"
              onClick={() => {
                if (!connectionNotice.request) return;
                onInsertConverter(connectionNotice.request);
                setConnectionNotice({
                  message: `已插入转换节点 ${connectionNotice.suggestion?.converterToolName || "converter"}，请复核新增连线。`,
                });
              }}
            >
              <Plus strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
              确认插入转换
            </Button>
          ) : null}
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
        data.activeSearchResult ? "ring-2 ring-blue-400 ring-offset-1" : "",
        data.highlighted && !data.activeSearchResult ? "ring-2 ring-amber-300 ring-offset-1" : ""
      )}
      data-search-state={data.activeSearchResult ? "active" : data.highlighted ? "matched" : data.dimmed ? "dimmed" : "idle"}
      data-testid={`rule-flow-node-${data.graphNode.id}`}
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

function WorkflowSubflowGroupNode({ data }: NodeProps<RuleFlowSubflowGroupNode>) {
  return (
    <div className="h-full w-full rounded-md border border-dashed border-sky-300 bg-sky-50/45">
      <div className="inline-flex max-w-full items-center gap-2 rounded-br-md bg-white/90 px-2 py-1 text-[11px] font-medium text-sky-800 shadow-sm">
        <span className="truncate">{data.label}</span>
        <span className="shrink-0 text-sky-500">{data.nodeCount} nodes</span>
      </div>
    </div>
  );
}

function buildFlowNodes({
  activeSearchNodeId,
  edges,
  forceLayout = false,
  hasSearch,
  layout,
  matchedNodeIds,
  nodes,
  onSelectNode,
  selectedNodeId,
  toolByRevisionId,
  validationIssues,
}: {
  activeSearchNodeId: string;
  edges: GraphEdge[];
  forceLayout?: boolean;
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
    const activeSearchResult = Boolean(activeSearchNodeId && activeSearchNodeId === node.id);
    return {
      id: node.id,
      data: {
        activeSearchResult,
        dimmed: hasSearch && !highlighted && nodeIssues.length === 0,
        edges,
        graphNode: node,
        highlighted,
        onSelect: onSelectNode,
        tool: toolByRevisionId.get(node.toolRevisionId),
        validationIssues: nodeIssues,
      },
      position: flowPositionForNode(node, item?.item, item?.index ?? index, forceLayout),
      selected: selectedNodeId === node.id,
      style: { width: FLOW_NODE_WIDTH },
      type: "workflowRule",
      zIndex: 10,
    };
  });
}

function buildSubflowGroupNodes(nodes: RuleFlowNode[]): RuleFlowSubflowGroupNode[] {
  const groups = new Map<string, { label: string; nodes: RuleFlowNode[] }>();
  for (const node of nodes) {
    const subflowId = graphNodeSubflowId(node.data.graphNode);
    if (!subflowId) continue;
    const existingGroup = groups.get(subflowId);
    const group = existingGroup || { label: graphNodeSubflowLabel(node.data.graphNode), nodes: [] };
    group.nodes.push(node);
    groups.set(subflowId, group);
  }
  return [...groups.entries()].map(([subflowId, group]) => subflowGroupNode(subflowId, group));
}

function subflowGroupNode(
  subflowId: string,
  group: {
    label: string;
    nodes: RuleFlowNode[];
  }
): RuleFlowSubflowGroupNode {
  const minX = Math.min(...group.nodes.map((node) => node.position.x));
  const minY = Math.min(...group.nodes.map((node) => node.position.y));
  const maxX = Math.max(...group.nodes.map((node) => node.position.x + FLOW_NODE_WIDTH));
  const maxY = Math.max(...group.nodes.map((node) => node.position.y + FLOW_NODE_MIN_HEIGHT));
  return {
    id: `${SUBFLOW_GROUP_NODE_PREFIX}${subflowId}`,
    connectable: false,
    data: { label: group.label || subflowId, nodeCount: group.nodes.length },
    deletable: false,
    draggable: false,
    focusable: false,
    position: { x: minX - SUBFLOW_GROUP_PADDING_X, y: minY - SUBFLOW_GROUP_PADDING_Y },
    selectable: false,
    style: {
      height: maxY - minY + SUBFLOW_GROUP_PADDING_Y * 2,
      width: maxX - minX + SUBFLOW_GROUP_PADDING_X * 2,
    },
    type: "subflowGroup",
    zIndex: 0,
  };
}

function flowPositionForNode(
  node: GraphNode,
  item: ReturnType<typeof layoutGeneratedWorkflowGraph>["items"][number] | undefined,
  index: number,
  forceLayout = false
) {
  const position = forceLayout ? null : graphNodePosition(node);
  if (position) return position;
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
    if (graphNodePosition(node.data.graphNode)) return node;
    const position = preservePositions ? previousPositions.get(node.id) : undefined;
    return position ? { ...node, position } : node;
  });
}

function flowNodePositions(nodes: RuleFlowNode[]) {
  return Object.fromEntries(nodes.map((node) => [node.id, node.position]));
}

function isSubflowGroupNodeId(nodeId: string) {
  return nodeId.startsWith(SUBFLOW_GROUP_NODE_PREFIX);
}

function connectionNoticeForDecision({
  decision,
  graphConnection,
  graphDraft,
  tools,
}: {
  decision: GeneratedWorkflowPortConnectionDecision;
  graphConnection: ReturnType<typeof reactFlowConnectionToGraphConnection>;
  graphDraft: GeneratedWorkflowGraphDraft;
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
      return {
        message: `${decision.reason}。可插入转换 ${suggestion.converterToolName} · 需确认，不会自动插入。${replacementNote}`,
        request: {
          sourceStepId: suggestion.sourceStepId,
          sourceOutput: suggestion.sourceOutput,
          targetStepId: graphConnection.to.nodeId,
          targetInput: graphConnection.to.port,
          converter: suggestion,
        },
        suggestion,
      };
    }
  }
  return { message: decision.reason };
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
