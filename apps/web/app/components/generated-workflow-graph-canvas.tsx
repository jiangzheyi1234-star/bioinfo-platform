"use client";

import { useMemo } from "react";

import type { AddedTool } from "./tools-page-model";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

type GraphNode = GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
type GraphEdge = GeneratedWorkflowBuilderController["graphDraft"]["edges"][number];

export function GeneratedWorkflowGraphCanvas({
  edges,
  nodes,
  onSelectNode,
  selectedNodeId,
  tools,
}: {
  edges: GraphEdge[];
  nodes: GraphNode[];
  onSelectNode: (nodeId: string) => void;
  selectedNodeId: string;
  tools: AddedTool[];
}) {
  const toolById = useMemo(() => new Map(tools.map((tool) => [tool.id, tool])), [tools]);
  if (nodes.length === 0) {
    return <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">还没有规则节点。</div>;
  }
  return (
    <div className="relative min-h-[190px] overflow-hidden rounded-md">
      <WorkflowGraphEdgeLayer edges={edges} nodes={nodes} />
      <div className="relative z-10 grid gap-2 md:grid-cols-2">
        {nodes.map((node) => {
          const selected = selectedNodeId === node.id;
          return (
            <RuleGraphNodeCard
              edges={edges}
              key={node.id}
              node={node}
              onSelect={() => onSelectNode(node.id)}
              selected={selected}
              tool={toolById.get(node.toolId)}
            />
          );
        })}
      </div>
    </div>
  );
}

function WorkflowGraphEdgeLayer({ edges, nodes }: { edges: GraphEdge[]; nodes: GraphNode[] }) {
  const positions = nodePositions(nodes);
  const visibleEdges = edges
    .map((edge) => ({ edge, from: positions.get(edge.from.nodeId), to: positions.get(edge.to.nodeId) }))
    .filter((item): item is { edge: GraphEdge; from: GraphPoint; to: GraphPoint } => Boolean(item.from && item.to));
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

function nodePositions(nodes: GraphNode[]) {
  const columns = nodes.length <= 1 ? 1 : 2;
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  return new Map(
    nodes.map((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const x = columns === 1 ? 500 : column === 0 ? 245 : 755;
      const y = ((row + 0.5) / rows) * 1000;
      return [node.id, { x, y }];
    })
  );
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
