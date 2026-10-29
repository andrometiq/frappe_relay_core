<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import PrimePopover from 'primevue/popover'
import RelayIcon from './RelayIcon.vue'
import { focusableElements, overlayKeydown } from '../services/overlayFocus'
const props = defineProps({ options: { type: Array, default: () => [] }, placement: { type: String, default: 'bottom' }, touchTargets: Boolean })
const popover = ref(), menu = ref(), trigger = ref(), opened = ref(false)
const menuId = `relay-menu-${Math.random().toString(36).slice(2)}`
function updateTrigger() {
  const button = trigger.value?.querySelector('button')
  button?.setAttribute('aria-haspopup', 'menu')
  button?.setAttribute('aria-expanded', String(opened.value))
  button?.setAttribute('aria-controls', menuId)
}
onMounted(updateTrigger)
watch(opened, updateTrigger)
const toggle = (event, target) => popover.value?.toggle(event, target)
defineExpose({ toggle })
function close() { popover.value?.hide() }
let observer
onBeforeUnmount(() => observer?.disconnect())
function hidden() { observer?.disconnect(); opened.value = false; trigger.value?.querySelector('button')?.focus({ preventScroll: true }) }
async function shown() {
  opened.value = true
  await nextTick()
  place()
  // PrimeVue realigns after its content resize observer; apply the requested side after that pass too.
  observer?.disconnect()
  observer = new ResizeObserver(place)
  if (menu.value) observer.observe(menu.value)
  focusableElements(menu.value)[0]?.focus()
}
function place() {
  const node = popover.value?.container, box = trigger.value?.getBoundingClientRect()
  if (node && box && ['top', 'above', 'top-start'].includes(props.placement)) {
    node.style.top = `${Math.max(8, box.top + window.scrollY - node.offsetHeight - 8)}px`
    node.style.left = `${Math.max(8, Math.min(box.left + window.scrollX, window.innerWidth - node.offsetWidth - 8))}px`
    node.style.transformOrigin = 'bottom'
  }
}
const choose = option => { if (option.disabled) return; close(); option.onClick?.() }
const pt = computed(() => ({ root: { class: ['relay-menu', { 'relay-menu--touch': props.touchTargets }] }, content: { class: 'relay-menu__content' }, transition: { onAfterEnter: place } }))
</script>
<template><span ref="trigger" class="relay-dropdown-trigger" @click="toggle" @keydown.down.prevent="!opened && toggle($event, trigger)" @keydown.esc="close"><slot /></span><PrimePopover ref="popover" :pt="pt" @show="shown" @hide="hidden"><div ref="menu" :id="menuId" role="menu" class="relay-menu__items" @keydown="overlayKeydown($event, menu, close, { arrows: true })"><button v-for="(option,index) in options" :key="option.value ?? option.label ?? index" type="button" role="menuitem" class="relay-menu__item" :disabled="option.disabled" @click="choose(option)"><RelayIcon v-if="option.icon" :name="option.icon" /><span>{{ option.label }}</span></button></div></PrimePopover></template>
