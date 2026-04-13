"use client";

import type { WorkflowArtifact, WorkflowEdgeView, WorkflowRun, WorkflowSpecView } from "./detection_workspace_types";

export type WorkflowDagNodeState = "draft" | "compiled" | "running" | "completed" | "failed";

export type WorkflowDagNodeModel = {
  node_id: string;
  label: string;
  tool_id: string;
  depth: number;
  order: number;
  x: number;
  y: number;
  width: number;
  height: number;
  state: WorkflowDagNodeState;
  selected: boolean;
  upstream: string[];
  downstream: string[];
  matched_artifacts: WorkflowArtifact[];
};

export type WorkflowDagEdgeModel = WorkflowEdgeView & {
  source_x: number;
  source_y: number;
  target_x: number;
  target_y: number;
  selected: boolean;
};

export type WorkflowDagModel = {
  nodes: WorkflowDagNodeModel[];
  edges: WorkflowDagEdgeModel[];
  roots: string[];
  leaves: string[];
  width: number;
  height: number;
};

const NODE_WIDTH = 240;
const NODE_HEIGHT = 112;
const NODE_GAP_X = 88;
const NODE_GAP_Y = 28;
const CANVAS_PADDING = 40;

function safeText(value: unknown, fallback = "") {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return fallback;
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function inferRunState(selectedRun: WorkflowRun | null): WorkflowDagNodeState {
  const state = selectedRun?.status?.toLowerCase() || "";
  if (["running", "queued", "pending", "draft"].includes(state)) {
    return "running";
  }
  if (["completed", "complete", "succeeded", "success"].includes(state)) {
    return "completed";
  }
  if (["failed", "error", "cancelled", "canceled"].includes(state)) {
    return "failed";
  }
  return selectedRun ? "compiled" : "draft";
}

function collectNodeDepths(workflow: WorkflowSpecView) {
  const nodeIds = workflow.nodes.map((node) => node.node_id);
  const adjacency = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  for (const nodeId of nodeIds) {
    adjacency.set(nodeId, []);
    incoming.set(nodeId, []);
  }
  for (const edge of workflow.edges) {
    if (!adjacency.has(edge.source_node_id) || !incoming.has(edge.target_node_id)) {
      continue;
    }
    adjacency.get(edge.source_node_id)?.push(edge.target_node_id);
    incoming.get(edge.target_node_id)?.push(edge.source_node_id);
  }

  const memo = new Map<string, number>();
  const visiting = new Set<string>();
  const computeDepth = (nodeId: string): number => {
    if (memo.has(nodeId)) {
      return memo.get(nodeId) as number;
    }
    if (visiting.has(nodeId)) {
      return 0;
    }
    visiting.add(nodeId);
    const parents = incoming.get(nodeId) || [];
    const depth = parents.length === 0 ? 0 : Math.max(...parents.map((parentId) => computeDepth(parentId) + 1));
    visiting.delete(nodeId);
    memo.set(nodeId, depth);
    return depth;
  };

  const depths = new Map<string, number>();
  for (const nodeId of nodeIds) {
    depths.set(nodeId, computeDepth(nodeId));
  }

  return { adjacency, incoming, depths };
}

function matchArtifactsForNode(node: WorkflowSpecView["nodes"][number], artifacts: WorkflowArtifact[]) {
  const tokens = [node.node_id, node.tool_id, node.label].map((item) => slugify(item));
  return artifacts.filter((artifact) => {
    const haystack = slugify([artifact.name, artifact.remote_path, artifact.local_path].filter(Boolean).join(" "));
    return tokens.some((token) => token.length > 0 && haystack.includes(token));
  });
}

export function buildWorkflowDagModel(
  workflow: WorkflowSpecView,
  selectedRun: WorkflowRun | null,
  artifacts: WorkflowArtifact[],
  selectedNodeId?: string | null
): WorkflowDagModel {
  const { adjacency, incoming, depths } = collectNodeDepths(workflow);
  const nodeOrder = new Map(workflow.nodes.map((node, index) => [node.node_id, index]));
  const selectedState = inferRunState(selectedRun);
  const roots = workflow.nodes.filter((node) => (incoming.get(node.node_id) || []).length === 0).map((node) => node.node_id);
  const leaves = workflow.nodes.filter((node) => (adjacency.get(node.node_id) || []).length === 0).map((node) => node.node_id);

  const byDepth = new Map<number, WorkflowSpecView["nodes"]>();
  for (const node of workflow.nodes) {
    const depth = depths.get(node.node_id) || 0;
    const bucket = byDepth.get(depth) || [];
    bucket.push(node);
    byDepth.set(depth, bucket);
  }

  const layoutNodes: WorkflowDagNodeModel[] = [];
  const depthValues = Array.from(byDepth.keys()).sort((left, right) => left - right);
  for (const depth of depthValues) {
    const bucket = [...(byDepth.get(depth) || [])].sort((left, right) => {
      const leftOrder = nodeOrder.get(left.node_id) ?? 0;
      const rightOrder = nodeOrder.get(right.node_id) ?? 0;
      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }
      return left.node_id.localeCompare(right.node_id);
    });
    bucket.forEach((node, index) => {
      const matchedArtifacts = matchArtifactsForNode(node, artifacts);
      layoutNodes.push({
        node_id: node.node_id,
        label: safeText(node.label, node.node_id) || node.node_id,
        tool_id: safeText(node.tool_id, "tool") || "tool",
        depth,
        order: index,
        x: CANVAS_PADDING + depth * (NODE_WIDTH + NODE_GAP_X),
        y: CANVAS_PADDING + index * (NODE_HEIGHT + NODE_GAP_Y),
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        state: selectedState,
        selected: node.node_id === selectedNodeId,
        upstream: (incoming.get(node.node_id) || []).slice(),
        downstream: (adjacency.get(node.node_id) || []).slice(),
        matched_artifacts: matchedArtifacts,
      });
    });
  }

  const nodeLookup = new Map(layoutNodes.map((node) => [node.node_id, node]));
  const layoutEdges: WorkflowDagEdgeModel[] = workflow.edges
    .filter((edge) => nodeLookup.has(edge.source_node_id) && nodeLookup.has(edge.target_node_id))
    .map((edge) => {
      const source = nodeLookup.get(edge.source_node_id) as WorkflowDagNodeModel;
      const target = nodeLookup.get(edge.target_node_id) as WorkflowDagNodeModel;
      const source_x = source.x + source.width;
      const source_y = source.y + source.height / 2;
      const target_x = target.x;
      const target_y = target.y + target.height / 2;
      return {
        ...edge,
        source_x,
        source_y,
        target_x,
        target_y,
        selected: selectedNodeId ? edge.source_node_id === selectedNodeId || edge.target_node_id === selectedNodeId : false,
      };
    });

  const maxNodeX = layoutNodes.reduce((max, node) => Math.max(max, node.x + node.width), 0);
  const maxNodeY = layoutNodes.reduce((max, node) => Math.max(max, node.y + node.height), 0);

  return {
    nodes: layoutNodes,
    edges: layoutEdges,
    roots,
    leaves,
    width: Math.max(0, maxNodeX + CANVAS_PADDING),
    height: Math.max(0, maxNodeY + CANVAS_PADDING),
  };
}
