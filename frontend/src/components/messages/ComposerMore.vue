<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Button, FeatherIcon } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'
import { composerEmoji } from '../../services/composerActions'
import { focusableElements, overlayKeydown } from '../../services/overlayFocus'
const props = defineProps({ actions: { type: Array, default: () => [] }, disabled: Boolean, hasSticker: Boolean })
const emit = defineEmits(['action', 'emoji'])
const mobile = useMobileLayout(), open = ref(false), view = ref(''), trigger = ref(null), panel = ref(null), position = ref({})
const title = computed(() => ({ emoji: 'Emoji', sticker: 'Resend a sticker', details: 'Sending details' })[view.value] || 'Add to message')
const groups = computed(() => ['quick', 'attachments', 'secondary', 'details'].map(id => ({ id, actions: props.actions.filter(action => action.group === id) })).filter(group => group.actions.length))
function close() { open.value = false; view.value = ''; nextTick(() => trigger.value?.$el?.focus({ preventScroll: true })) }
async function toggle() {
  if (open.value) { close(); return }
  if (props.disabled) return
  const box = trigger.value.$el.getBoundingClientRect()
  position.value = { left: `${Math.max(8, Math.min(box.left, innerWidth - 376))}px`, bottom: `${innerHeight - box.top + 8}px`, maxHeight: `${Math.max(120, box.top - 16)}px` }
  open.value = true
  await nextTick(); focusableElements(panel.value)[0]?.focus()
}
async function navigate(value) { view.value = value; await nextTick(); focusableElements(panel.value)[0]?.focus() }
async function choose(action) {
  if (action.disabled) return
  if (['emoji', 'sticker', 'details'].includes(action.id)) { navigate(action.id); return }
  close(); await nextTick(); emit('action', action.id)
}
async function insertEmoji(value) { close(); await nextTick(); emit('emoji', value) }
function outside(event) { if (!trigger.value?.$el?.contains(event.target) && !panel.value?.contains(event.target)) close() }
watch(open, value => {
  document[value ? 'addEventListener' : 'removeEventListener']('pointerdown', outside)
  window[value ? 'addEventListener' : 'removeEventListener']('resize', close)
})
watch(() => props.disabled, value => { if (value && open.value) close() })
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', close) })
</script>
<template>
  <Button ref="trigger" class="composer-more-trigger" icon="plus" variant="ghost" aria-label="Attachments and more" title="Attachments and more"
    aria-haspopup="dialog" :aria-expanded="open" :disabled="disabled" @click="toggle" />
  <Teleport to=".v1-shell" defer>
    <div v-if="open && mobile" class="composer-more-backdrop" @click="close" />
    <section v-if="open" ref="panel" class="composer-more-panel" :class="{ 'is-sheet': mobile }" :style="mobile ? undefined : position"
      role="dialog" :aria-modal="mobile || undefined" :aria-label="title"
      @keydown="overlayKeydown($event, panel, close, { arrows: !view, trap: true })">
      <header><Button v-if="view" icon="arrow-left" variant="ghost" aria-label="Back to more options" @click="navigate('')" />
        <strong>{{ title }}</strong><Button icon="x" variant="ghost" aria-label="Close more options" @click="close" /></header>
      <template v-if="!view">
        <div v-for="group in groups" :key="group.id" class="composer-more-group" :class="'more-' + group.id">
          <p v-if="group.id === 'attachments'">ATTACH</p>
          <Button v-for="action in group.actions" :key="action.id" :label="action.label" :icon-left="action.icon" variant="ghost"
            :class="{ 'more-note': action.id === 'note' }" :disabled="action.disabled" @click="choose(action)" />
        </div>
      </template>
      <div v-else-if="view === 'emoji'" class="composer-emoji-grid">
        <Button v-for="[value, label] in composerEmoji" :key="label" :label="value" :aria-label="label" :title="label" @click="insertEmoji(value)" />
      </div>
      <div v-else-if="view === 'sticker'" class="composer-more-copy">
        <p>Open Message actions on a sticker in this conversation, then choose Resend sticker.</p>
        <p v-if="!hasSticker">No sticker in this conversation yet. A customer must send one before you can resend it.</p>
        <p>Stickers cannot be uploaded here.</p>
      </div>
      <div v-else class="composer-more-copy"><slot name="details" /></div>
    </section>
  </Teleport>
</template>
<style scoped>
.composer-more-panel { position:fixed; z-index:80; width:360px; max-width:calc(100vw - 16px); overflow:auto; overscroll-behavior:contain; padding:12px; border:1px solid var(--relay-stroke-strong); border-radius:12px; background:var(--surface-modal); color:var(--relay-ink); box-shadow:var(--relay-shadow-2); }
.composer-more-panel header { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.composer-more-panel header strong { flex:1; font-size:14px; }
.composer-more-panel :deep(.relay-button) { min-width:44px; min-height:44px; height:auto; font-size:12px; }
.composer-more-panel :deep(button:focus-visible) { outline:2px solid var(--relay-accent); outline-offset:2px; }
.composer-more-group { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.composer-more-group :deep(.relay-button) { justify-content:flex-start; }
.more-quick :deep(.relay-button) { background:var(--surface-blue-1); color:var(--relay-accent-text); }
.more-attachments { grid-template-columns:repeat(4,minmax(0,1fr)); }
.more-attachments p { grid-column:1/-1; margin:16px 4px 0; color:var(--relay-ink-3); font-size:11px; letter-spacing:1px; }
.more-attachments :deep(.relay-button) { flex-direction:column; justify-content:center; min-height:64px; padding:8px 2px; font-size:11px; }
.more-secondary, .more-details { margin-top:8px; padding-top:8px; border-top:1px solid var(--relay-stroke); }
.more-details { grid-template-columns:1fr; }
.more-note { color:var(--relay-note-ink); }
.composer-more-copy { font-size:13px; overflow-wrap:anywhere; }
.composer-more-copy p + p { margin-top:12px; }
.composer-emoji-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
.composer-emoji-grid :deep(.relay-button) { font-size:24px; }
.composer-more-backdrop { position:fixed; inset:0; background:var(--relay-overlay); z-index:79; }
.composer-more-panel.is-sheet { inset:auto 8px max(8px, env(safe-area-inset-bottom)); width:auto; max-height:calc(100dvh - 32px); border-radius:16px; padding-bottom:16px; }
</style>
