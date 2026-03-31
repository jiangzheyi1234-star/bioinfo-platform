import { historyStore } from './historyStore';
import { loadHistoryRecords, normalizeHistoryStatus, selectHistoryExecution } from './historyActions';
import { setActiveTab } from './uiStore';
import { loadWorkbenchConfig, syncWorkbenchSelectionFromHistory } from './workbenchActions';

function findHistoryRecord(executionId) {
  const targetId = String(executionId || '').trim();
  if (!targetId) {
    return null;
  }
  return historyStore.records.find((item) => String(item?.execution_id || '').trim() === targetId) || null;
}

export async function reloadReadOnlyShell() {
  await Promise.all([
    loadHistoryRecords(),
    loadWorkbenchConfig(true),
  ]);
}

export async function syncFromRunPayload(payload) {
  const executionId = String(payload?.execution_id || '').trim();
  if (!executionId) {
    return;
  }
  await reloadReadOnlyShell();
  selectHistoryExecution(executionId);
  setActiveTab('history');
}

export async function syncFromExecutionUpdate(payload) {
  const executionId = String(payload?.execution_id || '').trim();
  if (!executionId) {
    return;
  }

  await reloadReadOnlyShell();
  selectHistoryExecution(executionId);

  const record = findHistoryRecord(executionId);
  if (!record) {
    setActiveTab('history');
    return;
  }

  if (normalizeHistoryStatus(record.status) === 'completed') {
    syncWorkbenchSelectionFromHistory(record);
    return;
  }

  setActiveTab('history');
}
