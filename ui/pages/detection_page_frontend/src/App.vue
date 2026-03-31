<template>
  <main class="app-shell">
    <header class="app-header">
      <div>
        <p class="section-kicker">Vue Harness</p>
        <h1>H2OMeta 检测页迁移</h1>
        <p class="section-subtitle">
          当前处于 Phase 2：只读区块接管。Python bridge、执行链和结果协议保持冻结。
        </p>
      </div>
      <div class="bridge-state">
        <span class="bridge-label">Bridge</span>
        <span class="status-pill" :data-ready="bridgeState.ready ? '1' : '0'">
          {{ bridgeState.ready ? 'connected' : 'waiting' }}
        </span>
      </div>
    </header>

    <TopTabs :active-tab="uiStore.activeTab" @change="setActiveTab" />
    <InlineNotice :message="uiStore.notice.message" :tone="uiStore.notice.tone" />

    <section v-if="uiStore.activeTab === 'history'" class="content-grid">
      <HistoryPanel
        :records="filteredHistoryRecords"
        :search-text="historyStore.searchText"
        :selected-execution-id="historyStore.selectedExecutionId"
        :loading="historyStore.loading"
        @refresh="reloadReadOnlyData"
        @search="setHistorySearchText"
        @select="handleHistorySelect"
      />
      <section class="surface">
        <div class="section-header compact">
          <div>
            <p class="section-kicker">Selection</p>
            <h2>历史详情</h2>
          </div>
        </div>
        <pre class="detail-pre">{{ JSON.stringify(selectedHistoryRecord || {}, null, 2) }}</pre>
      </section>
    </section>

    <WorkbenchPanel
      v-else-if="uiStore.activeTab === 'integrated'"
      :title="workbenchStore.title"
      :subtitle="workbenchStore.subtitle"
      :features="workbenchStore.features"
      :views="workbenchStore.views"
      :execution-views="workbenchStore.executionViews"
      :selected-feature-id="workbenchStore.selectedFeatureId"
      :loading="workbenchStore.loading"
      :selected-execution-record="selectedHistoryRecord"
      @refresh="reloadReadOnlyData"
      @select-feature="selectWorkbenchFeature"
    />

    <section v-else class="surface placeholder-surface">
      <div class="section-header compact">
        <div>
          <p class="section-kicker">Legacy Ownership</p>
          <h2>{{ uiStore.activeTab === 'tools' ? '工具工作台' : '数据库管理' }}</h2>
        </div>
      </div>
      <p class="section-subtitle">
        当前阶段不接管此区域，仍由 legacy detection page 负责。Phase 3 才会迁移工具配置与运行入口。
      </p>
    </section>
  </main>
</template>

<script setup>
import { computed, inject, onMounted, watch } from 'vue';
import TopTabs from './components/TopTabs.vue';
import InlineNotice from './components/InlineNotice.vue';
import HistoryPanel from './components/HistoryPanel.vue';
import WorkbenchPanel from './components/WorkbenchPanel.vue';
import { historyStore } from './stores/historyStore';
import { normalizeHistoryStatus, selectHistoryExecution, setHistorySearchText } from './stores/historyActions';
import { uiStore, setActiveTab, setNotice } from './stores/uiStore';
import { workbenchStore } from './stores/workbenchStore';
import { loadExecutionResultPreview, selectWorkbenchFeature, syncWorkbenchSelectionFromHistory } from './stores/workbenchActions';
import { reloadReadOnlyShell, syncFromExecutionUpdate, syncFromRunPayload } from './stores/runtimeSync';

const bridgeState = inject('bridgeState');

const filteredHistoryRecords = computed(() => {
  const keyword = String(historyStore.searchText || '').trim().toLowerCase();
  if (!keyword) {
    return historyStore.records;
  }
  return historyStore.records.filter((record) => {
    const haystack = [
      record?.execution_id,
      record?.tool_id,
      record?.sample_name,
      record?.sample_id,
      record?.parameters,
      record?.status,
    ]
      .join(' ')
      .toLowerCase();
    return haystack.includes(keyword);
  });
});

const selectedHistoryRecord = computed(() => {
  const targetId = String(historyStore.selectedExecutionId || '').trim();
  if (!targetId) {
    return null;
  }
  return historyStore.records.find((item) => String(item?.execution_id || '').trim() === targetId) || null;
});

async function reloadReadOnlyData() {
  if (!bridgeState?.ready) {
    return;
  }
  await reloadReadOnlyShell();
}

async function handleHistorySelect(record) {
  selectHistoryExecution(record?.execution_id);
  if (normalizeHistoryStatus(record?.status) === 'completed') {
    const matchedFeatureId = syncWorkbenchSelectionFromHistory(record);
    await loadExecutionResultPreview(record?.execution_id, {
      record,
      activate: !matchedFeatureId,
    });
  }
}

onMounted(async () => {
  if (bridgeState?.ready) {
    await reloadReadOnlyData();
    return;
  }
  if (bridgeState?.error) {
    setNotice(bridgeState.error, 'warning');
  }
});

watch(
  () => bridgeState?.ready,
  async (ready) => {
    if (ready) {
      await reloadReadOnlyData();
    }
  },
  { immediate: false },
);

watch(
  () => bridgeState?.lastRunPayload,
  async (payload) => {
    if (!payload || !bridgeState?.ready) {
      return;
    }
    await syncFromRunPayload(payload);
  },
  { deep: false },
);

watch(
  () => bridgeState?.lastExecutionPayload,
  async (payload) => {
    if (!payload || !bridgeState?.ready) {
      return;
    }
    await syncFromExecutionUpdate(payload);
  },
  { deep: false },
);
</script>
