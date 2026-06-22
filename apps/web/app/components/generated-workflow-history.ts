export type WorkflowEditorHistory<T> = {
  past: T[];
  present: T;
  future: T[];
};

export function createWorkflowEditorHistory<T>(present: T): WorkflowEditorHistory<T> {
  return { past: [], present, future: [] };
}

export function replaceWorkflowEditorHistory<T>(
  history: WorkflowEditorHistory<T>,
  present: T
): WorkflowEditorHistory<T> {
  if (history.present === present) return history;
  return createWorkflowEditorHistory(present);
}

export function commitWorkflowEditorHistory<T>(
  history: WorkflowEditorHistory<T>,
  present: T,
  limit = 50
): WorkflowEditorHistory<T> {
  if (history.present === present) return history;
  return {
    past: [...history.past, history.present].slice(-Math.max(limit, 1)),
    present,
    future: [],
  };
}

export function undoWorkflowEditorHistory<T>(history: WorkflowEditorHistory<T>): WorkflowEditorHistory<T> {
  const present = history.past.at(-1);
  if (!present) return history;
  return {
    past: history.past.slice(0, -1),
    present,
    future: [history.present, ...history.future],
  };
}

export function redoWorkflowEditorHistory<T>(history: WorkflowEditorHistory<T>): WorkflowEditorHistory<T> {
  const present = history.future[0];
  if (!present) return history;
  return {
    past: [...history.past, history.present],
    present,
    future: history.future.slice(1),
  };
}

