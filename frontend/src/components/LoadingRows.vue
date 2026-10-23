<script setup>
defineProps({ label: { type: String, default: 'Loading records…' }, count: { type: Number, default: 4 } })
</script>
<template>
  <div class="loading-rows" role="status" :aria-label="label">
    <span class="sr-only">{{ label }}</span>
    <div v-for="index in count" :key="index" class="loading-row" aria-hidden="true"><span /><div><i /><i /></div></div>
  </div>
</template>
