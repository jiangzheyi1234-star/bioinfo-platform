import { bridgeStore } from '../stores/bridgeStore';

function getBridge() {
  const bridge = bridgeStore.bridge;
  if (!bridge) {
    throw new Error('QWebChannel bridge 尚未连接');
  }
  return bridge;
}

function invokeBridge(methodName, ...args) {
  return new Promise((resolve, reject) => {
    let bridge;
    try {
      bridge = getBridge();
    } catch (error) {
      reject(error);
      return;
    }

    const method = bridge[methodName];
    if (typeof method !== 'function') {
      reject(new Error(`Bridge 方法不可用: ${methodName}`));
      return;
    }

    try {
      method(...args, (json) => {
        resolve(String(json || ''));
      });
    } catch (error) {
      reject(error);
    }
  });
}

export function bridgeSupports(methodName) {
  return Boolean(bridgeStore.bridge && typeof bridgeStore.bridge[methodName] === 'function');
}

export function getExecutionHistory() {
  return invokeBridge('get_execution_history');
}

export function getIntegratedWorkbenchConfig() {
  return invokeBridge('get_integrated_workbench_config');
}

export function getResultsForExecution(executionId) {
  return invokeBridge('get_results_for_execution', String(executionId || '').trim());
}
