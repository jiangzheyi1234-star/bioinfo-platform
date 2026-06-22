"use client";

import { type CSSProperties, useMemo } from "react";

import { cn } from "@/lib/utils";

import type { AddedTool } from "./tools-page-model";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import {
  layoutGeneratedWorkflowGraph,
  type GeneratedWorkflowGraphLayout,
  type GeneratedWorkflowGraphNodePosition,
} from "./generated-workflow-graph-layout";
import { readRuleInputs, readRuleOutputs, workflowToolRevisionEntries, type GeneratedWorkflowValidationIssue } from "./generated-workflow-model";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

type GraphNode = GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
type GraphEdge = GeneratedWorkflowBuilderController["graphDraft"]["edges"][number];

export function GeneratedWorkflowGraphCanvas({
  edges,
  nodes,
  onSelectNode,
  searchQuery = "",
  selectedNodeId,
  tools,
  validationIssues,
  zoom = 1,
}: {
  edges: GraphEdge[];
  nodes: GraphNode[];
  onSelectNode: (nodeId: string) => void;
  searchQuery?: string;
  selectedNodeId: string;
  tools: AddedTool[];
  validationIssues: GeneratedWorkflowValidationIssue[];
  zoom?: number;
}) {
  const toolByRevisionId = useMemo(() => new Map(workflowToolRevisionEntries(tools)), [tools]);
  const layout = useMemo(() => layoutGeneratedWorkflowGraph({ edges, nodes }), [edges, nodes]);
  const matchedNodeIds = useMemo(
    () => matchedGraphNodeIds({ nodes, query: searchQuery, toolByRevisionId }),
    [nodes, searchQuery, toolByRevisionId]
  );
  const hasSearch = searchQuery.trim().length > 0;
  if (nodes.length === 0) {
    return <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">还没有规则节点。从工具库添加 RuleSpec 节点。</div>;
  }
  return (
    <div className="relative min-h-[190px] overflow-auto rounded-md">
      <div className="generated-workflow-graph-viewport relative min-h-[190px]" style={graphViewportStyle(zoom)}>
        <WorkflowGraphEdgeLayer edges={edges} layout={layout} nodes={nodes} toolByRevisionId={toolByRevisionId} />
        <GraphLayoutStyles />
        <div
          className="generated-workflow-graph-layout relative z-10 grid grid-cols-1 gap-2"
          style={graphLayoutStyle(layout.columnCount)}
        >
          {layout.items.map((item) => {
            const node = item.node;
            const selected = selectedNodeId === node.id;
            const highlighted = matchedNodeIds.has(node.id);
            const nodeIssues = validationIssues.filter((issue) => issue.stepId === node.id);
            const dimmed = hasSearch && !highlighted && nodeIssues.length === 0;
            return (
              <div
                className={cn(
                  "generated-workflow-graph-layout-item min-w-0 rounded-md transition",
                  dimmed ? "opacity-35" : "",
                  highlighted ? "ring-2 ring-amber-300 ring-offset-1" : ""
                )}
                key={node.id}
                style={graphLayoutItemStyle(item)}
              >
                <RuleGraphNodeCard
                  edges={edges}
                  node={node}
                  onSelect={() => onSelectNode(node.id)}
                  selected={selected}
                  tool={toolByRevisionId.get(node.toolRevisionId)}
                  validationIssues={nodeIssues}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function WorkflowGraphEdgeLayer({
  edges,
  layout,
  nodes,
  toolByRevisionId,
}: {
  edges: GraphEdge[];
  layout: GeneratedWorkflowGraphLayout;
  nodes: GraphNode[];
  toolByRevisionId: Map<string, AddedTool>;
}) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const visibleEdges = edges
    .map((edge) => {
      const fromNode = nodeById.get(edge.from.nodeId);
      const toNode = nodeById.get(edge.to.nodeId);
      const fromPosition = layout.positions.get(edge.from.nodeId);
      const toPosition = layout.positions.get(edge.to.nodeId);
      if (!fromNode || !toNode || !fromPosition || !toPosition) return null;
      return {
        edge,
        from: portAnchorForEdge({ edge, node: fromNode, position: fromPosition, tool: toolByRevisionId.get(fromNode.toolRevisionId), direction: "output" }),
        to: portAnchorForEdge({ edge, node: toNode, position: toPosition, tool: toolByRevisionId.get(toNode.toolRevisionId), direction: "input" }),
      };
    })
    .filter((item): item is { edge: GraphEdge; from: GraphPoint; to: GraphPoint } => Boolean(item));
  if (visibleEdges.length === 0) return null;
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-0 hidden h-full w-full md:block"
      data-workflow-graph-edge-layer
      preserveAspectRatio="none"
      viewBox="0 0 1000 1000"
    >
      <defs>
        <marker id="workflow-graph-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
          <path d="M0,0 L8,4 L0,8 Z" fill="rgb(59 130 246)" />
        </marker>
      </defs>
      {visibleEdges.map(({ edge, from, to }) => (
        <path
          key={edge.id}
          d={edgePath(from, to)}
          data-from-port={edge.from.port}
          data-to-port={edge.to.port}
          data-workflow-graph-edge
          fill="none"
          markerEnd="url(#workflow-graph-arrow)"
          stroke="rgb(59 130 246)"
          strokeOpacity="0.45"
          strokeWidth="3"
        />
      ))}
    </svg>
  );
}

type GraphPoint = {
  x: number;
  y: number;
};

function portAnchorForEdge({
  direction,
  edge,
  node,
  position,
  tool,
}: {
  direction: "input" | "output";
  edge: GraphEdge;
  node: GraphNode;
  position: GeneratedWorkflowGraphNodePosition;
  tool: AddedTool | undefined;
}) {
  const portName = direction === "output" ? edge.from.port : edge.to.port;
  const ports = direction === "output" ? readRuleOutputs(tool) : readRuleInputs(tool);
  const portIndex = Math.max(0, ports.findIndex((port) => port.name === portName));
  return {
    x: direction === "output" ? position.outputX : position.inputX,
    y: position.centerY + portOffset(portIndex, Math.max(1, ports.length || Object.keys(node.inputs).length)),
  };
}

function portOffset(index: number, count: number) {
  const visibleCount = Math.min(Math.max(count, 1), 3);
  const visibleIndex = Math.min(index, visibleCount - 1);
  return (visibleIndex - (visibleCount - 1) / 2) * 52;
}

function edgePath(from: GraphPoint, to: GraphPoint) {
  const horizontal = Math.max(120, Math.abs(to.x - from.x) * 0.45);
  const vertical = Math.max(80, Math.abs(to.y - from.y) * 0.25);
  const fromBias = to.x >= from.x ? horizontal : -horizontal;
  const toBias = to.x >= from.x ? -horizontal : horizontal;
  const fromY = from.y + (to.y > from.y ? vertical : to.y < from.y ? -vertical : 0);
  const toY = to.y + (from.y > to.y ? vertical : from.y < to.y ? -vertical : 0);
  return `M ${from.x} ${from.y} C ${from.x + fromBias} ${fromY}, ${to.x + toBias} ${toY}, ${to.x} ${to.y}`;
}

function graphLayoutStyle(columnCount: number): CSSProperties {
  return { "--workflow-graph-columns": columnCount } as CSSProperties;
}

function graphLayoutItemStyle(item: GeneratedWorkflowGraphNodePosition): CSSProperties {
  return {
    "--workflow-graph-column": item.column + 1,
    "--workflow-graph-row": item.row + 1,
  } as CSSProperties;
}

function graphViewportStyle(zoom: number): CSSProperties {
  const clampedZoom = Math.min(1.5, Math.max(0.65, zoom));
  return {
    "--workflow-graph-zoom": clampedZoom,
  } as CSSProperties;
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

function GraphLayoutStyles() {
  return (
    <style>{`
.generated-workflow-graph-viewport {
  transform: scale(var(--workflow-graph-zoom));
  transform-origin: top left;
  width: calc(100% / var(--workflow-graph-zoom));
}

@media (min-width: 768px) {
  .generated-workflow-graph-layout {
    grid-template-columns: repeat(var(--workflow-graph-columns), minmax(0, 1fr));
  }

  .generated-workflow-graph-layout-item {
    grid-column: var(--workflow-graph-column);
    grid-row: var(--workflow-graph-row);
  }
}
`}</style>
  );
}
