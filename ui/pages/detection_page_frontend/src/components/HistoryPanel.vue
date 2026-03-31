<template>
  <section class="surface">
    <div class="section-header">
      <div>
        <p class="section-kicker">只读迁移</p>
        <h2>运行历史</h2>
      </div>
      <button type="button" class="ghost-btn" @click="$emit('refresh')">刷新</button>
    </div>

    <label class="field-label" for="history-search">搜索</label>
    <input
      id="history-search"
      class="search-input"
      :value="searchText"
      type="text"
      placeholder="搜索 execution / tool / sample"
      @input="$emit('search', $event.target.value)"
    >

    <div class="history-list">
      <button
        v-for="record in records"
        :key="record.execution_id"
        type="button"
        class="history-row"
        :class="{ 'is-selected': selectedExecutionId === String(record.execution_id || '') }"
        @click="$emit('select', record)"
      >
        <span class="history-status" :data-status="normalizeStatus(record.status)">{{ record.status || 'unknown' }}</span>
        <div class="history-main">
          <div class="history-title">{{ record.sample_name || record.sample_id || record.execution_id }}</div>
          <div class="history-meta">{{ record.tool_id || '-' }} · {{ record.execution_id || '-' }}</div>
        </div>
        <div class="history-time">{{ formatTimestamp(record.started_at || record.created_at) }}</div>
      </button>

      <div v-if="!records.length && !loading" class="empty-state">
        暂无执行记录
      </div>
      <div v-if="loading" class="empty-state">
        正在加载执行历史…
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  records: {
    type: Array,
    default: () => [],
  },
  searchText: {
    type: String,
    default: '',
  },
  selectedExecutionId: {
    type: String,
    default: '',
  },
  loading: {
    type: Boolean,
    default: false,
  },
});

defineEmits(['refresh', 'search', 'select']);

function normalizeStatus(value) {
  return String(value || '').trim().toLowerCase() || 'unknown';
}

function formatTimestamp(value) {
  const text = String(value || '').trim();
  return text || '—';
}
</script>
