import { historyStore } from './historyStore';
import { loadHistoryRecords, normalizeHistoryStatus, selectHistoryExecution } from './historyActions';
import { setActiveTab } from './uiStore';
import { loadExecutionResultPreview, loadWorkbenchConfig, syncWorkbenchSelectionFromHistory } from './workbenchActions';

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
    const matchedFeatureId = syncWorkbenchSelectionFromHistory(record);
    await loadExecutionResultPreview(executionId, {
      record,
      activate: !matchedFeatureId,
    });
    return;
  }

  setActiveTab('history');
}
