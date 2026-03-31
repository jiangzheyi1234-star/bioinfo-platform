import { bridgeStore } from '../stores/bridgeStore';
import { setNotice } from '../stores/uiStore';

export const bridgeState = bridgeStore;

function normalizeMethods(bridge) {
  if (!bridge) {
    return [];
  }
  return Object.keys(bridge).filter((key) => typeof bridge[key] === 'function');
}

function attachCompatibilityCallbacks() {
  window._onRunResult = (payload) => {
    bridgeStore.lastRunPayload = payload || null;
    bridgeStore.lastRunResult = JSON.stringify(payload || {});
    bridgeStore.lastRunAt = new Date().toLocaleString();
    if (payload?.message) {
      setNotice(payload.message, payload?.status === 'failed' ? 'error' : 'success');
    }
  };

  window._onExecutionUpdate = (payload) => {
    bridgeStore.lastExecutionPayload = payload || null;
    bridgeStore.lastExecutionUpdate = JSON.stringify(payload || {});
    bridgeStore.lastExecutionAt = new Date().toLocaleString();
    if (payload?.message) {
      const tone = payload?.status === 'failed' ? 'error' : 'info';
      setNotice(payload.message, tone);
    }
  };
}

export function initBridge() {
  attachCompatibilityCallbacks();

  if (typeof window === 'undefined' || typeof window.QWebChannel === 'undefined' || typeof window.qt === 'undefined') {
    bridgeStore.host = 'browser';
    bridgeStore.error = 'Qt 宿主未注入，当前为浏览器开发壳。';
    return;
  }

  new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
    const bridge = channel.objects.bridge;
    bridgeStore.bridge = bridge || null;
    bridgeStore.ready = Boolean(bridge);
    bridgeStore.host = 'qt';
    bridgeStore.connectedAt = new Date().toLocaleString();
    bridgeStore.methods = normalizeMethods(bridge);
    window.bridge = bridge;
  });
}
