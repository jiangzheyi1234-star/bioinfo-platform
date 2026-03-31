<template>
  <div v-if="message" class="inline-notice" :data-tone="tone">
    {{ message }}
  </div>
</template>

<script setup>
defineProps({
  message: {
    type: String,
    default: '',
  },
  tone: {
    type: String,
    default: 'info',
  },
});
</script>
