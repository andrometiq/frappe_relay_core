<script setup>
import { computed } from 'vue'
import PrimeButton from 'primevue/button'
import RelayIcon from './RelayIcon.vue'

const props = defineProps({
  label: { type: [String, Number], default: '' }, icon: String, iconLeft: String, iconRight: String,
  variant: { type: String, default: 'subtle' }, theme: { type: String, default: 'gray' },
  size: { type: String, default: 'sm' }, loading: Boolean, disabled: Boolean, type: { type: String, default: 'button' },
})
// outline is the base bordered look: a secondary action that still reads as a button.
const variants = { solid: 'relay-button--solid', subtle: 'relay-button--subtle', ghost: 'relay-button--ghost', outline: 'relay-button--outline' }
const themes = { gray: 'relay-button--gray', red: 'relay-button--red', blue: 'relay-button--blue', green: 'relay-button--green' }
const sizes = { xs: 'relay-button--xs', sm: 'relay-button--sm', lg: 'relay-button--lg' }
const classes = computed(() => [
  'relay-button', variants[props.variant], themes[props.theme], sizes[props.size],
  { 'relay-button--icon-only': !props.label && !useDefault.value, 'is-loading': props.loading },
])
const slots = defineSlots()
const useDefault = computed(() => Boolean(slots.default))
</script>

<template>
  <PrimeButton :type="type" :disabled="disabled || loading" :loading="loading" :class="classes">
    <RelayIcon v-if="loading" name="loader-circle" class="relay-button__spinner" />
    <RelayIcon v-else-if="iconLeft || icon" :name="iconLeft || icon" />
    <span v-if="label" class="relay-button__label">{{ label }}</span><slot v-else />
    <RelayIcon v-if="iconRight" :name="iconRight" />
  </PrimeButton>
</template>
