import { historyStore } from './historyStore';
import { setActiveTab, setNotice } from './uiStore';
import { getExecutionHistory } from '../bridge/api';

export async function loadHistoryRecords() {
  historyStore.loading = true;
  historyStore.error = '';
  try {
    const json = await getExecutionHistory();
    const payload = JSON.parse(json || '[]');
    historyStore.records = Array.isArray(payload) ? payload : [];
    return historyStore.records;
  } catch (error) {
    historyStore.error = String(error?.message || error || '执行历史读取失败');
    setNotice(historyStore.error, 'error');
    throw error;
  } finally {
    historyStore.loading = false;
  }
}

export function setHistorySearchText(value) {
  historyStore.searchText = String(value || '');
}

export function selectHistoryExecution(executionId) {
  historyStore.selectedExecutionId = String(executionId || '').trim();
  if (historyStore.selectedExecutionId) {
    setActiveTab('history');
  }
}

export function normalizeHistoryStatus(status) {
  return String(status || '').trim().toLowerCase();
}
