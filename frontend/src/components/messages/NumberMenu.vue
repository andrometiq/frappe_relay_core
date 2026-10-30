<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'
import { focusableElements, overlayKeydown } from '../../services/overlayFocus'
import { countLabel } from '../../services/queueCounts'

/** WhatsApp number choices: a popover on desktop and a bottom sheet on the phone. */
const props = defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  placement: { type: String, default: 'below' },
  divided: Boolean,
  disabled: Boolean,
})
const model = defineModel({ type: String, default: '' })
const isMobile = useMobileLayout()
const open = ref(false), root = ref(null), list = ref(null), position = ref({})

// The desktop popover is fixed to the trigger, so a scrolling composer or list never clips it.
function place() {
  const box = root.value?.getBoundingClientRect()
  if (!box || isMobile.value) return
  position.value = props.placement === 'above'
    ? { right: `${Math.max(8, innerWidth - box.right)}px`, bottom: `${innerHeight - box.top + 6}px`, width: `${Math.min(380, innerWidth - 16)}px` }
    : { left: `${box.left}px`, top: `${box.bottom + 4}px`, width: `${Math.max(260, box.width)}px` }
}
function toggle() { if (!props.disabled) { place(); open.value = !open.value } }
function choose(value) { model.value = value; close() }
function outside(event) { if (!root.value?.contains(event.target) && !list.value?.contains(event.target)) close() }
watch(open, async value => {
  document.removeEventListener('pointerdown', outside)
  removeEventListener('resize', close)
  if (!value) return
  document.addEventListener('pointerdown', outside)
  addEventListener('resize', close)
  await nextTick()
  ;(list.value?.querySelector('[aria-selected=true]') || focusableElements(list.value)[0])?.focus()
})
watch(() => props.disabled, value => { if (value) open.value = false })
function close() { open.value = false; nextTick(() => root.value?.querySelector('button')?.focus({ preventScroll: true })) }
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); removeEventListener('resize', close) })
</script>

<template>
  <div ref="root" class="number-menu" @keydown.esc="close">
    <slot :open="open" :toggle="toggle" />
    <Teleport to=".v1-shell" defer>
      <Transition name="relay-fade"><button v-if="open && isMobile" type="button" class="mobile-sheet-backdrop" :aria-label="'Close ' + title" @click="close" /></Transition>
      <Transition :name="isMobile ? 'relay-sheet' : ''">
        <div v-if="open" ref="list" :class="isMobile ? 'mobile-sheet number-sheet' : 'number-pop'" :style="isMobile ? undefined : position"
          :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile || undefined" :aria-label="title" @keydown="overlayKeydown($event, list, close, { arrows: true })">
          <span v-if="isMobile" class="mobile-sheet-handle" aria-hidden="true" />
          <div class="number-menu-heading"><h3 class="number-menu-title">{{ title }}</h3><button type="button" aria-label="Close sender choices" @click="close"><FeatherIcon name="x" /></button></div>
          <p v-if="isMobile && hint" class="number-sheet-hint">{{ hint }}</p>
          <div role="listbox" :aria-label="title">
            <template v-for="(option, index) in options" :key="option.value">
              <hr v-if="divided && index === 1 && !isMobile">
              <button type="button" role="option" class="number-option" :aria-selected="model === option.value" @click="choose(option.value)">
                <FeatherIcon v-if="option.value" name="message-circle" class="number-wa" />
                <span class="number-option-main">{{ option.label }}<template v-if="option.inline && option.address"> · {{ option.address }}</template>
                  <small v-if="option.status" :class="option.templateOnly ? 'is-warn' : 'is-ok'">{{ option.status }}</small>
                  <small v-else-if="option.address && !option.inline">{{ option.address }}</small></span>
                <span v-if="countLabel(option.count)" class="number-option-count">{{ countLabel(option.count) }}</span>
                <FeatherIcon v-if="model === option.value" name="check" class="number-tick" />
              </button>
            </template>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.number-menu-heading { display:flex; align-items:center; justify-content:space-between; }
.number-menu-heading button, .number-option { min-height:44px; min-width:44px; }
.number-menu-heading button { display:grid; place-items:center; }
.number-option:focus-visible, .number-menu-heading button:focus-visible { outline:2px solid var(--relay-accent); outline-offset:-2px; }
</style>
