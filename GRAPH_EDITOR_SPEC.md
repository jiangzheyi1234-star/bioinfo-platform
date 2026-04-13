# Workflow Graph Editor Spec

## Objective
Replace the custom SVG DAG view with a React Flow-based editor that preserves existing workflow semantics and current `/workspace` run operations.

## Data Contract
- Source workflow data: `WorkflowSpecView`
- Source run data: `WorkflowRun | null`
- Source artifacts: `WorkflowArtifact[]`
- Selected node source of truth: `selectedNodeId`

## Node Mapping
- React Flow node id = `WorkflowNodeView.node_id`
- Node label = `WorkflowNodeView.label`
- Node subtitle = `WorkflowNodeView.tool_id`
- Node status badge = inferred from current run status using the existing DAG state mapping
- Node metadata panel includes upstream/downstream counts and matched artifact count

## Edge Mapping
- React Flow edge id = `WorkflowEdgeView.edge_id`
- Source = `source_node_id`
- Target = `target_node_id`
- Edge label = `output_name -> input_name` when either side is present

## Interactions
- Clicking a node updates `selectedNodeId`
- Editing node label/tool id stays in the existing form editor below the graph in this iteration
- Graph view is authoritative for structure visualization, not for creating/removing edges in this iteration

## Non-Goals
- No API contract change for workflow compile or run submission
- No persisted custom XY coordinates in this iteration
- No hidden fallback to the old SVG renderer
