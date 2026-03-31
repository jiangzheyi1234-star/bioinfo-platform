<template>
  <section class="surface workbench-shell">
    <aside class="workbench-sidebar">
      <div class="section-header compact">
        <div>
          <p class="section-kicker">只读迁移</p>
          <h2>{{ title }}</h2>
        </div>
        <button type="button" class="ghost-btn" @click="$emit('refresh')">刷新</button>
      </div>
      <p v-if="subtitle" class="section-subtitle">{{ subtitle }}</p>

      <div class="feature-list">
        <button
          v-for="feature in features"
          :key="feature.id"
          type="button"
          class="feature-item"
          :class="{ 'is-active': selectedFeatureId === feature.id }"
          @click="$emit('select-feature', feature.id)"
        >
          <div class="feature-name">{{ feature.name || feature.id }}</div>
          <div class="feature-desc">{{ feature.description || '暂无描述' }}</div>
        </button>

        <div v-if="!features.length && !loading" class="empty-state">
          暂无结果工作台功能
        </div>
        <div v-if="loading" class="empty-state">
          正在加载结果工作台…
        </div>
      </div>
    </aside>

    <div class="workbench-detail">
      <div class="detail-hero">
        <div>
          <p class="section-kicker">Feature Preview</p>
          <h3>{{ selectedFeature?.name || '请选择左侧功能' }}</h3>
          <p class="section-subtitle">
            {{ selectedFeature?.description || 'Phase 2 只接管左侧功能导航和只读摘要，不接管结果渲染。' }}
          </p>
        </div>
        <span class="status-pill">{{ selectedFeature?.status || 'idle' }}</span>
      </div>

      <div class="detail-grid">
        <article class="detail-card">
          <h4>基础视图</h4>
          <p>{{ selectedViewSummary.base }}</p>
        </article>
        <article class="detail-card">
          <h4>历史结果缓存</h4>
          <p>{{ selectedViewSummary.execution }}</p>
        </article>
        <article class="detail-card">
          <h4>来自历史</h4>
          <p>{{ selectedRecordSummary }}</p>
        </article>
      </div>

      <div v-if="selectedExecutionView" class="detail-card">
        <h4>Execution 结果摘要</h4>
        <div class="preview-grid">
          <div class="preview-item">
            <span class="preview-label">Archetype</span>
            <strong>{{ selectedExecutionView.archetype || 'unknown' }}</strong>
          </div>
          <div class="preview-item">
            <span class="preview-label">Summary</span>
            <strong>{{ executionSummaryCount }}</strong>
          </div>
          <div class="preview-item">
            <span class="preview-label">Charts</span>
            <strong>{{ executionChartCount }}</strong>
          </div>
          <div class="preview-item">
            <span class="preview-label">Artifacts</span>
            <strong>{{ executionArtifactCount }}</strong>
          </div>
        </div>
      </div>

      <div class="detail-card">
        <h4>当前 feature 原始信息</h4>
        <pre class="detail-pre">{{ JSON.stringify(selectedFeature || {}, null, 2) }}</pre>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  title: {
    type: String,
    default: '结果工作台',
  },
  subtitle: {
    type: String,
    default: '',
  },
  features: {
    type: Array,
    default: () => [],
  },
  views: {
    type: Object,
    default: () => ({}),
  },
  executionViews: {
    type: Object,
    default: () => ({}),
  },
  selectedFeatureId: {
    type: String,
    default: '',
  },
  loading: {
    type: Boolean,
    default: false,
  },
  selectedExecutionRecord: {
    type: Object,
    default: null,
  },
});

defineEmits(['refresh', 'select-feature']);

const selectedFeature = computed(() => {
  return props.features.find((item) => String(item?.id || '') === props.selectedFeatureId) || null;
});

const selectedExecutionView = computed(() => {
  const featureId = String(props.selectedFeatureId || '').trim();
  if (!featureId) {
    return null;
  }
  return props.executionViews?.[featureId] || null;
});

const selectedViewSummary = computed(() => {
  const featureId = String(props.selectedFeatureId || '').trim();
  if (!featureId) {
    return {
      base: '尚未选择',
      execution: '尚未选择',
    };
  }

  const baseView = props.views?.[featureId];
  const executionView = props.executionViews?.[featureId];
  return {
    base: baseView ? `存在基础视图：${baseView.archetype || baseView.title || 'unnamed'}` : '无基础视图',
    execution: executionView ? `存在 execution 视图：${executionView.archetype || executionView.title || 'unnamed'}` : '暂无 execution 视图',
  };
});

const selectedRecordSummary = computed(() => {
  if (!props.selectedExecutionRecord) {
    return '当前未从运行历史定位 execution';
  }
  return `${props.selectedExecutionRecord.tool_id || '-'} · ${props.selectedExecutionRecord.execution_id || '-'}`;
});

const executionSummaryCount = computed(() => {
  return Array.isArray(selectedExecutionView.value?.summary)
    ? selectedExecutionView.value.summary.length
    : 0;
});

const executionChartCount = computed(() => {
  return Array.isArray(selectedExecutionView.value?.charts)
    ? selectedExecutionView.value.charts.length
    : 0;
});

const executionArtifactCount = computed(() => {
  return Array.isArray(selectedExecutionView.value?.artifacts)
    ? selectedExecutionView.value.artifacts.length
    : 0;
});
</script>
