<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'

// A record's details beside its list on desktop; a full-screen sheet on phones.
defineProps({ title: String, label: String, wide: Boolean })
const emit = defineEmits(['close'])
const isMobile = useMobileLayout()
const panel = ref(null)
onMounted(async () => {
  if (!isMobile.value) return
  await nextTick()
  panel.value?.querySelector('.side-panel-close')?.focus()
})
</script>

<template>
  <aside ref="panel" class="side-panel" :class="{ 'is-sheet': isMobile, 'is-wide': wide }" :aria-label="label || title"
    :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile || undefined" @keydown.esc="emit('close')">
    <header class="side-panel-head">
      <button v-if="isMobile" type="button" class="side-panel-close" :aria-label="`Close ${label || title}`" @click="emit('close')"><FeatherIcon name="chevron-left" :size="20" /></button>
      <slot name="title"><h2 :title="title">{{ title }}</h2></slot>
      <div class="side-panel-actions"><slot name="actions" /></div>
      <button v-if="!isMobile" type="button" class="side-panel-close" :aria-label="`Close ${label || title}`" @click="emit('close')"><FeatherIcon name="x" /></button>
    </header>
    <div class="side-panel-body"><slot /></div>
    <footer v-if="$slots.footer" class="side-panel-foot"><slot name="footer" /></footer>
  </aside>
</template>
