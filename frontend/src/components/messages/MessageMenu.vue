<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { FeatherIcon } from '@relay/ui'

// The actions of one message. Wide screens: a menu kept inside the message area. Phones: a bottom sheet.
const props = defineProps({ trigger: Object, area: Object, sheet: Boolean, emoji: { type: Array, default: () => [] }, current: String, items: Array })
const emit = defineEmits(['close', 'react', 'more'])
const panel = ref(null), position = ref({ visibility: 'hidden' })

// The sheet lifts the chosen message above itself, so the message stays in view.
function lift() {
  const overlap = props.trigger.getBoundingClientRect().bottom + 12 - (innerHeight - panel.value.offsetHeight)
  if (overlap <= 0) return
  props.area.style.paddingBottom = panel.value.offsetHeight + 'px'
  props.area.scrollTop += overlap
}
function place() {
  if (props.sheet) { position.value = {}; lift(); return }
  const area = props.area.getBoundingClientRect(), at = props.trigger.getBoundingClientRect(), box = panel.value.getBoundingClientRect()
  const height = Math.min(box.height, area.height - 16)
  let top = at.bottom + 4
  if (top + height > area.bottom - 8) top = at.top - 4 - height
  top = Math.max(area.top + 8, Math.min(top, area.bottom - 8 - height))
  const left = Math.max(area.left + 8, Math.min(at.right - box.width, area.right - 8 - box.width))
  position.value = { top: top + 'px', left: left + 'px', maxHeight: height + 'px' }
}
function close() { emit('close') }
function choose(item) { close(); item.onClick() }
function outside(event) { if (!props.sheet && !panel.value?.contains(event.target) && !props.trigger?.contains(event.target)) close() }
function escape(event) { if (event.key === 'Escape') { close(); props.trigger?.focus?.() } }
onMounted(async () => {
  await nextTick()
  place()
  panel.value?.querySelector('button:not(:disabled)')?.focus({ preventScroll: true })
  document.addEventListener('pointerdown', outside, true)
  document.addEventListener('keydown', escape)
  window.addEventListener('resize', close)
  if (!props.sheet) props.area?.addEventListener('scroll', close, { passive: true })
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside, true)
  document.removeEventListener('keydown', escape)
  window.removeEventListener('resize', close)
  props.area?.removeEventListener('scroll', close)
  if (props.sheet && props.area) props.area.style.paddingBottom = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="sheet" class="message-sheet-backdrop" aria-hidden="true" @click="close" />
    <div ref="panel" class="relay-menu message-menu" :class="{ 'is-sheet': sheet }" :style="position" role="menu" aria-label="Message actions">
      <div v-if="emoji.length" class="message-menu-emoji" role="group" aria-label="React">
        <button v-for="value in emoji" :key="value" type="button" :class="{ 'is-current': value === current }" :aria-pressed="value === current"
          :aria-label="'React ' + value" @click="emit('react', value); close()">{{ value }}</button>
        <button type="button" aria-label="More reactions" title="More reactions" @click="emit('more'); close()"><FeatherIcon name="plus" :size="18" /></button>
      </div>
      <template v-for="(item, index) in items" :key="item.label || 'divider' + index">
        <hr v-if="item.divider" class="message-menu-divider" />
        <button v-else type="button" role="menuitem" class="relay-menu__item" :disabled="item.disabled" @click="choose(item)">
          <FeatherIcon :name="item.icon" :size="16" /><span>{{ item.label }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>

<style scoped>
.message-menu .relay-menu__item { min-height:44px; }
.message-menu { position:fixed; z-index:90; display:flex; flex-direction:column; gap:1px; width:232px; padding:4px; overflow:auto; }
.message-menu-emoji { display:flex; justify-content:space-between; gap:2px; padding:2px 2px 6px; margin-bottom:4px; border-bottom:1px solid var(--relay-stroke, var(--outline-gray-2)); }
.message-menu-emoji button { display:grid; place-items:center; width:34px; height:34px; min-height:34px; border-radius:999px; font-size:20px; line-height:1; color:var(--ink-gray-7); }
.message-menu-emoji button:hover, .message-menu-emoji button:focus-visible { background:var(--relay-hover, var(--surface-gray-2)); outline:0; }
.message-menu-emoji button.is-current { background:var(--surface-blue-1, #e6f0ff); }
.message-menu-divider { margin:4px 0; border:0; border-top:1px solid var(--relay-stroke, var(--outline-gray-2)); }
.message-sheet-backdrop { position:fixed; inset:0; z-index:89; background:transparent; }
.message-menu.is-sheet { inset:auto 0 0 0; width:auto; max-height:70vh; padding:8px 8px calc(8px + env(safe-area-inset-bottom)); border-radius:16px 16px 0 0; animation:message-sheet-in 180ms ease-out; }
.message-menu.is-sheet::before { content:''; align-self:center; width:36px; height:4px; margin:0 0 8px; border-radius:2px; background:var(--outline-gray-3, #ccc); }
.message-menu.is-sheet .relay-menu__item { min-height:48px; font-size:15px; }
.message-menu.is-sheet .message-menu-emoji button { width:44px; height:44px; font-size:24px; }
@keyframes message-sheet-in { from { transform:translateY(100%); } }
</style>
