from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _component_source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_palette_cards_drag_tool_revision_ids_to_react_flow_canvas() -> None:
    builder = _component_source("generated-workflow-builder.tsx")
    canvas = _component_source("generated-workflow-graph-canvas.tsx")
    drag_drop = _component_source("generated-workflow-graph-drag-drop.ts")

    assert 'WORKFLOW_TOOL_DRAG_MIME = "application/x-h2ometa-workflow-tool-revision"' in drag_drop
    assert "workflowToolDragPayload(toolRevisionId)" in builder
    assert "event.dataTransfer.effectAllowed = \"copy\"" in builder
    assert "event.dataTransfer.setData(WORKFLOW_TOOL_DRAG_MIME, payload)" in builder
    assert "data-workflow-tool-revision-id={toolRevisionId}" in builder
    assert "draggable={Boolean(toolRevisionId)}" in builder
    assert "onDropTool={addToolAtPosition}" in builder

    assert "readWorkflowToolDrop(event.dataTransfer)" in canvas
    assert "event.dataTransfer.dropEffect = \"copy\"" in canvas
    assert "flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })" in canvas
    assert "onDropTool(" in canvas
    assert "onDragOver={onDragOver}" in canvas
    assert "onDrop={onDrop}" in canvas
    assert "pointer-events-none" in canvas


def test_dropped_steps_persist_position_through_single_history_commit() -> None:
    hook = _component_source("use-generated-workflow-builder.ts")

    assert 'type AddStepOptions = { position?: GraphNodePosition }' in hook
    assert 'addStep: (toolRevisionId: string, options: AddStepOptions = {})' in hook
    assert 'dispatch({ type: "add_step", position: options.position, tool, tools })' in hook
    assert 'graphNodeMetadataWithPosition(nextStep.metadata, action.position)' in hook
    assert 'steps: [...current.steps, positionedStep]' in hook
    assert "commitWorkflowEditorHistory(state.graphHistory, graphDraft)" in hook
    assert "screenToFlowPosition" not in hook
