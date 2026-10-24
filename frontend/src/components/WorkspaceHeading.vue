<script setup>
defineProps({ title: String, description: String })
</script>
<template>
  <header class="workspace-heading">
    <div class="workspace-heading-copy"><h2>{{ title }}</h2><p v-if="description">{{ description }}</p></div>
    <div v-if="$slots.default" class="workspace-heading-actions"><slot /></div>
  </header>
</template>
