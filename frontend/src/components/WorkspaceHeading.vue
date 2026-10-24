<script setup>
defineProps({ description: String })
</script>
<template>
  <header v-if="description || $slots.default" class="workspace-heading" :class="{ 'workspace-heading--description': !$slots.default }">
    <p v-if="description" class="workspace-heading-copy">{{ description }}</p>
    <div v-if="$slots.default" class="workspace-heading-actions"><slot /></div>
  </header>
</template>
