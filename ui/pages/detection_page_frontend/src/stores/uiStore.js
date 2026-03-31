import { reactive } from 'vue';

export const uiStore = reactive({
  activeTab: 'history',
  notice: {
    message: '',
    tone: 'info',
  },
  sidebarCollapsed: false,
});

export function setActiveTab(tab) {
  uiStore.activeTab = String(tab || 'tools').trim() || 'tools';
}

export function setNotice(message, tone = 'info') {
  const normalizedMessage = String(message || '').trim();
  uiStore.notice = {
    message: normalizedMessage,
    tone: String(tone || 'info').trim() || 'info',
  };
}

export function clearNotice() {
  setNotice('', 'info');
}
