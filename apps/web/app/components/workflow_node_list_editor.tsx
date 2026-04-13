"use client";

import type { WorkflowSpecView } from "./detection_workspace_types";
import { WORKFLOW_NODE_TEMPLATES } from "./workflow_support";

type WorkflowNodeListEditorProps = {
  workflow: WorkflowSpecView | null;
  selectedNodeId?: string;
  onSelectNode?: (nodeId: string) => void;
  onAddNode: (templateKey?: string) => void;
  onUpdateNode: (index: number, patch: Partial<WorkflowSpecView["nodes"][number]>) => void;
  onRemoveNode: (index: number) => void;
};

export function WorkflowNodeListEditor({
  workflow,
  selectedNodeId,
  onSelectNode,
  onAddNode,
  onUpdateNode,
  onRemoveNode,
}: WorkflowNodeListEditorProps) {
  return (
    <div className="workflow-node-list">
      <div className="workflow-node-list-head">
        <strong>Steps</strong>
        <span className="muted">从模板插入步骤，再在图上拖拽和连线。</span>
      </div>
      <div className="workflow-console-topbar">
        {WORKFLOW_NODE_TEMPLATES.map((template) => (
          <button key={template.key} type="button" className="control-btn" onClick={() => onAddNode(template.key)}>
            + {template.label}
          </button>
        ))}
      </div>
      {workflow?.nodes.map((node, index) => (
        <div
          key={node.node_id}
          className="workflow-node-row"
          style={selectedNodeId === node.node_id ? { borderColor: "var(--workspace-selection-border)", background: "var(--workspace-selection)" } : undefined}
        >
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
          <button type="button" className="control-btn" onClick={() => onSelectNode?.(node.node_id)}>
            聚焦
          </button>
          <button type="button" className="control-btn" onClick={() => onRemoveNode(index)} disabled={(workflow?.nodes.length || 0) <= 1}>
            删除
          </button>
        </div>
      ))}
    </div>
  );
}
