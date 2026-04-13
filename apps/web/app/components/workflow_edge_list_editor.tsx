"use client";

import type { WorkflowSpecView } from "./detection_workspace_types";

type WorkflowEdgeListEditorProps = {
  workflow: WorkflowSpecView | null;
  onUpdateEdge: (edgeId: string, patch: Partial<WorkflowSpecView["edges"][number]>) => void;
  onRemoveEdge: (edgeId: string) => void;
};

export function WorkflowEdgeListEditor({ workflow, onUpdateEdge, onRemoveEdge }: WorkflowEdgeListEditorProps) {
  return (
    <div className="workflow-node-list">
      <div className="workflow-node-list-head">
        <strong>Connections</strong>
        <span className="muted">在图上拖拽连线，必要时补全 input/output 名称。</span>
      </div>
      {workflow?.edges.length ? (
        workflow.edges.map((edge) => (
          <div key={edge.edge_id} className="workflow-node-row">
            <label className="control-field">
              <span>Source → Target</span>
              <input
                className="control-input"
                value={`${edge.source_node_id} → ${edge.target_node_id}`}
                disabled
                readOnly
              />
            </label>
            <label className="control-field">
              <span>Output</span>
              <input className="control-input" value={edge.output_name} onChange={(event) => onUpdateEdge(edge.edge_id, { output_name: event.target.value })} />
            </label>
            <label className="control-field">
              <span>Input</span>
              <input className="control-input" value={edge.input_name} onChange={(event) => onUpdateEdge(edge.edge_id, { input_name: event.target.value })} />
            </label>
            <button type="button" className="control-btn" onClick={() => onRemoveEdge(edge.edge_id)}>
              删除连线
            </button>
          </div>
        ))
      ) : (
        <p className="workflow-console-inline-note">暂无连线；可直接在图上从右侧拖到目标节点左侧创建。</p>
      )}
    </div>
  );
}
