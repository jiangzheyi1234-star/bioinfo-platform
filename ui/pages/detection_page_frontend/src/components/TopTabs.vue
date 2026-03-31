<template>
  <nav class="top-tabs" aria-label="检测页导航">
    <button
      v-for="item in tabs"
      :key="item.id"
      type="button"
      class="top-tab"
      :class="{ 'is-active': activeTab === item.id }"
      @click="$emit('change', item.id)"
    >
      {{ item.label }}
    </button>
  </nav>
</template>

<script setup>
defineProps({
  activeTab: {
    type: String,
    required: true,
  },
});

defineEmits(['change']);

const tabs = [
  { id: 'tools', label: '工具' },
  { id: 'history', label: '运行历史' },
  { id: 'integrated', label: '结果工作台' },
  { id: 'database', label: '数据库' },
];
</script>
