export const WORKFLOW_TOOL_DRAG_MIME = "application/x-h2ometa-workflow-tool-revision";

export function workflowToolDragPayload(toolRevisionId: string): string {
  return toolRevisionId.trim();
}

export function readWorkflowToolDrop(dataTransfer: DataTransfer): string {
  return dataTransfer.getData(WORKFLOW_TOOL_DRAG_MIME).trim();
}
