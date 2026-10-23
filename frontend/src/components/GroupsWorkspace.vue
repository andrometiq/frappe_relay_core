<script setup>
import { defineAsyncComponent, ref } from 'vue'
import { Button } from '@relay/ui'
const WhatsApp = defineAsyncComponent(() => import('./WhatsAppWorkspace.vue'))
const Telegram = defineAsyncComponent(() => import('./TelegramGroups.vue'))
const provider = ref('WhatsApp')
</script>
<template>
 <section class="flex flex-col min-h-0 flex-1">
  <div class="toolbar gap-2" role="tablist" aria-label="Group channel"><Button v-for="channel in ['WhatsApp','Telegram']" :key="channel" :label="channel" role="tab" :aria-selected="provider===channel" :variant="provider===channel?'subtle':'ghost'" @click="provider=channel"/></div>
  <WhatsApp v-if="provider==='WhatsApp'" initial-tab="Groups" focused/>
  <Telegram v-else/>
 </section>
</template>
