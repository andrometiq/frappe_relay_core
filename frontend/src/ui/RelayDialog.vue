<script setup>
import { computed, nextTick, onBeforeUnmount, watch } from 'vue'
import PrimeDialog from 'primevue/dialog'
const props = defineProps({ modelValue: Boolean, options: { type: Object, default: () => ({}) }, disableOutsideClickToClose: Boolean })
let origin
watch(() => props.modelValue, value => { if (value) origin = document.activeElement; else nextTick(restoreFocus) }, { immediate: true })
function restoreFocus() { if (origin?.isConnected) origin.focus({ preventScroll: true }) }
onBeforeUnmount(restoreFocus)
const emit = defineEmits(['update:modelValue', 'close'])
const sizes = { sm: 'relay-dialog--sm', lg: 'relay-dialog--lg', xl: 'relay-dialog--xl' }
const size = computed(() => sizes[props.options.size] || '')
const close = () => { emit('update:modelValue', false); emit('close') }
const pt = computed(() => ({ mask: { class: 'relay-dialog-mask' }, root: { class: ['relay-dialog', size.value] }, header: { class: 'relay-dialog__header' }, title: { class: 'relay-dialog__title' }, pcCloseButton: { root: { class: 'relay-dialog__close' } }, content: { class: 'relay-dialog__content' }, footer: { class: 'relay-dialog__footer' } }))
</script>
<template><PrimeDialog :visible="modelValue" modal :header="options.title" :dismissable-mask="!disableOutsideClickToClose" :close-on-escape="!disableOutsideClickToClose" :pt="pt" @update:visible="value => value ? $emit('update:modelValue', true) : close()"><slot name="body-content" /><slot /><template v-if="$slots.actions" #footer><slot name="actions" :close="close" /></template></PrimeDialog></template>

<style scoped>
:deep(.relay-dialog__close) { min-width:44px; min-height:44px; }
</style>
