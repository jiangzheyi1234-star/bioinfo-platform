import { workbenchStore } from './workbenchStore';
import { historyStore } from './historyStore';
import { setActiveTab, setNotice } from './uiStore';
import { getIntegratedWorkbenchConfig, getResultsForExecution } from '../bridge/api';

function normalizeFeatureId(value) {
  return String(value || '').trim();
}

function resolveFeatureIdFromRecord(record) {
  const toolId = String(record?.tool_id || '').trim();
  if (!toolId) {
    return '';
  }
  if (toolId === 'centrifuge' || toolId === 'kraken2') {
    return toolId;
  }
  return toolId;
}

function resolveFeatureIdFromView(view, fallbackRecord = null) {
  const fromView = String(
    view?.feature_id
    || view?.view_id
    || view?.tool_id
    || ''
  ).trim();
  if (fromView) {
    return fromView;
  }
  return resolveFeatureIdFromRecord(fallbackRecord);
}

function ensureExecutionFeature(featureId, view) {
  const normalizedId = normalizeFeatureId(featureId);
  if (!normalizedId) {
    return;
  }
  const existing = workbenchStore.features.find((item) => String(item?.id || '').trim() === normalizedId);
  if (existing) {
    return;
  }
  workbenchStore.features = [
    ...workbenchStore.features,
    {
      id: normalizedId,
      name: String(view?.title || normalizedId),
      description: String(view?.description || ''),
      status: 'active',
      temporary: true,
    },
  ];
}

export async function loadWorkbenchConfig(forceRefresh = false) {
  if (!forceRefresh && workbenchStore.features.length) {
    return workbenchStore.features;
  }

  workbenchStore.loading = true;
  workbenchStore.error = '';
  try {
    const json = await getIntegratedWorkbenchConfig();
    const payload = JSON.parse(json || '{}');
    workbenchStore.title = String(payload?.title || '集成分析工作台');
    workbenchStore.subtitle = String(payload?.subtitle || '');
    workbenchStore.projectId = String(payload?.project_id || '');
    workbenchStore.features = Array.isArray(payload?.features) ? payload.features : [];
    workbenchStore.views = payload?.views && typeof payload.views === 'object' ? payload.views : {};
    if (!normalizeFeatureId(workbenchStore.selectedFeatureId) && workbenchStore.features.length) {
      const preferred = workbenchStore.features.find((item) => item?.status === 'active') || workbenchStore.features[0];
      workbenchStore.selectedFeatureId = String(preferred?.id || '');
    }
    return workbenchStore.features;
  } catch (error) {
    workbenchStore.error = String(error?.message || error || '结果工作台配置读取失败');
    setNotice(workbenchStore.error, 'error');
    throw error;
  } finally {
    workbenchStore.loading = false;
  }
}

export function selectWorkbenchFeature(featureId) {
  workbenchStore.selectedFeatureId = normalizeFeatureId(featureId);
  if (workbenchStore.selectedFeatureId) {
    setActiveTab('integrated');
  }
}

export function syncWorkbenchSelectionFromHistory(record) {
  const featureId = resolveFeatureIdFromRecord(record);
  if (!featureId) {
    return '';
  }
  const matched = workbenchStore.features.find((item) => String(item?.id || '').trim() === featureId);
  if (!matched) {
    return '';
  }
  historyStore.selectedExecutionId = String(record?.execution_id || '').trim();
  selectWorkbenchFeature(featureId);
  return featureId;
}

export async function loadExecutionResultPreview(executionId, options = {}) {
  const normalizedExecutionId = String(executionId || '').trim();
  if (!normalizedExecutionId) {
    return null;
  }

  workbenchStore.previewLoading = true;
  workbenchStore.previewExecutionId = normalizedExecutionId;
  workbenchStore.previewError = '';

  try {
    const json = await getResultsForExecution(normalizedExecutionId);
    const payload = JSON.parse(json || '{}');
    if (payload?.status !== 'ok' || !payload?.view) {
      throw new Error(payload?.message || '任务结果读取失败');
    }

    const featureId = resolveFeatureIdFromView(payload.view, options.record || null);
    if (!featureId) {
      throw new Error('任务结果缺少 feature_id/view_id/tool_id');
    }

    ensureExecutionFeature(featureId, payload.view);
    workbenchStore.executionViews = {
      ...workbenchStore.executionViews,
      [featureId]: {
        ...payload.view,
        __displaySource: 'history',
      },
    };

    if (options.activate !== false) {
      historyStore.selectedExecutionId = normalizedExecutionId;
      selectWorkbenchFeature(featureId);
    }

    return {
      featureId,
      view: payload.view,
    };
  } catch (error) {
    workbenchStore.previewError = String(error?.message || error || '任务结果读取失败');
    setNotice(workbenchStore.previewError, 'error');
    throw error;
  } finally {
    workbenchStore.previewLoading = false;
  }
}
