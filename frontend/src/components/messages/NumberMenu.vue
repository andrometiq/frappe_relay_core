<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'
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
const open = ref(false), root = ref(null), list = ref(null)

function toggle() { if (!props.disabled) open.value = !open.value }
function choose(value) { model.value = value; open.value = false }
function outside(event) { if (!root.value?.contains(event.target) && !list.value?.contains(event.target)) open.value = false }
watch(open, async value => {
  document.removeEventListener('pointerdown', outside)
  if (!value) return
  document.addEventListener('pointerdown', outside)
  await nextTick()
  list.value?.querySelector('[aria-selected=true]')?.focus()
})
watch(() => props.disabled, value => { if (value) open.value = false })
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="number-menu" @keydown.esc="open = false">
    <slot :open="open" :toggle="toggle" />
    <Teleport to=".v1-shell" :disabled="!isMobile" defer>
      <Transition name="relay-fade"><button v-if="open && isMobile" type="button" class="mobile-sheet-backdrop" :aria-label="'Close ' + title" @click="open = false" /></Transition>
      <Transition :name="isMobile ? 'relay-sheet' : ''">
        <div v-if="open" ref="list" :class="isMobile ? 'mobile-sheet number-sheet' : ['number-pop', 'is-' + placement]"
          :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile || undefined" :aria-label="title" @keydown.esc="open = false">
          <span v-if="isMobile" class="mobile-sheet-handle" aria-hidden="true" />
          <h3 class="number-menu-title">{{ title }}</h3>
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
