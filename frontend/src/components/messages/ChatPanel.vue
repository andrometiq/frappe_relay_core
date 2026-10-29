<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { Button } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'

// One side panel of the chat: right of the messages on wide screens, a full page on phones.
defineProps({ title: String, subtitle: String })
const emit = defineEmits(['close'])
const isMobile = useMobileLayout()
const panel = ref(null)
const origin = document.activeElement
onMounted(() => panel.value?.querySelector('button')?.focus({ preventScroll: true }))
onBeforeUnmount(() => { if (origin?.isConnected) origin.focus({ preventScroll: true }) })
</script>

<template>
  <aside ref="panel" class="chat-panel" :aria-label="title" @keydown.esc="emit('close')">
    <header class="chat-panel-head">
      <Button v-if="isMobile" icon="chevron-left" variant="ghost" aria-label="Close" title="Back" @click="emit('close')" />
      <div class="chat-panel-title"><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div>
      <Button v-if="!isMobile" icon="x" variant="ghost" aria-label="Close" title="Close" @click="emit('close')" />
    </header>
    <div class="chat-panel-body"><slot /></div>
  </aside>
</template>

<style scoped>
.chat-panel { display:flex; flex-direction:column; flex:none; width:360px; max-width:45%; min-height:0; border-left:1px solid var(--relay-stroke, var(--outline-gray-2)); background:var(--relay-layer, var(--surface-white)); color:var(--relay-ink, var(--ink-gray-8)); }
.chat-panel-head { display:flex; align-items:center; gap:8px; min-height:52px; padding:8px 8px 8px 16px; border-bottom:1px solid var(--relay-stroke, var(--outline-gray-2)); }
.chat-panel-head :deep(.relay-button) { width:44px; height:44px; min-height:44px; }
.chat-panel-title { flex:1; min-width:0; }
.chat-panel-title h2 { font-size:15px; font-weight:600; }
.chat-panel-title p { margin-top:2px; font-size:11px; color:var(--ink-gray-5); }
.chat-panel-body { display:flex; flex-direction:column; flex:1; min-height:0; overflow:auto; padding-bottom:env(safe-area-inset-bottom); }
@media (max-width: 768px) {
  .chat-panel { position:fixed; inset:0; z-index:60; width:auto; max-width:none; border-left:0; padding-top:env(safe-area-inset-top); background:var(--surface-white); }
  .chat-panel-head { padding-left:4px; }
}
</style>
