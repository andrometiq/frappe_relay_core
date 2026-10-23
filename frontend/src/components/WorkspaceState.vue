<script setup>
import { FeatherIcon } from '@relay/ui'
defineProps({ title: String, description: String, icon: { type: String, default: 'inbox' }, compact: Boolean })
</script>
<template>
  <div class="workspace-state" :class="{ 'workspace-state--compact': compact }">
    <span class="workspace-state-icon"><FeatherIcon :name="icon" :size="24" /></span>
    <h3>{{ title }}</h3><p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" class="workspace-state-action"><slot /></div>
  </div>
</template>
