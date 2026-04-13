"use client";

import { useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import type {
  WorkflowArtifact,
  WorkflowCompilePreview,
  WorkflowEdgeView,
  WorkflowRun,
  WorkflowSpecView,
} from "./detection_workspace_types";

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

export type WorkflowDagProps = {
  workflow: WorkflowSpecView | null;
  selectedRun: WorkflowRun | null;
  compilePreview: WorkflowCompilePreview | null;
  artifacts: WorkflowArtifact[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
  className?: string;
  style?: CSSProperties;
};

const NODE_WIDTH = 240;
const NODE_HEIGHT = 112;
const NODE_GAP_X = 88;
const NODE_GAP_Y = 28;
const CANVAS_PADDING = 40;
const DETAIL_MIN_WIDTH = 320;

function joinClasses(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

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

function inferRunState(selectedRun: WorkflowRun | null): WorkflowDagNodeState {
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

function createWorkflowDagModel(
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
      const matched_artifacts = matchArtifactsForNode(node, artifacts);
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
        matched_artifacts,
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

function stateBadgeLabel(state: WorkflowDagNodeState) {
  switch (state) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "compiled":
      return "Compiled";
    default:
      return "Draft";
  }
}

function stateBadgeTone(state: WorkflowDagNodeState) {
  switch (state) {
    case "running":
      return { background: "rgba(37, 99, 235, 0.12)", color: "#1d4ed8", border: "rgba(37, 99, 235, 0.24)" };
    case "completed":
      return { background: "rgba(22, 163, 74, 0.12)", color: "#15803d", border: "rgba(22, 163, 74, 0.24)" };
    case "failed":
      return { background: "rgba(220, 38, 38, 0.12)", color: "#b91c1c", border: "rgba(220, 38, 38, 0.24)" };
    case "compiled":
      return { background: "rgba(2, 132, 199, 0.12)", color: "#0369a1", border: "rgba(2, 132, 199, 0.24)" };
    default:
      return { background: "rgba(100, 116, 139, 0.10)", color: "#475569", border: "rgba(100, 116, 139, 0.20)" };
  }
}

function edgePath(edge: WorkflowDagEdgeModel) {
  const deltaX = Math.max(72, (edge.target_x - edge.source_x) * 0.5);
  const c1x = edge.source_x + deltaX;
  const c2x = edge.target_x - deltaX;
  return `M ${edge.source_x} ${edge.source_y} C ${c1x} ${edge.source_y}, ${c2x} ${edge.target_y}, ${edge.target_x} ${edge.target_y}`;
}

function StatPill({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gap: 4,
        padding: "10px 12px",
        borderRadius: 14,
        border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
        background: "var(--workspace-surface-muted, rgba(255, 255, 255, 0.6))",
        minWidth: 0,
      }}
    >
      <span style={{ fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>{label}</span>
      <strong style={{ fontSize: 14, lineHeight: 1.2 }}>{value}</strong>
    </div>
  );
}

export function buildWorkflowDagModel(
  workflow: WorkflowSpecView,
  selectedRun: WorkflowRun | null,
  artifacts: WorkflowArtifact[],
  selectedNodeId?: string | null
) {
  return createWorkflowDagModel(workflow, selectedRun, artifacts, selectedNodeId);
}

export function WorkflowDag({
  workflow,
  selectedRun,
  compilePreview,
  artifacts,
  selectedNodeId,
  onSelectNode,
  className,
  style,
}: WorkflowDagProps) {
  const model = useMemo(() => {
    if (!workflow) {
      return null;
    }
    return createWorkflowDagModel(workflow, selectedRun, artifacts, selectedNodeId);
  }, [workflow, selectedRun, artifacts, selectedNodeId]);

  const selectedNode = model?.nodes.find((node) => node.node_id === selectedNodeId) || null;
  const activeNode = selectedNode;
  const runState = inferRunState(selectedRun);
  const compileFiles = compilePreview ? Object.keys(compilePreview.files) : [];
  const compileManifestKeys = compilePreview ? Object.keys(compilePreview.manifest || {}) : [];
  const artifactAvailableCount = artifacts.filter((item) => item.available).length;
  const artifactMissingCount = artifacts.length - artifactAvailableCount;

  if (!workflow || !model) {
    return (
      <div
        className={joinClasses("workflow-dag-shell", className)}
        style={{
          ...style,
          display: "grid",
          gap: 16,
          padding: 16,
          borderRadius: 20,
          border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
          background: "var(--workspace-surface, rgba(255, 255, 255, 0.76))",
          boxShadow: "0 18px 48px rgba(15, 23, 42, 0.06)",
        }}
      >
        <div style={{ display: "grid", gap: 8 }}>
          <strong style={{ fontSize: 18 }}>Workflow DAG</strong>
          <p style={{ margin: 0, color: "var(--workspace-muted, #64748b)" }}>等待 workflow 载入后显示 DAG 结构和节点详情。</p>
        </div>
      </div>
    );
  }

  const selectedArtifactMatches = activeNode ? activeNode.matched_artifacts : [];

  return (
    <div
      className={joinClasses("workflow-dag-shell", className)}
      style={{
        ...style,
        display: "grid",
        gap: 16,
        padding: 16,
        borderRadius: 20,
        border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
        background:
          "linear-gradient(180deg, var(--workspace-surface, rgba(255, 255, 255, 0.76)) 0%, var(--workspace-surface-muted, rgba(248, 250, 252, 0.96)) 100%)",
        boxShadow: "0 18px 48px rgba(15, 23, 42, 0.06)",
      }}
    >
      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <div style={{ display: "grid", gap: 4 }}>
            <strong style={{ fontSize: 18 }}>{workflow.name || "Workflow DAG"}</strong>
            <span style={{ color: "var(--workspace-muted, #64748b)", fontSize: 13 }}>
              {workflow.workflow_id} · {workflow.version || "draft"} · {stateBadgeLabel(runState)}
            </span>
          </div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              borderRadius: 999,
              border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
              background: "rgba(255, 255, 255, 0.66)",
              color: "#0f172a",
              fontSize: 13,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: stateBadgeTone(runState).color,
              }}
            />
            {selectedRun ? `${selectedRun.run_id} · ${selectedRun.status}` : "未选择 run"}
          </div>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 12,
          }}
        >
          <StatPill label="Nodes" value={workflow.nodes.length} />
          <StatPill label="Edges" value={workflow.edges.length} />
          <StatPill label="Roots / Leaves" value={`${model.roots.length} / ${model.leaves.length}`} />
          <StatPill label="Artifacts" value={`${artifactAvailableCount}/${artifacts.length}`} />
          <StatPill label="Bundle" value={compilePreview?.bundle_id || "pending"} />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: `minmax(0, 1fr) minmax(${DETAIL_MIN_WIDTH}px, 360px)`,
          gap: 16,
          alignItems: "start",
        }}
      >
        <section
          aria-label="Workflow DAG canvas"
          style={{
            minWidth: 0,
            overflow: "auto",
            borderRadius: 18,
            border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
            background: "rgba(255, 255, 255, 0.72)",
            padding: 12,
          }}
        >
          <div
            style={{
              position: "relative",
              width: Math.max(model.width, 760),
              height: Math.max(model.height, 280),
              minWidth: "100%",
            }}
          >
            <svg
              width={Math.max(model.width, 760)}
              height={Math.max(model.height, 280)}
              viewBox={`0 0 ${Math.max(model.width, 760)} ${Math.max(model.height, 280)}`}
              style={{
                position: "absolute",
                inset: 0,
                pointerEvents: "none",
                overflow: "visible",
              }}
              aria-hidden="true"
            >
              <defs>
                <marker id="workflow-dag-arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(71, 85, 105, 0.85)" />
                </marker>
              </defs>
              {model.edges.map((edge) => (
                <g key={edge.edge_id}>
                  <path
                    d={edgePath(edge)}
                    fill="none"
                    stroke={edge.selected ? "#2563eb" : "rgba(71, 85, 105, 0.45)"}
                    strokeWidth={edge.selected ? 2.5 : 1.6}
                    strokeDasharray={edge.selected ? "0" : "6 4"}
                    markerEnd="url(#workflow-dag-arrow)"
                  />
                </g>
              ))}
            </svg>

            {model.nodes.map((node) => {
              const tone = stateBadgeTone(node.state);
              return (
                <button
                  key={node.node_id}
                  type="button"
                  onClick={() => onSelectNode?.(node.node_id)}
                  aria-pressed={node.selected}
                  title={`${node.label} · ${node.tool_id}`}
                  style={{
                    position: "absolute",
                    left: node.x,
                    top: node.y,
                    width: node.width,
                    minHeight: node.height,
                    padding: 14,
                    borderRadius: 18,
                    border: `1px solid ${node.selected ? "#2563eb" : "rgba(15, 23, 42, 0.14)"}`,
                    background: node.selected
                      ? "linear-gradient(180deg, rgba(37, 99, 235, 0.12) 0%, rgba(255, 255, 255, 0.96) 100%)"
                      : "linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(248, 250, 252, 0.96) 100%)",
                    boxShadow: node.selected ? "0 18px 36px rgba(37, 99, 235, 0.14)" : "0 14px 32px rgba(15, 23, 42, 0.08)",
                    textAlign: "left",
                    cursor: "pointer",
                    color: "inherit",
                  }}
                >
                  <div style={{ display: "grid", gap: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                      <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
                        <strong style={{ fontSize: 14, lineHeight: 1.2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {node.label}
                        </strong>
                        <span style={{ fontSize: 12, color: "var(--workspace-muted, #64748b)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {node.tool_id}
                        </span>
                      </div>
                      <span
                        style={{
                          padding: "4px 8px",
                          borderRadius: 999,
                          border: `1px solid ${tone.border}`,
                          background: tone.background,
                          color: tone.color,
                          fontSize: 11,
                          fontWeight: 700,
                          flexShrink: 0,
                        }}
                      >
                        {stateBadgeLabel(node.state)}
                      </span>
                    </div>

                    <div style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <span>Node</span>
                        <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>{node.node_id}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <span>Edges</span>
                        <span>
                          {node.upstream.length} in · {node.downstream.length} out
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                        <span>Artifacts</span>
                        <span>{node.matched_artifacts.length}</span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <aside
          style={{
            display: "grid",
            gap: 16,
            minWidth: 0,
          }}
        >
          <section
            style={{
              display: "grid",
              gap: 12,
              padding: 16,
              borderRadius: 18,
              border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
              background: "rgba(255, 255, 255, 0.76)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
              <strong>Selected Node</strong>
              <span style={{ fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>{activeNode ? activeNode.node_id : "none"}</span>
            </div>
            {activeNode ? (
              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ display: "grid", gap: 4 }}>
                  <strong style={{ fontSize: 16 }}>{activeNode.label}</strong>
                  <span style={{ color: "var(--workspace-muted, #64748b)", fontSize: 13 }}>{activeNode.tool_id}</span>
                </div>
                <div
                  style={{
                    display: "grid",
                    gap: 6,
                    padding: 12,
                    borderRadius: 14,
                    border: "1px solid rgba(15, 23, 42, 0.10)",
                    background: "rgba(248, 250, 252, 0.92)",
                    fontSize: 12,
                    color: "var(--workspace-muted, #64748b)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>Depth</span>
                    <span>{activeNode.depth}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>Upstream</span>
                    <span>{activeNode.upstream.length}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>Downstream</span>
                    <span>{activeNode.downstream.length}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>Artifacts</span>
                    <span>{activeNode.matched_artifacts.length}</span>
                  </div>
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  <strong style={{ fontSize: 13 }}>Upstream</strong>
                  {activeNode.upstream.length > 0 ? (
                    activeNode.upstream.map((nodeId) => (
                      <button
                        key={nodeId}
                        type="button"
                        onClick={() => onSelectNode?.(nodeId)}
                        style={{
                          padding: "8px 10px",
                          borderRadius: 12,
                          border: "1px solid rgba(15, 23, 42, 0.12)",
                          background: "rgba(255, 255, 255, 0.86)",
                          textAlign: "left",
                          cursor: "pointer",
                        }}
                      >
                        {nodeId}
                      </button>
                    ))
                  ) : (
                    <p style={{ margin: 0, color: "var(--workspace-muted, #64748b)", fontSize: 12 }}>No upstream nodes.</p>
                  )}
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  <strong style={{ fontSize: 13 }}>Downstream</strong>
                  {activeNode.downstream.length > 0 ? (
                    activeNode.downstream.map((nodeId) => (
                      <button
                        key={nodeId}
                        type="button"
                        onClick={() => onSelectNode?.(nodeId)}
                        style={{
                          padding: "8px 10px",
                          borderRadius: 12,
                          border: "1px solid rgba(15, 23, 42, 0.12)",
                          background: "rgba(255, 255, 255, 0.86)",
                          textAlign: "left",
                          cursor: "pointer",
                        }}
                      >
                        {nodeId}
                      </button>
                    ))
                  ) : (
                    <p style={{ margin: 0, color: "var(--workspace-muted, #64748b)", fontSize: 12 }}>No downstream nodes.</p>
                  )}
                </div>

                <div style={{ display: "grid", gap: 8 }}>
                  <strong style={{ fontSize: 13 }}>Matched Artifacts</strong>
                  {selectedArtifactMatches.length > 0 ? (
                    selectedArtifactMatches.map((artifact) => (
                      <div
                        key={`${artifact.name}-${artifact.remote_path}`}
                        style={{
                          display: "grid",
                          gap: 4,
                          padding: 10,
                          borderRadius: 12,
                          border: "1px solid rgba(15, 23, 42, 0.10)",
                          background: "rgba(248, 250, 252, 0.92)",
                        }}
                      >
                        <strong style={{ fontSize: 12 }}>{artifact.name}</strong>
                        <span style={{ fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>
                          {artifact.available ? artifact.local_path || artifact.remote_path : artifact.error || "missing"}
                        </span>
                      </div>
                    ))
                  ) : (
                    <p style={{ margin: 0, color: "var(--workspace-muted, #64748b)", fontSize: 12 }}>No artifact matches for this node yet.</p>
                  )}
                </div>
              </div>
            ) : (
              <p style={{ margin: 0, color: "var(--workspace-muted, #64748b)" }}>Select a node to inspect its position, connectivity, and artifact matches.</p>
            )}
          </section>

          <section
            style={{
              display: "grid",
              gap: 12,
              padding: 16,
              borderRadius: 18,
              border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
              background: "rgba(255, 255, 255, 0.76)",
            }}
          >
            <strong>Compile Preview</strong>
            <div style={{ display: "grid", gap: 8, fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Files</span>
                <span>{compileFiles.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Manifest keys</span>
                <span>{compileManifestKeys.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Bundle</span>
                <span>{compilePreview?.bundle_id || "pending"}</span>
              </div>
            </div>
            <pre
              style={{
                margin: 0,
                padding: 12,
                borderRadius: 12,
                border: "1px solid rgba(15, 23, 42, 0.10)",
                background: "rgba(248, 250, 252, 0.96)",
                overflow: "auto",
                maxHeight: 220,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                lineHeight: 1.45,
              }}
            >
              {compilePreview
                ? JSON.stringify(
                    {
                      bundle_id: compilePreview.bundle_id,
                      files: compileFiles,
                      manifest_keys: compileManifestKeys,
                      main_nf_preview: compilePreview.files["main.nf"]?.split("\n").slice(0, 20).join("\n") || "",
                    },
                    null,
                    2
                  )
                : "{}"}
            </pre>
          </section>

          <section
            style={{
              display: "grid",
              gap: 12,
              padding: 16,
              borderRadius: 18,
              border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
              background: "rgba(255, 255, 255, 0.76)",
            }}
          >
            <strong>Run Summary</strong>
            <div style={{ display: "grid", gap: 8, fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Status</span>
                <span>{selectedRun?.status || "none"}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Backend</span>
                <span>{selectedRun?.backend_kind || "unknown"}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Executor</span>
                <span>{selectedRun?.executor || "unknown"}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Packaging</span>
                <span>{selectedRun?.packaging_mode || "unknown"}</span>
              </div>
            </div>
          </section>

          <section
            style={{
              display: "grid",
              gap: 12,
              padding: 16,
              borderRadius: 18,
              border: "1px solid var(--workspace-border, rgba(15, 23, 42, 0.12))",
              background: "rgba(255, 255, 255, 0.76)",
            }}
          >
            <strong>Artifacts</strong>
            <div style={{ display: "grid", gap: 8, fontSize: 12, color: "var(--workspace-muted, #64748b)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Available</span>
                <span>{artifactAvailableCount}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span>Missing</span>
                <span>{artifactMissingCount}</span>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

export default WorkflowDag;
