"use client";

import type { WorkflowSpecView } from "./detection_workspace_types";

type WorkflowNodeListEditorProps = {
  workflow: WorkflowSpecView | null;
  onAddNode: () => void;
  onUpdateNode: (index: number, patch: Partial<WorkflowSpecView["nodes"][number]>) => void;
  onRemoveNode: (index: number) => void;
};

export function WorkflowNodeListEditor({
  workflow,
  onAddNode,
  onUpdateNode,
  onRemoveNode,
}: WorkflowNodeListEditorProps) {
  return (
    <div className="workflow-node-list">
      <div className="workflow-node-list-head">
        <strong>Steps</strong>
        <button type="button" className="control-btn" onClick={onAddNode}>
          添加 Step
        </button>
      </div>
      {workflow?.nodes.map((node, index) => (
        <div key={node.node_id} className="workflow-node-row">
          <label className="control-field">
            <span>Label</span>
            <input className="control-input" value={node.label} onChange={(event) => onUpdateNode(index, { label: event.target.value })} />
          </label>
          <label className="control-field">
            <span>Tool ID</span>
            <input
              className="control-input"
              value={node.tool_id}
              onChange={(event) => onUpdateNode(index, { tool_id: event.target.value })}
              placeholder="tool_placeholder"
            />
          </label>
          <button type="button" className="control-btn" onClick={() => onRemoveNode(index)} disabled={(workflow?.nodes.length || 0) <= 1}>
            删除
          </button>
        </div>
      ))}
    </div>
  );
}
