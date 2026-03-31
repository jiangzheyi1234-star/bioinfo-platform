<template>
  <section class="surface">
    <div class="section-header compact">
      <div>
        <p class="section-kicker">Harness Health</p>
        <h2>宿主与桥状态</h2>
      </div>
    </div>

    <div class="health-grid">
      <article class="detail-card">
        <h4>Host</h4>
        <p>{{ hostLabel }}</p>
      </article>
      <article class="detail-card">
        <h4>Bridge</h4>
        <p>{{ bridgeLabel }}</p>
      </article>
      <article class="detail-card">
        <h4>Last Run Callback</h4>
        <p>{{ lastRunLabel }}</p>
      </article>
      <article class="detail-card">
        <h4>Last Execution Callback</h4>
        <p>{{ lastExecutionLabel }}</p>
      </article>
    </div>

    <div v-if="error" class="inline-health-error">
      {{ error }}
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  host: { type: String, default: 'browser' },
  ready: { type: Boolean, default: false },
  connectedAt: { type: String, default: '' },
  lastRunAt: { type: String, default: '' },
  lastExecutionAt: { type: String, default: '' },
  error: { type: String, default: '' },
});

const hostLabel = computed(() => (props.host === 'qt' ? 'Qt 宿主已注入' : '浏览器开发壳'));
const bridgeLabel = computed(() => {
  if (!props.ready) return '等待 bridge 连接';
  return props.connectedAt ? `已连接 · ${props.connectedAt}` : '已连接';
});
const lastRunLabel = computed(() => props.lastRunAt || '尚未收到');
const lastExecutionLabel = computed(() => props.lastExecutionAt || '尚未收到');
</script>
