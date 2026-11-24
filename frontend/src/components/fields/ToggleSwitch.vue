<script setup>
// An on/off switch for a settings row. The row's label names it.
defineProps({ label: { type: String, required: true }, disabled: Boolean })
const model = defineModel({ type: Boolean, default: false })
</script>

<template>
  <button type="button" role="switch" class="toggle-switch" :aria-checked="model" :aria-label="label" :disabled="disabled" @click="model = !model">
    <span aria-hidden="true" />
  </button>
</template>
