"use client";

import { useMemo } from "react";

import type { AddedTool } from "./tools-page-model";
import { RuleGraphNodeCard } from "./generated-workflow-graph-node-card";
import { readRuleInputs, readRuleOutputs, type GeneratedWorkflowValidationIssue } from "./generated-workflow-model";
import type { GeneratedWorkflowBuilderController } from "./use-generated-workflow-builder";

type GraphNode = GeneratedWorkflowBuilderController["graphDraft"]["nodes"][number];
type GraphEdge = GeneratedWorkflowBuilderController["graphDraft"]["edges"][number];

export function GeneratedWorkflowGraphCanvas({
  edges,
  nodes,
  onSelectNode,
  selectedNodeId,
  tools,
  validationIssues,
}: {
  edges: GraphEdge[];
  nodes: GraphNode[];
  onSelectNode: (nodeId: string) => void;
  selectedNodeId: string;
  tools: AddedTool[];
  validationIssues: GeneratedWorkflowValidationIssue[];
}) {
  const toolById = useMemo(() => new Map(tools.map((tool) => [tool.id, tool])), [tools]);
  if (nodes.length === 0) {
    return <div className="rounded-md bg-white px-3 py-2 text-xs text-slate-500">还没有规则节点。</div>;
  }
  return (
    <div className="relative min-h-[190px] overflow-hidden rounded-md">
      <WorkflowGraphEdgeLayer edges={edges} nodes={nodes} toolById={toolById} />
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
              validationIssues={validationIssues.filter((issue) => issue.stepId === node.id)}
            />
          );
        })}
      </div>
    </div>
  );
}

function WorkflowGraphEdgeLayer({
  edges,
  nodes,
  toolById,
}: {
  edges: GraphEdge[];
  nodes: GraphNode[];
  toolById: Map<string, AddedTool>;
}) {
  const positions = nodePositions(nodes);
  const visibleEdges = edges
    .map((edge) => {
      const fromNode = nodes.find((node) => node.id === edge.from.nodeId);
      const toNode = nodes.find((node) => node.id === edge.to.nodeId);
      const fromPosition = positions.get(edge.from.nodeId);
      const toPosition = positions.get(edge.to.nodeId);
      if (!fromNode || !toNode || !fromPosition || !toPosition) return null;
      return {
        edge,
        from: portAnchorForEdge({ edge, node: fromNode, position: fromPosition, tool: toolById.get(fromNode.toolId), direction: "output" }),
        to: portAnchorForEdge({ edge, node: toNode, position: toPosition, tool: toolById.get(toNode.toolId), direction: "input" }),
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

type GraphNodePosition = {
  centerY: number;
  inputX: number;
  outputX: number;
};

function nodePositions(nodes: GraphNode[]) {
  const columns = nodes.length <= 1 ? 1 : 2;
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  return new Map(
    nodes.map((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const centerX = columns === 1 ? 500 : column === 0 ? 245 : 755;
      return [
        node.id,
        {
          centerY: ((row + 0.5) / rows) * 1000,
          inputX: Math.max(40, centerX - 210),
          outputX: Math.min(960, centerX + 210),
        },
      ];
    })
  );
}

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
  position: GraphNodePosition;
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
