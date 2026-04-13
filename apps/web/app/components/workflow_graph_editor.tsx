"use client";

import { useMemo } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type OnNodeClick,
} from "@xyflow/react";

import type { WorkflowArtifact, WorkflowCompilePreview, WorkflowRun, WorkflowSpecView } from "./detection_workspace_types";
import { buildWorkflowDagModel, inferRunState, type WorkflowDagNodeState } from "./workflow_graph_model";

type WorkflowGraphEditorProps = {
  workflow: WorkflowSpecView | null;
  selectedRun: WorkflowRun | null;
  compilePreview: WorkflowCompilePreview | null;
  artifacts: WorkflowArtifact[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
};

type WorkflowGraphNodeData = {
  label: string;
  toolId: string;
  state: WorkflowDagNodeState;
  artifacts: number;
  upstream: number;
  downstream: number;
};

function stateColor(state: WorkflowDagNodeState) {
  switch (state) {
    case "running":
      return "#2563eb";
    case "completed":
      return "#15803d";
    case "failed":
      return "#b91c1c";
    case "compiled":
      return "#0369a1";
    default:
      return "#64748b";
  }
}

function StateLabel(state: WorkflowDagNodeState) {
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

function WorkflowNodeCard({ data, selected }: NodeProps<Node<WorkflowGraphNodeData>>) {
  const accent = stateColor(data.state);
  return (
    <div
      style={{
        minWidth: 220,
        borderRadius: 18,
        border: selected ? `2px solid ${accent}` : "1px solid rgba(15, 23, 42, 0.12)",
        background: "rgba(255, 255, 255, 0.95)",
        boxShadow: selected ? `0 18px 40px ${accent}22` : "0 14px 30px rgba(15, 23, 42, 0.08)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "10px 14px",
          background: `linear-gradient(135deg, ${accent} 0%, rgba(255,255,255,0.9) 180%)`,
          color: "#fff",
        }}
      >
        <strong style={{ display: "block", fontSize: 14 }}>{data.label}</strong>
        <span style={{ display: "block", marginTop: 4, fontSize: 12, opacity: 0.92 }}>{data.toolId}</span>
      </div>
      <div style={{ padding: 14, display: "grid", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12, color: "#475569" }}>
          <span>{StateLabel(data.state)}</span>
          <span>{data.artifacts} artifacts</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span className="workflow-graph-pill">in {data.upstream}</span>
          <span className="workflow-graph-pill">out {data.downstream}</span>
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { workflowNode: WorkflowNodeCard };

export function WorkflowGraphEditor({
  workflow,
  selectedRun,
  compilePreview,
  artifacts,
  selectedNodeId,
  onSelectNode,
}: WorkflowGraphEditorProps) {
  const model = useMemo(() => {
    if (!workflow) {
      return null;
    }
    return buildWorkflowDagModel(workflow, selectedRun, artifacts, selectedNodeId);
  }, [workflow, selectedRun, artifacts, selectedNodeId]);

  const nodes = useMemo<Node<WorkflowGraphNodeData>[]>(() => {
    if (!model) {
      return [];
    }
    return model.nodes.map((node) => ({
      id: node.node_id,
      type: "workflowNode",
      position: { x: node.x, y: node.y },
      selectable: true,
      draggable: false,
      data: {
        label: node.label,
        toolId: node.tool_id,
        state: node.state,
        artifacts: node.matched_artifacts.length,
        upstream: node.upstream.length,
        downstream: node.downstream.length,
      },
    }));
  }, [model]);

  const edges = useMemo<Edge[]>(() => {
    if (!model) {
      return [];
    }
    return model.edges.map((edge) => ({
      id: edge.edge_id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      animated: edge.selected || inferRunState(selectedRun) === "running",
      label: [edge.output_name, edge.input_name].filter(Boolean).join(" -> "),
      style: {
        stroke: edge.selected ? "#0f172a" : "rgba(51, 65, 85, 0.45)",
        strokeWidth: edge.selected ? 2.2 : 1.5,
      },
      labelStyle: {
        fill: "#334155",
        fontSize: 11,
      },
    }));
  }, [model, selectedRun]);

  const onNodeClick: OnNodeClick<Node<WorkflowGraphNodeData>> = (_event, node) => {
    onSelectNode?.(node.id);
  };

  const headline = workflow ? `${workflow.nodes.length} nodes · ${workflow.edges.length} edges` : "等待 workflow 初始化";
  const bundleId = compilePreview?.bundle_id || "pending";

  if (!workflow || !model) {
    return (
      <div className="workflow-graph-shell">
        <div className="workflow-graph-empty">
          <strong>Workflow Graph</strong>
          <span>等待 workflow 载入后显示 React Flow 视图。</span>
        </div>
      </div>
    );
  }

  return (
    <div className="workflow-graph-shell">
      <div className="workflow-graph-header">
        <div>
          <strong>{workflow.name || "Workflow Graph"}</strong>
          <span>{headline}</span>
        </div>
        <div className="workflow-graph-header-meta">
          <span className="workflow-graph-pill">bundle {bundleId}</span>
          <span className="workflow-graph-pill">{selectedRun ? selectedRun.status : "draft"}</span>
        </div>
      </div>
      <div className="workflow-graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={onNodeClick}
        >
          <Background color="rgba(148, 163, 184, 0.24)" gap={20} />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
