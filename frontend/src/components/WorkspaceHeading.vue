<script setup>
import { FeatherIcon } from '@relay/ui'
defineProps({ title: String, description: String, icon: String })
</script>
<template>
  <header class="workspace-heading">
    <span v-if="icon" class="workspace-heading-icon"><FeatherIcon :name="icon" :size="20" /></span>
    <div class="workspace-heading-copy"><h2>{{ title }}</h2><p v-if="description">{{ description }}</p></div>
    <div v-if="$slots.default" class="workspace-heading-actions"><slot /></div>
  </header>
</template>
