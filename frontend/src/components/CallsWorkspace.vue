<script setup>
import { defineAsyncComponent } from 'vue'
import { Badge } from '@relay/ui'
const WhatsApp = defineAsyncComponent(() => import('./WhatsAppWorkspace.vue'))
</script>
<template><section class="flex flex-col min-h-0 flex-1"><div class="toolbar gap-3"><Badge label="WhatsApp" theme="green"/><span class="text-sm text-ink-gray-5">Voice calls</span></div><WhatsApp initial-tab="Calls" focused/></section></template>
